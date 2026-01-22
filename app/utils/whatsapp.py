"""WhatsApp messaging utilities and shared state definitions."""

import requests
from app.config import wpp_settings

WPP_ADAPTER_URL = wpp_settings.WPP_ADAPTER_URL


async def send_whatsapp_text(
    to_whatsapp: str, body: str, media: str = None, file_name: str = None
):
    payload = {
        "to": to_whatsapp,
        "message": body,
        "authKey": wpp_settings.AUTH_SESSION_KEY,
    }
    if media:
        payload["mediaUrl"] = media
        payload["fileName"] = file_name
    try:
        requests.post(WPP_ADAPTER_URL, json=payload)
    except Exception as e:
        print("Error sending message via WPPConnect:", e)
        raise
