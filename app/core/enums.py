from enum import StrEnum


class SessionState(StrEnum):
    """Conversation states for the WhatsApp bot flow (Internal logic)."""

    GETTING_AD_DESTINATION = "getting_ad_destination"
    CLASSIFYING_DESTINATION = (
        "classifying_destination"  # LLM fallback when ad message is unknown
    )
    PRESENTING_OFFERS = (
        "presenting_offers"  # LLM shows available packages for the destination
    )
    EXTRACTING_INFORMATION = (
        "extracting_information"  # LLM extracts information from the user message
    )
    # Handoff states - conversation ends and agent takes over
    HANDOFF_WITH_OFFER = "handoff_to_agent_with_offer_sent"
    HANDOFF_NO_OFFER = "handoff_to_agent_without_sending_offer"
    HANDOFF_NO_DEPARTURE = "handoff_to_agent_without_detecting_departure"
    HANDOFF_NO_TRAVELERS = "handoff_to_agent_without_detecting_num_travelers"
    HANDOFF_TIMEOUT = "handoff_to_agent_timeout"
    HANDOFF_UNKNOWN_DESTINATION = "handoff_to_agent_unknown_destination"

    @classmethod
    def handoff_states(cls) -> set["SessionState"]:
        """Returns all states that indicate handoff to human agent."""
        return {
            cls.HANDOFF_WITH_OFFER,
            cls.HANDOFF_NO_OFFER,
            cls.HANDOFF_NO_DEPARTURE,
            cls.HANDOFF_NO_TRAVELERS,
            cls.HANDOFF_TIMEOUT,
            cls.HANDOFF_UNKNOWN_DESTINATION,
        }


class TotalStates(StrEnum):
    """Human-readable states (Spanish translations) for reporting/display."""

    getting_ad_destination = "Preguntando por destino"
    classifying_destination = "Clasificando destino con LLM"
    presenting_offers = "Presentando ofertas disponibles"
    extracting_information = "Extrayendo información del usuario"
    # Handoff states
    handoff_to_agent_with_offer_sent = "Pasado al vendedor con primera oferta enviada"
    handoff_to_agent_without_sending_offer = "Pasado al vendedor sin enviar oferta"
    handoff_to_agent_without_detecting_departure = (
        "Pasado al vendedor sin detectar origen"
    )
    handoff_to_agent_without_detecting_num_travelers = (
        "Pasado al vendedor sin detectar cantidad de viajeros"
    )
    handoff_to_agent_timeout = "Pasado al vendedor por falta de respuesta"
    handoff_to_agent_unknown_destination = "Pasado al vendedor por destino desconocido"
