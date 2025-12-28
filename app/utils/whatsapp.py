"""WhatsApp messaging utilities and shared state definitions."""

from enum import StrEnum
import requests
from app.config import wpp_settings


class SessionState(StrEnum):
    """Conversation states for the WhatsApp bot flow."""

    GETTING_AD_DESTINATION = "getting_ad_destination"
    ASKING_NUM_TRAVELERS = "asking_num_travelers"
    ASKING_DEPARTURE = "asking_departure"
    # Handoff states - conversation ends and agent takes over
    HANDOFF_WITH_OFFER = "handoff_to_agent_with_offer_sent"
    HANDOFF_NO_OFFER = "handoff_to_agent_without_sending_offer"
    HANDOFF_NO_DEPARTURE = "handoff_to_agent_without_detecting_departure"
    HANDOFF_NO_TRAVELERS = "handoff_to_agent_without_detecting_num_travelers"
    ASKING_DEPARTURE_DATE = "asking_departure_date"

    @classmethod
    def handoff_states(cls) -> set["SessionState"]:
        """Returns all states that indicate handoff to human agent."""
        return {
            cls.HANDOFF_WITH_OFFER,
            cls.HANDOFF_NO_OFFER,
            cls.HANDOFF_NO_DEPARTURE,
            cls.HANDOFF_NO_TRAVELERS,
        }


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
