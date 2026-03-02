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

    # ─────────────────────────────────────────────────────────────────────────
    # New session — detect destination then send offers deterministically
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_new_session(
        self, redis_session: RedisSession, from_number: str, body: str, name: str
    ):
        ad_destination, offer_type = await self.message_manager.get_ad_info(body)

        if ad_destination == "unknown":
            return {
                "status": "400",
                "detail": "Destination not found in actual offers",
            }

        actual_session = {
            "state": SessionState.PRESENTING_OFFERS,
            "date_of_contact": datetime.now(self.argentina_tz).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "full_name": name,
            "destination": ad_destination,
            "offer_type": offer_type,
            "count_requests": 1,
            "messages_history": [],
            "num_travelers": None,
            "num_underage_travelers": None,
            "departure_location": None,
            "departure_iata_code": None,
            "date": None,
        }

        return await self._start_offer_presentation(
            actual_session, redis_session, from_number
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2 — Deterministic offer presentation (no LLM)
    # ─────────────────────────────────────────────────────────────────────────

    async def _start_offer_presentation(
        self,
        actual_session: dict,
        redis_session: RedisSession,
        from_number: str,
    ):
        """
        Send the greeting + all available offer messages directly from offers_db.
        No LLM is used here — the texts are already written.
        State is set to PRESENTING_OFFERS so the next message goes to extract_with_offers().
        """
        destination = actual_session["destination"]
        name = actual_session.get("full_name", "Viajero")

        # ── 1. Greeting ───────────────────────────────────────────────────────
        intro = (
            f"¡Hola!👋🏻 Somos Etnia Viajes ✨\n"
            f"Nos escribiste por un viaje a {destination.title()}."
        )
        await send_whatsapp_text(from_number, intro)
        actual_session["messages_history"].append(
            {"role": "assistant", "content": intro}
        )

        # ── 2. Send all available offer messages for this destination ─────────
        offers = self.message_manager.get_offers_for_destination(destination)

        # TODO: Handle no offers case with fully agent to extract information

        for _key, offer_text in offers:
            await send_whatsapp_text(from_number, offer_text)

        # ── 3. Closing question ───────────────────────────────────────────────
        closing = (
            "¿Que te parecen estas opciones? "
            "Si preferís, también podemos armarte algo a medida 😊"
        )
        await send_whatsapp_text(from_number, closing)
        actual_session["messages_history"].append(
            {"role": "assistant", "content": closing}
        )

        actual_session["state"] = SessionState.PRESENTING_OFFERS
        await redis_session.save_session(actual_session)
        sync_sheets_with_redis_task.delay()
        return {"status": "ok"}

    # ─────────────────────────────────────────────────────────────────────────
    # Dispatcher for existing sessions
    # ─────────────────────────────────────────────────────────────────────────

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
            
            return {"status": "406", "detail": "The message is not acceptable"}

        actual_session["messages_history"].append({"role": "user", "content": body})

        # ── Route to the correct stage ────────────────────────────────────────
        if state == SessionState.PRESENTING_OFFERS:
            return await self._handle_offer_reply(
                actual_session, redis_session, from_number, body
            )
        elif state == SessionState.EXTRACTING_INFORMATION:
            return await self._handle_extraction(
                actual_session, redis_session, from_number, body
            )

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2 — Handle user reply to offers (single LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_offer_reply(
        self,
        actual_session: dict,
        redis_session: RedisSession,
        from_number: str,
        body: str,
    ):
        """
        Single LLM call that does both:
        - Detect if the user accepted one of the pre-sent offers
        - OR extract any info they already provided (departure, travelers, date)
        """
        destination = actual_session.get("destination")
        valid_offer_keys = [
            key
            for key, _ in self.message_manager.get_offers_for_destination(destination)
        ]
        offers_summary = self.message_manager.get_offers_summary_for_destination(
            destination
        )

        result = await self.extractor.extract_with_offers(
            message=body,
            session=actual_session,
            valid_offer_keys=valid_offer_keys,
            offers_summary=offers_summary,
        )

        actual_session["messages_history"].append(
            {"role": "assistant", "content": result.response_message}
        )

        if result.offer_accepted and result.accepted_offer_key:
            # ── User accepted a pre-built offer ──────────────────────────────
            # The offer text was already sent and is in the history — no need to resend.
            # Just confirm and hand off.
            confirm_msg = "✨ ¡Perfecto! Un asesor se va a contactar con vos para coordinar los detalles y confirmar la reserva."
            await send_whatsapp_text(from_number, confirm_msg)
            actual_session["messages_history"].append(
                {"role": "assistant", "content": confirm_msg}
            )
            actual_session["state"] = SessionState.HANDOFF_WITH_OFFER
            actual_session["accepted_offer_key"] = result.accepted_offer_key

        else:
            # ── User wants custom quote — merge any extracted info ────────────
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

            if result.is_complete:
                # All info gathered — hand off to agent
                handoff_msg = (
                    "Perfecto, ya tenemos toda la información. "
                    "Un asesor se va a contactar con vos para armarte una propuesta. 😊"
                )
                await send_whatsapp_text(from_number, handoff_msg)
                actual_session["state"] = SessionState.HANDOFF_NO_OFFER
            else:
                # Still missing fields — ask for the next one
                await send_whatsapp_text(from_number, result.response_message)
                actual_session["state"] = SessionState.EXTRACTING_INFORMATION

        sync_sheets_with_redis_task.delay()
        await redis_session.save_session(actual_session)
        return {"status": "ok"}

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 3 — Custom Quote Extraction
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_extraction(
        self,
        actual_session: dict,
        redis_session: RedisSession,
        from_number: str,
        body: str,
    ):
        """Continue extracting missing fields for a custom quote."""
        extraction = await self.extractor.extract(body, actual_session)

        if extraction.num_travelers is not None:
            actual_session["num_travelers"] = extraction.num_travelers
        if extraction.num_underage_travelers is not None:
            actual_session["num_underage_travelers"] = extraction.num_underage_travelers
        if extraction.date is not None:
            actual_session["date"] = extraction.date
        if extraction.departure_location is not None:
            actual_session["departure_location"] = extraction.departure_location
            actual_session["departure_iata_code"] = (
                await self.message_manager.get_iata_code(extraction.departure_location)
            )

        if extraction.is_complete and actual_session.get("departure_iata_code"):
            handoff_msg = (
                "Perfecto, ya tenemos toda la información. "
                "Un asesor se va a contactar con vos para armarte una propuesta. 😊"
            )
            await send_whatsapp_text(from_number, handoff_msg)
            actual_session["state"] = SessionState.HANDOFF_NO_OFFER
        else:
            await send_whatsapp_text(from_number, extraction.response_message)

        sync_sheets_with_redis_task.delay()
        await redis_session.save_session(actual_session)
        return {"status": "ok"}
