from typing import Annotated
from fastapi import Depends
from app.services.redis_services import RedisService
from redis.asyncio import Redis
from app.config import redis_settings
from app.core.exceptions import RedisConnectionError


async def get_redis_client():
    """Getting the redis client where the data is stored"""
    _redis_client = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        username=redis_settings.REDIS_USER,
        password=redis_settings.REDIS_PASSWORD,
        decode_responses=True,
    )

    if not await _redis_client.ping():
        await _redis_client.aclose()
        raise RedisConnectionError("Redis connection failed")

    try:
        yield _redis_client
    finally:
        await _redis_client.aclose()


RedisClientDep = Annotated[Redis, Depends(get_redis_client)]


async def get_redis_service(redis_client: RedisClientDep) -> RedisService:
    """Getting the redis service where the data is stored"""
    return RedisService(redis_client)
