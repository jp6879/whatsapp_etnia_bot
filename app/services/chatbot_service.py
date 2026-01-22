from app.core.exceptions import DestinationNotInPubliclyOfferedError
from datetime import datetime, timedelta
import pytz
from fastapi import HTTPException
from app.services.session_service import RedisSession
from app.core.enums import SessionState
from app.utils.message_manager import MessageManager
from app.utils.whatsapp import send_whatsapp_text
from app.state_machines.factory import StateMachineFactory
from app.tasks import sync_sheets_with_redis_task
from app.utils.logger import logger

class ChatbotService:
    def __init__(self, message_manager: MessageManager, factory: StateMachineFactory):
        self.message_manager = message_manager
        self.factory = factory
        self.argentina_tz = pytz.timezone("America/Argentina/Buenos_Aires")

    async def process_message(
        self, redis_session: RedisSession, from_number: str, body: str, name: str
    ):
        logger.debug(f"Received message from {from_number}: {body}")

        if not await redis_session.load_session():
            return await self._handle_new_session(
                redis_session, from_number, body, name
            )

        return await self._handle_existing_session(redis_session, from_number, body)

    async def _handle_new_session(
        self, redis_session: RedisSession, from_number: str, body: str, name: str
    ):
        ad_destination = await self.message_manager.get_destination_by_message(body)
        actual_session = {
            "state": SessionState.GETTING_AD_DESTINATION,
            "full_name": name,
            "destination": ad_destination,
            "num_travelers_message": None,
            "num_travelers": 0,
            "num_underage_travelers": 0,
            "departure_location": None,
            "departure_iata_code": None,
            "date_of_contact": datetime.now(self.argentina_tz).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "count_requests": 1,
        }

        if actual_session.get("destination") != "unknown":
            # send initial greeting + first question
            actual_session["state"] = SessionState.ASKING_NUM_TRAVELERS
            await send_whatsapp_text(
                from_number,
                f"¡Hola Viajero! 👋🏻 Somos Agos y Meli de Etnia Viajes ✨\nNos escribiste por un viaje a: {ad_destination}.",
            )
            await send_whatsapp_text(
                from_number,
                "¿Para cuántas personas sería? Si viajan menores, contanos cuántos son 😉",
            )
            await redis_session.save_session(actual_session)
            sync_sheets_with_redis_task.delay()
            return {"status": "ok"}
        else:
            raise DestinationNotInPubliclyOfferedError(
                detail="Destination not recognized in message"
            )

    async def _handle_existing_session(
        self, redis_session: RedisSession, from_number: str, body: str
    ):
        actual_session = redis_session.session
        actual_session["count_requests"] += 1
        state = redis_session.state

        contact_time = self.argentina_tz.localize(
            datetime.strptime(actual_session.get("date_of_contact"), "%Y-%m-%d %H:%M")
        )

        # Timeout check
        if (
            datetime.now(self.argentina_tz) - contact_time > timedelta(hours=1)
            and actual_session.get("state") not in SessionState.handoff_states()
        ):
            actual_session["state"] = SessionState.HANDOFF_TIMEOUT
            await redis_session.save_session(actual_session)
            return {"status": "400", "detail": "Session timeout"}

        # Max requests check
        if (
            actual_session["count_requests"] > 10
            or state in SessionState.handoff_states()
        ):
            return {"status": "400", "detail": "Session ended or max requests reached"}

        # Delegate to State Machine for all processing beyond initialization
        # Identify the correct SM
        destination = actual_session.get("destination")
        sm = self.factory.get_sm(destination)

        # Process
        updated_session = await sm.process(actual_session, body, from_number)

        # Save session
        await redis_session.save_session(updated_session)

        return {"status": "ok"}
