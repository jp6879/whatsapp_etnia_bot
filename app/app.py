import json
from datetime import datetime
import httpx
from fastapi import FastAPI, requests, status, Request, Query, HTTPException
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


@app.post("/webhook")
async def response_webhook(request: Request):
    data = await request.json()
    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = message["from"]
        text = message["text"]["body"]

        # Simple rule-based bot
        if "hello" in text.lower():
            reply = "Hi 👋! How can I help you today?"
        else:
            reply = "Sorry, I didn’t understand. Please try again."

        url = f"https://graph.facebook.com/v21.0/{meta_settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {meta_settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": sender,
            "type": "text",
            "text": {"body": reply},
        }
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print("Webhook error:", e)
    return "OK"
