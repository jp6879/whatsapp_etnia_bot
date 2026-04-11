from typing import Annotated
from fastapi import Depends
from app.database.sheets import get_sheets_service
from app.services.sheets_services import SheetsService
from app.services.chatbot_service import ChatbotService
from app.utils.message_manager import MessageManager

# Dependency for the sheets service (used when master_router is registered)
SheetsServiceDep = Annotated[SheetsService, Depends(get_sheets_service)]

# Singleton instances
_message_manager_instance = None


def get_message_manager() -> MessageManager:
    global _message_manager_instance
    if _message_manager_instance is None:
        _message_manager_instance = MessageManager()
    return _message_manager_instance


def get_chatbot_service(
    message_manager: MessageManager = Depends(get_message_manager),
) -> ChatbotService:
    return ChatbotService(message_manager)


ChatbotServiceDep = Annotated[ChatbotService, Depends(get_chatbot_service)]
