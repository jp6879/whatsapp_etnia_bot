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
        """Load session from Redis. Returns True if a session was loaded, False otherwise."""
        key = self.get_session_key()
        try:
            raw = await async_redis.get(key)
            if raw:
                self.session = json.loads(raw)
                self.state = self.session.get("state", "waiting")
                return True
            return False
        except Exception as e:
            print(f"Error loading session: {e}")
            self.session = None
            self.state = "waiting"
            try:
                await async_redis.delete(key)
            except Exception:
                pass
            return False

    async def save_session(self, session: dict):
        key = self.get_session_key()
        self.session = session
        self.state = session.get("state", self.state)
        try:
            await async_redis.set(key, json.dumps(session))
            # Trigger Celery task to sync with Google Sheets
            from app.tasks import sync_sheets_with_redis_task

            sync_sheets_with_redis_task.delay()
        except Exception as e:
            print(f"Error saving session: {e}")

    async def clear_session(self):
        try:
            await async_redis.delete(self.get_session_key())
        except Exception as e:
            print(f"Error clearing session: {e}")


async def get_session(request: Request) -> RedisSession:
    data = await request.json()
    from_number = data.get("From")
    if not from_number:
        raise HTTPException(status_code=400, detail="Missing From number in request")

    session = RedisSession(from_number)
    return session


RedisSessionDep = Annotated[RedisSession, Depends(get_session)]
