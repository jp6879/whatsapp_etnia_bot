from app.state_machines.base import BaseStateMachine
from app.utils.whatsapp import send_whatsapp_text
from app.tasks import sync_sheets_with_redis_task
from app.core.enums import SessionState


class SeasonalSM(BaseStateMachine):
    async def process(self, session: dict, body: str, from_number: str) -> dict:
        state = session.get("state")

        if state == SessionState.ASKING_NUM_TRAVELERS:
            return await self._handle_asking_num_travelers(session, body, from_number)

        if state == SessionState.ASKING_DEPARTURE:
            return await self._handle_asking_departure(session, body, from_number)

        if state == SessionState.ASKING_DEPARTURE_DATE:
            return await self._handle_asking_date(session, body, from_number)

        return session

    async def _handle_asking_departure(self, session, body, from_number):
        # 1. Extract Departure (Origin)
        if (
            session["departure_location"] is None
            and session["departure_iata_code"] is None
        ):
            session["departure_location"] = body
            departure_iata = await self.message_manager.get_iata_code(body)
            session["departure_iata_code"] = departure_iata

            if not departure_iata:
                session["state"] = SessionState.HANDOFF_NO_DEPARTURE
                sync_sheets_with_redis_task.delay()
                await send_whatsapp_text(
                    from_number,
                    "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
                )
                return session

        # 2. Transition to Asking Date (Month) instead of offering immediately
        session["state"] = SessionState.ASKING_DEPARTURE_DATE
        sync_sheets_with_redis_task.delay()

        await send_whatsapp_text(from_number, "Contanos en que mes te gustaría viajar")
        return session

    async def _handle_asking_date(self, session, body, from_number):
        month = self.message_manager.get_month_from_message(body)

        if not month:
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        # Strict validation: 2 adults, 0 minors
        if not self._validate_travelers(session):
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        session["departure_month"] = month

        # Strict validation: 2 adults, 0 minors
        if not session["departure_month"] in [
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
        ]:
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        message_to_send = await self.message_manager.get_message_offer(session)

        if message_to_send is None:
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        session["state"] = SessionState.HANDOFF_WITH_OFFER
        await send_whatsapp_text(
            from_number,
            message_to_send,
        )
        await send_whatsapp_text(
            from_number,
            "👉 Decime qué mes te interesa y para cuántas personas, y lo vemos más a medida (vuelo, equipaje y forma de pago) 😊✈️",
        )

        sync_sheets_with_redis_task.delay()
        return session

    def _validate_travelers(self, session):
        num_travelers = session.get("num_travelers")
        num_underage_travelers = session.get("num_underage_travelers")
        return num_travelers == 2 and num_underage_travelers == 0
