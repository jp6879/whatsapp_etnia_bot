"""WhatsApp messaging utilities and shared state definitions."""

import logging
import httpx
from app.config import wpp_settings

logger = logging.getLogger("whatsapp")

WPP_ADAPTER_URL = wpp_settings.WPP_ADAPTER_URL

# Shared async client — reuses connection pool across requests.
# Timeout: 10 s connect + 15 s read (wppconnect can be slow on first send).
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)
)


async def send_whatsapp_text(
    to_whatsapp: str, body: str, media: str = None, file_name: str = None
):
    """Send a WhatsApp message via the wppconnect adapter (fully async)."""
    payload = {
        "to": to_whatsapp,
        "message": body,
        "authKey": wpp_settings.AUTH_SESSION_KEY,
    }
    if media:
        payload["mediaUrl"] = media
        payload["fileName"] = file_name
    try:
        response = await _http_client.post(WPP_ADAPTER_URL, json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "WPPConnect returned error %s: %s", e.response.status_code, e.response.text
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error sending WhatsApp message: %s", e)
        raise
