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
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@app.post("/webhook")
async def response_webhook(request: Request):
    data = await request.json()
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        messages = changes.get("value", {}).get("messages", [])
        for message in messages:
            sender = message.get("from")
            text = message.get("text", {}).get("body")

            print(f"Received message from {sender}: {text}")

            url = f"https://graph.facebook.com/v21.0/{meta_settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {meta_settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": f"{sender}",
                "type": "template",
                "template": {
                    "name": "hello_world",
                    "language": {"code": "en_US"},
                },
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, headers=headers, json=payload, timeout=10.0
                )
                resp.raise_for_status()
    except KeyError as e:
        print("Webhook parsing error:", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload"
        )
    except httpx.HTTPStatusError as e:
        print("Sending message failed:", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send message"
        )
    except Exception as e:
        print("Webhook error:", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    return "OK"
