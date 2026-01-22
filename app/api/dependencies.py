from typing import Annotated
from fastapi import Depends
from app.database.redis import get_redis_service
from app.database.sheets import get_sheets_service
from app.services.sheets_services import SheetsService
from app.services.chatbot_service import ChatbotService
from app.services.redis_services import RedisService
from app.utils.message_manager import MessageManager
from app.state_machines.standard import StandardSM
from app.state_machines.seasonal import SeasonalSM
from app.state_machines.groupal import GroupalSM
from app.state_machines.factory import StateMachineFactory

# Dependency for the redis client
RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]

# Dependency for the sheets service
SheetsServiceDep = Annotated[SheetsService, Depends(get_sheets_service)]


# Singleton instances
_message_manager_instance = None
_factory_instance = None


def get_message_manager() -> MessageManager:
    global _message_manager_instance
    if _message_manager_instance is None:
        _message_manager_instance = MessageManager()
    return _message_manager_instance


def get_sm_factory(
    message_manager: MessageManager = Depends(get_message_manager),
) -> StateMachineFactory:
    global _factory_instance
    if _factory_instance is None:
        standard = StandardSM(message_manager)
        seasonal = SeasonalSM(message_manager)
        groupal = GroupalSM(message_manager)
        _factory_instance = StateMachineFactory(standard, seasonal, groupal)
    return _factory_instance


def get_chatbot_service(
    message_manager: MessageManager = Depends(get_message_manager),
    factory: StateMachineFactory = Depends(get_sm_factory),
) -> ChatbotService:
    return ChatbotService(message_manager, factory)


ChatbotServiceDep = Annotated[ChatbotService, Depends(get_chatbot_service)]
