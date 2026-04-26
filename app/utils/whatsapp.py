import logging
import httpx

from app.config import wpp_settings

logger = logging.getLogger("whatsapp")

WPP_ADAPTER_URL = wpp_settings.WPP_ADAPTER_URL

# Singleton client
_wpp_client: httpx.AsyncClient | None = None


def init_http_client() -> None:
    """Initialize an http client once"""
    global _wpp_client
    if _wpp_client is None:
        _wpp_client = httpx.AsyncClient(timeout=10.0)


async def close_http_client() -> None:
    """Close the http client"""
    global _wpp_client
    if _wpp_client is not None:
        await _wpp_client.aclose()
        _wpp_client = None


async def send_whatsapp_text(
    to_whatsapp: str, body: str, media: str = None, file_name: str = None
):
    if _wpp_client is None:
        raise RuntimeError(
            "HTTP client not initialized. init_http_client() should have been called at startup."
        )

    payload = {
        "to": to_whatsapp,
        "message": body,
        "authKey": wpp_settings.AUTH_SESSION_KEY,
    }
    if media:
        payload["mediaUrl"] = media
        payload["fileName"] = file_name

    try:
        response = await _wpp_client.post(WPP_ADAPTER_URL, json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "WPP adapter rejected message to=%s status=%s body=%s",
            to_whatsapp,
            exc.response.status_code,
            exc.response.text[:200],
        )
        raise
    except httpx.HTTPError as exc:
        logger.exception("WPP adapter request failed to=%s: %s", to_whatsapp, exc)
        raise
