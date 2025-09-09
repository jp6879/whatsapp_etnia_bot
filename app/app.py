import json
from datetime import datetime
import httpx
from fastapi import FastAPI, status, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from .config import meta_settings

app = FastAPI()


@app.get("/webhook", response_class=PlainTextResponse, name="Verify Webhook")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
):
    if (
        hub_mode == "subscribe"
        and hub_verify_token == meta_settings.WHATSAPP_VERIFY_TOKEN
    ):
        print("WEBHOOK_VERIFIED")
        return hub_challenge

    print("WEBHOOK_VERIFICATION_FAILED")
    return status.HTTP_403_FORBIDDEN


@app.post("/webhook", name="receive_webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n\nWebhook received {timestamp}\n")
    print(json.dumps(body, indent=2))
    return {"status": "ok"}


@app.post("/send_template")
async def send_template(to: str):
    url = f"https://graph.facebook.com/v22.0/{meta_settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {meta_settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "primeros_pasos",
            "language": {"code": "es_AR"},
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        return {"status": "Message sent successfully"}
    else:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Failed to send message: {response.text}",
        )
