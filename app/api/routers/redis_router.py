from fastapi import APIRouter
from ..dependencies import RedisServiceDep
from ..tag import APITag

router = APIRouter(prefix="/redis", tags=[APITag.REDIS])


@router.get("/data")
def get_data_from_redis(service: RedisServiceDep):
    """Getting all the data from the redis"""
    return service.get_all_data()
