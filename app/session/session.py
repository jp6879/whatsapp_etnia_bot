from typing import Annotated
from fastapi import HTTPException, Request
from fastapi.params import Depends
import redis.asyncio as redis
import json
from app.config import redis_settings

async_redis = redis.from_url(redis_settings.REDIS_DB_URL, decode_responses=True)


class RedisSession:
    SESSION_PREFIX = "wa_session:"

    def __init__(self, from_number: str):
        self.from_number = from_number
        self.state = "waiting"
        self.session = None

    def get_session_key(self) -> str:
        return self.SESSION_PREFIX + self.from_number

    async def load_session(self) -> bool:
        """Load session from Redis. Returns True if a session was loaded, False otherwise.

        When loaded, sets `self.session` to the dict and `self.state` to session['state'] if present.
        """
        key = self.get_session_key()
        raw = async_redis.get(key)
        if raw:
            try:
                self.session = json.loads(raw)
                self.state = self.session.get("state", "waiting")
            except Exception:
                self.session = None
                self.state = "waiting"
                await async_redis.delete(key)
                return False
            return True
        return False

    async def save_session(self, session: dict):
        key = self.get_session_key()
        self.session = session
        self.state = session.get("state", self.state)
        await async_redis.set(key, json.dumps(session))

    async def clear_session(self):
        await async_redis.delete(self.SESSION_PREFIX + self.from_number)


async def get_session(request: Request) -> RedisSession:
    data = await request.json()
    from_number = data.get("From")
    if not from_number:
        raise HTTPException(status_code=400, detail="Missing From number in request")

    session = RedisSession(from_number)
    return session


RedisSessionDep = Annotated[RedisSession, Depends(get_session)]
