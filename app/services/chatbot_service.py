from datetime import datetime, timedelta
import logging
import pytz
from app.services.session_service import RedisSession
from app.core.enums import SessionState
from app.utils.message_manager import MessageManager
from app.utils.whatsapp import send_whatsapp_text
from app.tasks import sync_sheets_with_redis_task
from app.services.pre_classifier_service import PreClassifierService
from app.services.llm_extraction_service import LLMExtractionService

logger = logging.getLogger("chatbot")


class ChatbotService:
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager
        self.argentina_tz = pytz.timezone("America/Argentina/Buenos_Aires")
        self.guard = PreClassifierService()
        self.llm_extractor = LLMExtractionService()

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
        ad_destination, destination_key, offer_type = self.message_manager.get_ad_info(
            body
        )
        logger.debug(
            "[NEW SESSION] body=%r → destination=%r offer_type=%r destination_key=%r",
            body[:60],
            ad_destination,
            offer_type,
            destination_key,
        )

        if ad_destination == "unknown":
            logger.debug("[NEW SESSION] ❌ Destination unknown — rejecting")
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
            "destination_key": destination_key,
            "count_requests": 1,
            "messages_history": [{"role": "user", "content": body}],
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
        destination_key = actual_session["destination_key"]
        name = actual_session.get("full_name", "Viajero")
        logger.debug(
            "[STAGE 1→2] Starting offer presentation for destination=%r name=%r destination_key=%r",
            destination,
            name,
            destination_key,
        )

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
        offer_data = self.message_manager.get_offer_for_destination_key(destination_key)

        await send_whatsapp_text(from_number, offer_data["message"])

        # ── 3. Closing question ───────────────────────────────────────────────
        closing = "Decime qué mes te interesa y para cuántas personas, y lo vemos más a medida 😊✈️"
        await send_whatsapp_text(from_number, closing)

        actual_session["messages_history"].append(
            {"role": "assistant", "content": offer_data["message"]}
        )
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
        actual_session["count_requests"] = actual_session.get("count_requests", 0) + 1
        state = redis_session.state

        raw_contact = actual_session.get("date_of_contact")
        try:
            contact_time = self.argentina_tz.localize(
                datetime.strptime(raw_contact, "%Y-%m-%d %H:%M")
            )
        except (TypeError, ValueError):
            logger.warning(
                "[SESSION] Invalid date_of_contact=%r — resetting to now", raw_contact
            )
            contact_time = datetime.now(self.argentina_tz)
            actual_session["date_of_contact"] = contact_time.strftime("%Y-%m-%d %H:%M")

        # ── Timeout check ───────────────────────────────────────
        if (
            datetime.now(self.argentina_tz) - contact_time > timedelta(hours=1)
            and state not in SessionState.handoff_states()
        ):
            actual_session["state"] = SessionState.HANDOFF_TIMEOUT
            await redis_session.save_session(actual_session)
            return {"status": "ok", "detail": "Session timeout — handed off"}

        # ── Max requests / already handed off ──────────────────
        if (
            actual_session["count_requests"] > 10
            or state in SessionState.handoff_states()
        ):
            # TODO: Send message delegating conversation to a human agent
            await redis_session.save_session(actual_session)
            return {"status": "ok", "detail": "Session ended or max requests reached"}

        # ── Guard Agent ───────────────────────────────────────────────────────
        guard_context = {
            "destination": actual_session.get("destination"),
            "state": str(state),
        }
        classification = await self.guard.classify_message(body, context=guard_context)
        logger.debug("[GUARD] result=%r", classification)
        if not classification.get("is_travel_related") or not classification.get(
            "is_safe"
        ):
            logger.debug("[GUARD] ❌ Message blocked")
            await redis_session.save_session(actual_session)
            return {"status": "406", "detail": "The message is not acceptable"}

        logger.debug("[ROUTER] state=%r → routing...", state)
        # ── Route to the correct stage ────────────────────────────────────────
        if state == SessionState.PRESENTING_OFFERS:
            return await self._present_offers(
                actual_session, redis_session, from_number, body
            )
        if state == SessionState.EXTRACTING_INFORMATION:
            return await self._handle_extraction(
                actual_session, redis_session, from_number, body
            )

        logger.warning("[ROUTER] Unhandled state=%r — handing off", state)
        actual_session["state"] = SessionState.HANDOFF_NO_OFFER
        await redis_session.save_session(actual_session)
        return {"status": "ok", "detail": f"Unhandled state {state} — handed off"}

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2 — Handle user reply to offers (single LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    async def _present_offers(
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

        result = await self.llm_extractor.combined_extraction_answer(
            message=body,
            session=actual_session,
        )
        logger.debug(
            "[STAGE 2 LLM] offer_accepted=%r is_complete=%r travelers=%r departure=%r date=%r",
            result.offer_accepted,
            result.is_complete,
            result.num_travelers,
            result.departure_location,
            result.date,
        )

        if result.offer_accepted:
            # ── User accepted a pre-built offer ──────────────────────────────
            # The offer text was already sent and is in the history — no need to resend.
            # Just confirm and hand off.
            confirm_msg = "✨ ¡Perfecto! Un asesor se va a contactar con vos para coordinar los detalles y confirmar la reserva."
            await send_whatsapp_text(from_number, confirm_msg)
            actual_session["messages_history"].append(
                {"role": "assistant", "content": confirm_msg}
            )
            actual_session["state"] = SessionState.HANDOFF_WITH_OFFER

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
                    self.message_manager.get_iata_code(result.departure_location)
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
        extraction = await self.llm_extractor.extract(body, actual_session)
        logger.debug(
            "[STAGE 3 LLM] is_complete=%r travelers=%r underage=%r departure=%r date=%r",
            extraction.is_complete,
            extraction.num_travelers,
            extraction.num_underage_travelers,
            extraction.departure_location,
            extraction.date,
        )

        if extraction.num_travelers is not None:
            actual_session["num_travelers"] = extraction.num_travelers
        if extraction.num_underage_travelers is not None:
            actual_session["num_underage_travelers"] = extraction.num_underage_travelers
        if extraction.date is not None:
            actual_session["date"] = extraction.date
        if extraction.departure_location is not None:
            actual_session["departure_location"] = extraction.departure_location
            actual_session["departure_iata_code"] = self.message_manager.get_iata_code(
                extraction.departure_location
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
