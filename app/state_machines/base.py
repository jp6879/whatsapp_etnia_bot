from abc import ABC, abstractmethod
from app.utils.message_manager import MessageManager
from app.utils.whatsapp import send_whatsapp_text
from app.tasks import sync_sheets_with_redis_task
from app.core.enums import SessionState


class BaseStateMachine(ABC):
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager

    @abstractmethod
    async def process(self, session: dict, body: str, from_number: str) -> dict:
        """
        Process the message and update the session state.
        Returns the updated session.
        """
        pass

    async def _handle_asking_num_travelers(
        self, session: dict, body: str, from_number: str
    ) -> dict:
        """
        Common logic for handling ASKING_NUM_TRAVELERS state.
        Extracts number of travelers and transitions to ASKING_DEPARTURE (Standard flow).
        Subclasses can override this if they have different flow.
        """
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

        # Default transition: Go to ASKING_DEPARTURE
        session["state"] = SessionState.ASKING_DEPARTURE
        sync_sheets_with_redis_task.delay()

        await send_whatsapp_text(
            from_number, "Perfecto. ¿Desde dónde te gustaría salir?"
        )
        return session
