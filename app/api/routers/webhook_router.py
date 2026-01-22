from fastapi import APIRouter, Request, HTTPException
from app.services.session_service import RedisSessionDep
from app.api.dependencies import ChatbotServiceDep
from app.api.tag import APITag

router = APIRouter(prefix="/webhook", tags=[APITag.WEBHOOK])


@router.post("/")
async def whatsapp_webhook(
    request: Request,
    redis_session: RedisSessionDep,
    chatbot_service: ChatbotServiceDep,
):
    data = await request.json()
    from_number = data.get("From")
    body = data.get("Body", "").strip()
    name = data.get("Name", "").strip()

    if not from_number or not body:
        raise HTTPException(
            status_code=400, detail="Missing From number or Body in webhook payload"
        )

    return await chatbot_service.process_message(redis_session, from_number, body, name)
