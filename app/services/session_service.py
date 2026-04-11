from app.database.redis import RedisClientDep
from typing import Annotated
from fastapi import HTTPException, Request
from fastapi.params import Depends
import json
from redis.asyncio import Redis


class RedisSession:
    SESSION_PREFIX = "wa_session:"

    def __init__(self, from_number: str, client: Redis):
        self.from_number = from_number
        self.state = "waiting"
        self.client = client
        self.session = None

    def get_session_key(self) -> str:
        return self.SESSION_PREFIX + self.from_number

    async def load_session(self) -> bool:
        """Load session from Redis. Returns True if a session was loaded, False otherwise."""
        key = self.get_session_key()
        try:
            raw = await self.client.get(key)
            if raw:
                self.session = json.loads(raw)
                self.state = self.session.get("state", "waiting")
                return True
            return False
        except json.JSONDecodeError:
            await self.client.delete(key)
            return False
        except Exception as e:
            return False

    async def save_session(self, session: dict):
        key = self.get_session_key()
        self.session = session
        self.state = session.get("state", self.state)
        try:
            await self.client.set(key, json.dumps(session))
        except Exception as e:
            print(f"Error saving session: {e}")

    async def clear_session(self):
        try:
            await self.client.delete(self.get_session_key())
        except Exception as e:
            print(f"Error clearing session: {e}")


async def get_session(request: Request, redis_client: RedisClientDep) -> RedisSession:
    data = await request.json()
    from_number = data.get("From")
    if not from_number:
        raise HTTPException(status_code=400, detail="Missing From number in request")

    session = RedisSession(from_number, redis_client)
    return session


RedisSessionDep = Annotated[RedisSession, Depends(get_session)]
