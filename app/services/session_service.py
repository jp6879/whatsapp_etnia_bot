import json
import logging
from typing import Annotated, Any

from fastapi import HTTPException, Request
from fastapi.params import Depends
from redis.asyncio import Redis

from app.database.redis import RedisClientDep

logger = logging.getLogger("session")

# Sessions expire 7 days after the last write to keep PII out of Redis indefinitely.
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


class RedisSession:
    SESSION_PREFIX = "wa_session:"

    def __init__(self, from_number: str, client: Redis):
        self.from_number = from_number
        self.state = "waiting"
        self.client = client
        self.session: dict | None = None

    def get_session_key(self) -> str:
        return self.SESSION_PREFIX + self.from_number

    async def load_session(self) -> bool:
        """Load session from Redis. Returns True if a session was loaded, False otherwise.

        Raises on Redis connectivity errors so the request fails loudly instead of
        silently re-greeting an existing user.
        """
        key = self.get_session_key()
        raw = await self.client.get(key)
        if raw is None:
            return False
        try:
            self.session = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("[SESSION] Corrupt JSON for key=%s — discarding", key)
            await self.client.delete(key)
            return False
        self.state = self.session.get("state", "waiting")
        return True

    async def save_session(self, session: dict):
        key = self.get_session_key()
        self.session = session
        self.state = session.get("state", self.state)
        await self.client.set(key, json.dumps(session), ex=SESSION_TTL_SECONDS)

    async def clear_session(self):
        await self.client.delete(self.get_session_key())


async def get_webhook_payload(request: Request) -> dict[str, Any]:
    """Parse the webhook JSON body once per request and cache it on request.state."""
    cached = getattr(request.state, "webhook_payload", None)
    if cached is not None:
        return cached
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    request.state.webhook_payload = payload
    return payload


WebhookPayloadDep = Annotated[dict[str, Any], Depends(get_webhook_payload)]


async def get_session(
    payload: WebhookPayloadDep, redis_client: RedisClientDep
) -> RedisSession:
    from_number = payload.get("From")
    if not from_number:
        raise HTTPException(status_code=400, detail="Missing From number in request")

    return RedisSession(from_number, redis_client)


RedisSessionDep = Annotated[RedisSession, Depends(get_session)]
