from datetime import datetime, timedelta
import pytz
from app.services.session_service import RedisSession
from app.core.enums import SessionState
from app.utils.message_manager import MessageManager
from app.utils.whatsapp import send_whatsapp_text
from app.state_machines.factory import StateMachineFactory
from app.tasks import sync_sheets_with_redis_task
from app.services.pre_clasifyer_service import PreClasifyerService
from app.services.llm_extraction_service import LLMExtractionService

# TODO: Implement the custom exceptions to better debugging and error handling


class ChatbotService:
    def __init__(self, message_manager: MessageManager, factory: StateMachineFactory):
        self.message_manager = message_manager
        self.factory = factory
        self.argentina_tz = pytz.timezone("America/Argentina/Buenos_Aires")
        self.guard = PreClasifyerService()
        self.extractor = LLMExtractionService()

    async def process_message(
        self, redis_session: RedisSession, from_number: str, body: str, name: str
    ):
        if not await redis_session.load_session():
            return await self._handle_new_session(
                redis_session, from_number, body, name
            )

        return await self._handle_existing_session(redis_session, from_number, body)

    async def _handle_new_session(
        self, redis_session: RedisSession, from_number: str, body: str, name: str
    ):
        # Destination is determined by the exact ad message — no LLM needed here
        ad_destination = await self.message_manager.get_destination_by_message(body)
        required_fields = await self.message_manager.get_required_fields_by_message(
            body
        )
        actual_session = {
            "state": SessionState.GETTING_AD_DESTINATION,
            "full_name": name,
            "destination": ad_destination,
            "required_fields": required_fields,
            "num_travelers_message": None,
            "num_travelers": None,
            "num_underage_travelers": None,
            "departure_location": None,
            "departure_iata_code": None,
            "date": None,
            "date_of_contact": datetime.now(self.argentina_tz).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "count_requests": 1,
            "messages_history": [],
        }

        if actual_session.get("destination") != "unknown":
            actual_session["state"] = SessionState.ASKING_NUM_TRAVELERS
            initial_message = f"¡Hola Viajero! 👋🏻 Somos Agos y Meli de Etnia Viajes ✨\nNos escribiste por un viaje a: {ad_destination}."
            actual_session["messages_history"].append(
                {"role": "assistant", "content": initial_message}
            )
            initial_question_message = "¿Para cuántas personas sería? Si viajan menores, contanos cuántos son 😉"
            actual_session["messages_history"].append(
                {"role": "assistant", "content": initial_question_message}
            )
            await send_whatsapp_text(
                from_number,
                initial_message,
            )
            await send_whatsapp_text(
                from_number,
                initial_question_message,
            )
            await redis_session.save_session(actual_session)
            sync_sheets_with_redis_task.delay()
            return {"status": "ok"}
        else:
            return {"status": "400", "detail": "The message is not from an ad"}

    async def _handle_existing_session(
        self, redis_session: RedisSession, from_number: str, body: str
    ):
        actual_session = redis_session.session
        actual_session["count_requests"] += 1
        state = redis_session.state

        contact_time = self.argentina_tz.localize(
            datetime.strptime(actual_session.get("date_of_contact"), "%Y-%m-%d %H:%M")
        )

        # ── Timeout check ───────────────────────────────────────
        if (
            datetime.now(self.argentina_tz) - contact_time > timedelta(hours=1)
            and actual_session.get("state") not in SessionState.handoff_states()
        ):
            actual_session["state"] = SessionState.HANDOFF_TIMEOUT
            await redis_session.save_session(actual_session)
            # TODO: Send the most common offer to the user
            return {"status": "400", "detail": "Session timeout"}

        # ── Max requests / already handed off ──────────────────
        if (
            actual_session["count_requests"] > 10
            or state in SessionState.handoff_states()
        ):
            # TODO: Send message delegating conversation to a human agent
            return {"status": "400", "detail": "Session ended or max requests reached"}

        # ── Guard Agent ───────────────────────────────────────────────────────
        classification = await self.guard.classify_message(body)
        if not classification.get("is_travel_related") or not classification.get(
            "is_safe"
        ):
            # TODO: Implement reinforcement learning by human feedback to improve classification accuracy
            return {"status": "406", "detail": "The message is not acceptable"}

        # ── Extraction Agent ──────────────────────────────────────────────────
        # TODO: Make a buffer of messages to have multiple messages stored in 3 seconds before sending to the LLM and get the total context
        actual_session["messages_history"].append({"role": "user", "content": body})
        result = await self.extractor.extract(body, actual_session)

        # Merge extracted info into session (only overwrite if a new value was found)
        if result.num_travelers is not None:
            actual_session["num_travelers"] = result.num_travelers
        if result.num_underage_travelers is not None:
            actual_session["num_underage_travelers"] = result.num_underage_travelers
        if result.date is not None:
            actual_session["date"] = result.date
        if result.departure_location is not None:
            actual_session["departure_location"] = result.departure_location
            actual_session["departure_iata_code"] = (
                await self.message_manager.get_iata_code(result.departure_location)
            )

        # ── Route based on completeness ───────────────────────────────────────
        if result.is_complete and actual_session.get("departure_iata_code"):
            message_offer = await self.message_manager.get_message_offer(actual_session)

            if message_offer:
                await send_whatsapp_text(from_number, message_offer)
                await send_whatsapp_text(
                    from_number,
                    "✨ Decime si esta opción es la que buscás o si preferís que la acomodemos (fecha, hotel, compañía), o si querés que te enviemos otras opciones.",
                )
                actual_session["state"] = SessionState.HANDOFF_WITH_OFFER
            else:
                # Info complete but no matching offer in messages_db.json
                await send_whatsapp_text(from_number, result.response_message)
                actual_session["state"] = SessionState.HANDOFF_NO_OFFER
        else:
            # Still collecting info — send the LLM's conversational follow-up
            await send_whatsapp_text(from_number, result.response_message)

        sync_sheets_with_redis_task.delay()
        await redis_session.save_session(actual_session)
        return {"status": "ok"}
