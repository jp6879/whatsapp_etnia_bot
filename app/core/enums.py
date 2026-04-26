from enum import StrEnum


class SessionState(StrEnum):
    """Conversation states for the bot.

    Values are stable wire identifiers — used as JSON state keys today
    and as Chatwoot label slugs in Phase C+. The `label` property is
    the Spanish human-readable text used in reports / Chatwoot private
    notes.
    """

    GETTING_AD_DESTINATION = "getting_ad_destination"
    CLASSIFYING_DESTINATION = "classifying_destination"
    PRESENTING_OFFERS = "presenting_offers"
    EXTRACTING_INFORMATION = "extracting_information"

    # Handoff states — terminal; conversation goes to a human agent.
    HANDOFF_WITH_OFFER = "handoff_to_agent_with_offer_sent"
    HANDOFF_NO_OFFER = "handoff_to_agent_without_sending_offer"
    HANDOFF_NO_DEPARTURE = "handoff_to_agent_without_detecting_departure"
    HANDOFF_NO_TRAVELERS = "handoff_to_agent_without_detecting_num_travelers"
    HANDOFF_TIMEOUT = "handoff_to_agent_timeout"
    HANDOFF_UNKNOWN_DESTINATION = "handoff_to_agent_unknown_destination"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def handoff_states(cls) -> set["SessionState"]:
        return {
            cls.HANDOFF_WITH_OFFER,
            cls.HANDOFF_NO_OFFER,
            cls.HANDOFF_NO_DEPARTURE,
            cls.HANDOFF_NO_TRAVELERS,
            cls.HANDOFF_TIMEOUT,
            cls.HANDOFF_UNKNOWN_DESTINATION,
        }


_LABELS: dict[SessionState, str] = {
    SessionState.GETTING_AD_DESTINATION: "Preguntando por destino",
    SessionState.CLASSIFYING_DESTINATION: "Clasificando destino con LLM",
    SessionState.PRESENTING_OFFERS: "Presentando ofertas disponibles",
    SessionState.EXTRACTING_INFORMATION: "Extrayendo información del usuario",
    SessionState.HANDOFF_WITH_OFFER: "Pasado al vendedor con primera oferta enviada",
    SessionState.HANDOFF_NO_OFFER: "Pasado al vendedor sin enviar oferta",
    SessionState.HANDOFF_NO_DEPARTURE: "Pasado al vendedor sin detectar origen",
    SessionState.HANDOFF_NO_TRAVELERS: "Pasado al vendedor sin detectar cantidad de viajeros",
    SessionState.HANDOFF_TIMEOUT: "Pasado al vendedor por falta de respuesta",
    SessionState.HANDOFF_UNKNOWN_DESTINATION: "Pasado al vendedor por destino desconocido",
}
