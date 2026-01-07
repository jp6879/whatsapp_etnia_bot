from enum import StrEnum


class TotalStates(StrEnum):
    """Conversation states for the WhatsApp bot flow."""

    getting_ad_destination = "Preguntando por destino"
    asking_num_travelers = "Preguntando por cantidad de viajeros"
    asking_departure = "Preguntando por origen"
    asking_departure_date = "Preguntando por fecha de salida"
    # Handoff states - conversation ends and agent takes over

    handoff_to_agent_with_offer_sent = "Pasado al vendedor con primera oferta enviada"
    handoff_to_agent_without_sending_offer = "Pasado al vendedor sin enviar oferta"
    handoff_to_agent_without_detecting_departure = (
        "Pasado al vendedor sin detectar origen"
    )
    handoff_to_agent_without_detecting_num_travelers = (
        "Pasado al vendedor sin detectar cantidad de viajeros"
    )
    handoff_to_agent_timeout = "Pasado al vendedor por falta de respuesta"

    @classmethod
    def handoff_states(cls) -> set["SessionState"]:
        """Returns all states that indicate handoff to human agent."""
        return {
            cls.handoff_to_agent_with_offer_sent,
            cls.handoff_to_agent_without_sending_offer,
            cls.handoff_to_agent_without_detecting_departure,
            cls.handoff_to_agent_without_detecting_num_travelers,
            cls.handoff_to_agent_timeout,
        }
