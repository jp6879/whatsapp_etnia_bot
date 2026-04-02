"""
Test router - Simulates WhatsApp conversations without needing WhatsApp.

POST /test/chat
    { "from_number": "+54911000000", "message": "...", "name": "Juan", "debug": true }

- bot_messages: list of messages the bot would have sent
- session_state: current state after the turn
- debug_trace: step-by-step log of what happened (only when debug=true)
"""

import logging
from unittest.mock import patch
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import (
    get_chatbot_service,
    get_message_manager,
)
from app.services.session_service import RedisSession

router = APIRouter(prefix="/test", tags=["🧪 Test (local only)"])

# ── Debug log capture ───────────────────────────────────────────────────────


class _ListHandler(logging.Handler):
    """Logging handler that collects records into a list."""

    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(self.format(record))


# ── Request / Response models ───────────────────────────────────────────────


class ChatRequest(BaseModel):
    from_number: str = "+54911000000"
    message: str
    name: str = "Test User"
    debug: bool = False  # Set to true to get the full debug trace


class ChatResponse(BaseModel):
    status: str
    bot_messages: list[str]
    session_state: str | None = None
    session_snapshot: dict | None = None  # Full session dict (always included)
    debug_trace: list[str] | None = None  # Step-by-step log (only when debug=True)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def test_chat(body: ChatRequest):
    """
    Simulate a WhatsApp message to the bot and get its reply — no WhatsApp needed.

    - Use the same `from_number` across multiple requests for a multi-turn conversation.
    - Use a unique number (or DELETE /test/chat/session) to start fresh.
    - Set `debug: true` to see the full step-by-step trace.
    """
    # ── Build dependencies manually ─────────────────────────────────────────
    message_manager = get_message_manager()
    chatbot_service = get_chatbot_service(message_manager)
    redis_session = RedisSession(from_number=body.from_number)

    # ── Capture bot messages ─────────────────────────────────────────────────
    captured_messages: list[str] = []

    async def fake_send(to: str, message: str, media=None, file_name=None):
        captured_messages.append(message)

    # ── Optionally capture debug logs ────────────────────────────────────────
    list_handler = None
    if body.debug:
        list_handler = _ListHandler()
        list_handler.setFormatter(
            logging.Formatter("%(levelname)s [%(name)s] %(message)s")
        )
        for logger_name in ("chatbot", "extractor"):
            lg = logging.getLogger(logger_name)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(list_handler)

    # ── Run the bot ──────────────────────────────────────────────────────────
    with patch(
        "app.services.chatbot_service.send_whatsapp_text", side_effect=fake_send
    ):
        result = await chatbot_service.process_message(
            redis_session,
            body.from_number,
            body.message,
            body.name,
        )

    # ── Detach log handler ───────────────────────────────────────────────────
    if list_handler:
        for logger_name in ("chatbot", "extractor"):
            logging.getLogger(logger_name).removeHandler(list_handler)

    # ── Read back session ────────────────────────────────────────────────────
    session_state = None
    session_snapshot = None
    try:
        if await redis_session.load_session():
            session_state = redis_session.session.get("state")
            # Return session without full messages_history to keep it readable
            snap = dict(redis_session.session)
            snap.pop("messages_history", None)
            session_snapshot = snap
    except Exception:
        pass

    return ChatResponse(
        status=result.get("status", "unknown"),
        bot_messages=captured_messages,
        session_state=session_state,
        session_snapshot=session_snapshot,
        debug_trace=list_handler.records if list_handler else None,
    )


@router.get("/chat/session")
async def get_session(from_number: str = "+54911000000"):
    """Inspect the current Redis session for a given phone number."""
    try:
        redis_session = RedisSession(from_number=from_number)
        if await redis_session.load_session():
            snap = dict(redis_session.session)
            history = snap.pop("messages_history", [])
            return {
                "status": "ok",
                "state": redis_session.state,
                "session": snap,
                "history_length": len(history),
                "history": history,
            }
        return {"status": "ok", "state": "no session found"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.delete("/chat/session")
async def reset_session(from_number: str = "+54911000000"):
    """Delete the Redis session for a given phone number to start a fresh conversation."""
    try:
        redis_session = RedisSession(from_number=from_number)
        await redis_session.clear_session()
        return {"status": "ok", "message": f"Session for {from_number} deleted"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
