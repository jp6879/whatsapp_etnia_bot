from app.state_machines.standard import StandardSM
from app.utils.whatsapp import send_whatsapp_text
from app.tasks import sync_sheets_with_redis_task
from app.core.enums import SessionState

# GroupalSM can inherit from StandardSM if logic is similar, or BaseStateMachine if distinct.
# For now, it seems similar to Standard (ask location -> offer), maybe just different folder in Drive?
# Using StandardSM as base for now to reuse logic.


class GroupalSM(StandardSM):
    async def process(self, session: dict, body: str, from_number: str) -> dict:
        state = session.get("state")

        if state == SessionState.ASKING_NUM_TRAVELERS:
            return await self._handle_asking_num_travelers(session, body, from_number)

        return session

    async def _handle_asking_num_travelers(
        self, session: dict, body: str, from_number: str
    ) -> dict:
        # 1. Extract travelers
        session["num_travelers_message"] = body
        num_travelers_dict = await self.message_manager.extract_number_of_persons(body)

        if not num_travelers_dict or num_travelers_dict["total"] < 1:
            session["state"] = SessionState.HANDOFF_NO_TRAVELERS
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        session["num_travelers"] = num_travelers_dict["adults"]
        session["num_underage_travelers"] = num_travelers_dict["minors"]

        # 2. Skip Asking Departure -> Go to Offer/Handoff
        # (Assuming we have a generic offer or just handoff for now as per diagram "Handoff with/without offer")

        offer_link, file_name = await self.message_manager.get_offer_link(session)

        if not offer_link:
            session["state"] = SessionState.HANDOFF_NO_OFFER
            sync_sheets_with_redis_task.delay()
            await send_whatsapp_text(
                from_number,
                "Un agente te contactara para encontrar el paquete ideal para vos. ¡Gracias! 😊",
            )
            return session

        await send_whatsapp_text(
            from_number,
            "Te envío una propuesta ideal para vos 🛩️",
            media=offer_link,
            file_name=file_name,
        )

        await send_whatsapp_text(
            from_number,
            "✨ Decime si esta opción es la que buscás o si preferís que la acomodemos (fecha, hotel, compañía), o si querés que te enviemos otras opciones.",
        )

        session["state"] = SessionState.HANDOFF_WITH_OFFER
        sync_sheets_with_redis_task.delay()

        return session
