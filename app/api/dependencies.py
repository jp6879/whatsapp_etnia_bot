from typing import Annotated
from fastapi import Depends
from app.database.redis import get_redis_service
from app.database.sheets import get_sheets_service
from app.services.sheets_services import SheetsService
from app.services.redis_services import RedisService

# Dependency for the redis client
RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]

# Dependency for the sheets service
SheetsServiceDep = Annotated[SheetsService, Depends(get_sheets_service)]
