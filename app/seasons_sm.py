from app.utils.message_manager import MessageManager
from app.utils.whatsapp import send_whatsapp_text, SessionState


class SeasonalSM:
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager
        self.offer_link = None
        self.file_name = None

    async def seasonal_state_machine_workflow(
        self, actual_session, from_number, body
    ) -> dict:
        state = actual_session.get("state")
        num_travelers = actual_session.get("num_travelers")
        num_underage_travelers = actual_session.get("num_underage_travelers")

        if num_travelers != 2 or num_underage_travelers != 0:
            actual_session["state"] = SessionState.HANDOFF_NO_OFFER
            await send_whatsapp_text(
                from_number,
                "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return actual_session

        if state == SessionState.ASKING_DEPARTURE:
            actual_session["state"] = SessionState.ASKING_DEPARTURE_DATE
            await send_whatsapp_text(
                from_number, "Contanos en que mes te gustaría viajar"
            )
            return actual_session

        if state == SessionState.ASKING_DEPARTURE_DATE:
            month = self.message_manager.get_month_from_message(body)

            if not month:
                actual_session["state"] = SessionState.HANDOFF_NO_OFFER
                await send_whatsapp_text(
                    from_number,
                    "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
                )
                return actual_session

            actual_session["departure_month"] = month
            actual_session["state"] = SessionState.HANDOFF_WITH_OFFER
            self.offer_link, self.file_name = (
                await self.message_manager.get_seassonal_offer_link(actual_session)
            )

            if self.offer_link is None:
                actual_session["state"] = SessionState.HANDOFF_NO_OFFER
                await send_whatsapp_text(
                    from_number,
                    "En breve te contactamos para encontrar el paquete ideal para vos. ¡Gracias! 😊",
                )
                return actual_session

            return actual_session
