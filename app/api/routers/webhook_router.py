from fastapi import APIRouter, HTTPException

from app.api.dependencies import ChatbotServiceDep
from app.api.tag import APITag
from app.services.session_service import RedisSessionDep, WebhookPayloadDep

router = APIRouter(prefix="/webhook", tags=[APITag.WEBHOOK])


@router.post("/")
async def whatsapp_webhook(
    payload: WebhookPayloadDep,
    redis_session: RedisSessionDep,
    chatbot_service: ChatbotServiceDep,
):
    from_number = payload.get("From")
    body = (payload.get("Body") or "").strip()
    name = (payload.get("Name") or "").strip()

    if not from_number or not body:
        raise HTTPException(
            status_code=400, detail="Missing From number or Body in webhook payload"
        )

    return await chatbot_service.process_message(redis_session, from_number, body, name)
