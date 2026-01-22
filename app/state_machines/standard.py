from app.state_machines.base import BaseStateMachine
from app.utils.whatsapp import send_whatsapp_text
from app.tasks import sync_sheets_with_redis_task
from app.core.enums import SessionState


class StandardSM(BaseStateMachine):
    async def process(self, session: dict, body: str, from_number: str) -> dict:
        state = session.get("state")

        if state == SessionState.ASKING_NUM_TRAVELERS:
            return await self._handle_asking_num_travelers(session, body, from_number)

        if state == SessionState.ASKING_DEPARTURE:
            return await self._handle_asking_departure(session, body, from_number)

        # Default fallback if state not handled here (shouldn't happen if router works right)
        return session

    async def _handle_asking_departure(self, session, body, from_number):
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

        # offer_link, file_name = await self.message_manager.get_offer_link(session)
        # Strict validation: 2 adults, 0 minors
        if not self._validate_travelers(session):
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        message_to_send = await self.message_manager.get_message_offer(session)

        if not message_to_send:
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        await send_whatsapp_text(
            from_number,
            message_to_send,
        )

        await send_whatsapp_text(
            from_number,
            "✨ Decime si esta opción es la que buscás o si preferís que la acomodemos (fecha, hotel, compañía), o si querés que te enviemos otras opciones.",
        )

        session["state"] = SessionState.HANDOFF_WITH_OFFER
        sync_sheets_with_redis_task.delay()

        return session

    def _validate_travelers(self, session):
        num_travelers = session.get("num_travelers")
        num_underage_travelers = session.get("num_underage_travelers")
        return num_travelers == 2 and num_underage_travelers == 0
