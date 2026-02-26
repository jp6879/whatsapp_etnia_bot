import json
from dataclasses import dataclass
from openai import AsyncOpenAI
from app.config import openai_settings


@dataclass
class ExtractionResult:
    num_travelers: int | None
    num_underage_travelers: int | None
    departure_location: str | None
    date: str | None
    response_message: str  # Friendly Spanish message to send back to the user


class LLMExtractionService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=openai_settings.OPENAI_API_KEY)

    def build_messages_history(self, session: dict) -> list[dict]:
        """Return history as-is — each entry already has {role, content}."""
        return session.get("messages_history", [])

    async def extract(self, message: str, session: dict) -> ExtractionResult:
        """
        Conversational extraction agent.

        Destination is ALREADY known in session (set from the ad message).
        This agent extracts:
          - num_travelers (adults) — required
          - num_underage_travelers (minors, defaults to 0) — required
          - departure_location (Argentine city) — required
          - date (travel month or date) — conditionally required per destination
        When the user's city has no offer, the LLM picks the closest available
        departure and sets suggested_departure_iata.
        """
        destination = session.get("destination", "el destino seleccionado")
        required_fields = session.get("required_fields", [])

        # Build a summary of what's already known so the LLM doesn't re-ask
        known_lines = []
        if session.get("num_travelers") is not None:
            known_lines.append(f"- Adultos: {session['num_travelers']}")
        if session.get("num_underage_travelers") is not None:
            known_lines.append(f"- Menores: {session['num_underage_travelers']}")
        if session.get("departure_location"):
            known_lines.append(f"- Ciudad de salida: {session['departure_location']}")
        if session.get("date"):
            known_lines.append(f"- Fecha: {session['date']}")

        known_str = "\n".join(known_lines) if known_lines else "Ninguna todavía."

        # Optional extra fields block
        extra_fields_to_ask = (
            ""
            if session.get("required_fields") is None
            else "\n".join(session.get("required_fields"))
        )

        history = self.build_messages_history(session)

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Sos el asistente virtual de Etnia Viajes. "
                        f"El cliente quiere viajar a {destination}.\n\n"
                        "INFORMACIÓN YA RECOLECTADA:\n"
                        f"{known_str}\n\n"
                        "Tu tarea: extraer del mensaje del cliente la información que falte"
                        "y responder en español de forma amigable y natural.\n\n"
                        "CAMPOS A COMPLETAR (en orden de prioridad):\n"
                        "1. num_travelers — cantidad de adultos (requerido)\n"
                        "2. num_underage_travelers — menores de edad; si no se menciona, asumí 0 (requerido)\n"
                        "3. departure_location — ciudad argentina desde donde salen (requerido)\n"
                        f"Puede haber campos adicionales que se deben completar: {extra_fields_to_ask}\n"
                        "Devolvé SOLO JSON con este formato exacto:\n"
                        "{\n"
                        '  "num_travelers": <entero o null>,\n'
                        '  "num_underage_travelers": <entero o null>,\n'
                        '  "departure_location": "<ciudad mencionada por el cliente>" o null,\n'
                        '  "date": "<mes>" o null,\n'
                        '  "response_message": "<respuesta amigable; si el usuario saluda respondé el saludo; '
                        'luego preguntá sólo el PRÓXIMO campo que falta, no todos a la vez>"\n'
                        "}\n\n"
                        "Notas importantes:\n"
                        "- No repitas información ya recolectada en tu pregunta.\n"
                        "- Sólo pedí un campo a la vez.\n"
                        "- response_message SIEMPRE debe estar presente y en español.\n"
                        "- No incluyas JSON ni formato técnico en response_message."
                    ),
                },
                *history,
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            max_tokens=350,
        )

        data = json.loads(response.choices[0].message.content)

        return ExtractionResult(
            num_travelers=data.get("num_travelers"),
            num_underage_travelers=data.get("num_underage_travelers"),
            departure_location=data.get("departure_location"),
            date=data.get("date"),
            response_message=data.get("response_message", ""),
        )
