"""
Test router - Simulates WhatsApp conversations without needing WhatsApp.

POST /test/chat with:
    {
        "from_number": "+54911000000",
        "message": "Quiero ir a Turquía",
        "name": "Juan"
    }

The bot replies are captured instead of being sent to WhatsApp and returned as JSON.
Uses a real Redis session and real LLM calls.
"""

from unittest.mock import patch
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import (
    get_chatbot_service,
    get_message_manager,
    get_sm_factory,
)
from app.services.session_service import RedisSession

router = APIRouter(prefix="/test", tags=["🧪 Test (local only)"])


class ChatRequest(BaseModel):
    from_number: str = "+54911000000"
    message: str
    name: str = "Test User"


class ChatResponse(BaseModel):
    status: str
    bot_messages: list[str]
    session_state: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def test_chat(body: ChatRequest):
    """
    Simulate a WhatsApp message to the bot and get its reply — no WhatsApp needed.

    Use the same `from_number` across multiple requests to simulate a multi-turn conversation.
    Use a unique number (or call DELETE /test/chat/session) to start fresh.
    """
    # Build dependencies manually (bypasses Request-based session extraction)
    message_manager = get_message_manager()
    factory = get_sm_factory(message_manager)
    chatbot_service = get_chatbot_service(message_manager, factory)
    redis_session = RedisSession(from_number=body.from_number)

    captured_messages: list[str] = []

    async def fake_send(to: str, message: str, media=None, file_name=None):
        captured_messages.append(message)

    with patch(
        "app.services.chatbot_service.send_whatsapp_text",
        side_effect=fake_send,
    ):
        result = await chatbot_service.process_message(
            redis_session,
            body.from_number,
            body.message,
            body.name,
        )

    # Read back session state for debugging
    session_state = None
    try:
        if await redis_session.load_session():
            session_state = redis_session.session.get("state")
    except Exception:
        pass

    return ChatResponse(
        status=result.get("status", "unknown"),
        bot_messages=captured_messages,
        session_state=session_state,
    )


@router.delete("/chat/session")
async def reset_session(from_number: str = "+54911000000"):
    """
    Delete the Redis session for a given phone number to start a fresh conversation.
    """
    try:
        redis_session = RedisSession(from_number=from_number)
        await redis_session.clear_session()
        return {"status": "ok", "message": f"Session for {from_number} deleted"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
