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
    is_complete: bool = False  # True when all required fields have been collected
    # Populated only by extract_with_offers()
    offer_accepted: bool = False
    accepted_offer_key: str | None = None  # e.g. "turquia_2_0"


class LLMExtractionService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=openai_settings.OPENAI_API_KEY)

    def build_messages_history(self, session: dict) -> list[dict]:
        """Return history as-is — each entry already has {role, content}."""
        return session.get("messages_history", [])

    def _build_known_str(self, session: dict) -> str:
        known_lines = []
        if session.get("num_travelers") is not None:
            known_lines.append(f"- Adultos: {session['num_travelers']}")
        if session.get("num_underage_travelers") is not None:
            known_lines.append(f"- Menores: {session['num_underage_travelers']}")
        if session.get("departure_location"):
            known_lines.append(f"- Ciudad de salida: {session['departure_location']}")
        if session.get("date"):
            known_lines.append(f"- Fecha: {session['date']}")
        return "\n".join(known_lines) if known_lines else "Ninguna todavía."

    def _compute_completeness(self, data: dict, session: dict) -> bool:
        merged_travelers = (
            data.get("num_travelers")
            if data.get("num_travelers") is not None
            else session.get("num_travelers")
        )
        merged_underage = (
            data.get("num_underage_travelers")
            if data.get("num_underage_travelers") is not None
            else session.get("num_underage_travelers")
        )
        merged_departure = (
            data.get("departure_location")
            if data.get("departure_location")
            else session.get("departure_location")
        )
        merged_date = data.get("date") if data.get("date") else session.get("date")

        required_fields = session.get("required_fields", [])
        date_required = (
            "date" in required_fields or "fecha" in " ".join(required_fields).lower()
        )
        return (
            merged_travelers is not None
            and merged_underage is not None
            and merged_departure is not None
            and (not date_required or merged_date is not None)
        )

    async def extract(self, message: str, session: dict) -> ExtractionResult:
        """
        Stage 3 extraction agent — custom quote flow only.

        Called only after the user has rejected the pre-built offers.
        Extracts: num_travelers, num_underage_travelers, departure_location, date.
        """
        destination = session.get("destination", "el destino seleccionado")
        known_str = self._build_known_str(session)
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
                        "Tu tarea: extraer del mensaje del cliente la información que falte "
                        "y responder en español de forma amigable y natural.\n\n"
                        "CAMPOS A COMPLETAR (en orden de prioridad):\n"
                        "1. num_travelers — cantidad de adultos (requerido)\n"
                        "2. num_underage_travelers — menores de edad; si no se menciona, asumí 0 (requerido)\n"
                        "3. departure_location — ciudad argentina desde donde salen (requerido)\n"
                        "4. date — fecha del viaje, puede ser especifica o un mes únicamente (requerido)\n"
                        "Devolvé SOLO JSON con este formato exacto:\n"
                        "{\n"
                        '  "num_travelers": <entero o null>,\n'
                        '  "num_underage_travelers": <entero o null>,\n'
                        '  "departure_location": "<ciudad mencionada por el cliente>" o null,\n'
                        '  "date": "<mes>" o null,\n'
                        '  "response_message": "<respuesta amigable; preguntá sólo el PRÓXIMO campo que falta>"\n'
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
        is_complete = self._compute_completeness(data, session)

        return ExtractionResult(
            num_travelers=data.get("num_travelers"),
            num_underage_travelers=data.get("num_underage_travelers"),
            departure_location=data.get("departure_location"),
            date=data.get("date"),
            response_message=data.get("response_message", ""),
            is_complete=is_complete,
        )

    async def extract_with_offers(
        self,
        message: str,
        session: dict,
        valid_offer_keys: list[str],
        offers_summary: str | None = None,
    ) -> ExtractionResult:
        """
        Stage 2 combined agent — offer acceptance detection + info extraction.

        Called after the bot has sent the pre-built offer messages deterministically.
        The LLM reads the full conversation history (which already contains the offer texts)
        plus an optional structured offers_summary, and decides in a single call:
          A) User accepted one of the offers → offer_accepted=True, accepted_offer_key set
          B) User wants a custom quote → extracts whatever info they already gave

        Args:
            message: The user's latest message.
            session: Current session dict (includes messages_history with offer texts).
            valid_offer_keys: List of keys from offers_db for this destination.
            offers_summary: Optional summary_for_bot text, injected explicitly into the prompt.
        """
        destination = session.get("destination", "el destino seleccionado")
        known_str = self._build_known_str(session)
        history = self.build_messages_history(session)
        keys_str = ", ".join(valid_offer_keys) if valid_offer_keys else "ninguna"

        # Inject the structured summary if provided (more reliable than history-only)
        summary_block = (
            f"RESUMEN DE OPCIONES DISPONIBLES:\n{offers_summary}\n\n"
            if offers_summary
            else ""
        )

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Sos el asistente virtual de Etnia Viajes. "
                        f"El cliente está interesado en viajar a {destination}.\n\n"
                        "CONTEXTO: El bot ya mostró al cliente los paquetes disponibles "
                        "(los podés ver en el historial de conversación).\n\n"
                        f"{summary_block}"
                        "INFORMACIÓN YA RECOLECTADA DEL CLIENTE:\n"
                        f"{known_str}\n\n"
                        f"CLAVES VÁLIDAS DE OFERTA: {keys_str}\n"
                        "(formato: destino_adultos_menores — la salida está incluida en el texto de la oferta)\n\n"
                        "TU TAREA — decidir UNA de estas dos opciones:\n\n"
                        "OPCIÓN A — El cliente acepta un paquete:\n"
                        "  Señales: dice 'sí', 'me interesa', 'perfecto', 'ese', confirma la oferta\n"
                        "  → offer_accepted: true, accepted_offer_key: clave exacta de la lista\n\n"
                        "OPCIÓN B — El cliente quiere algo diferente o da información:\n"
                        "  Señales: menciona ciudad diferente, cantidad distinta, pide algo personalizado\n"
                        "  o simplemente da datos (ej: 'somos 3 adultos', 'salimos desde Córdoba')\n"
                        "  → offer_accepted: false, extraer lo que se pueda del mensaje\n\n"
                        "REGLAS:\n"
                        "- offer_accepted: true SOLO si el cliente confirma querer una oferta específica.\n"
                        "- Si hay duda, elegí OPCIÓN B y extraé la info.\n"
                        "- response_message vacío ('') si offer_accepted=true.\n"
                        "- Si offer_accepted=false, response_message debe pedir sólo el PRÓXIMO campo faltante.\n"
                        "- No repitas info ya recolectada. Sólo pedí un campo a la vez.\n"
                        "- No incluyas JSON en response_message.\n\n"
                        "Devolvé SOLO JSON con este formato:\n"
                        "{\n"
                        '  "offer_accepted": true/false,\n'
                        '  "accepted_offer_key": "<clave exacta>" | null,\n'
                        '  "num_travelers": <entero o null>,\n'
                        '  "num_underage_travelers": <entero o null>,\n'
                        '  "departure_location": "<ciudad>" | null,\n'
                        '  "date": "<mes o fecha>" | null,\n'
                        '  "response_message": "<mensaje para el cliente, o vacío>"\n'
                        "}"
                    ),
                },
                *history,
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            max_tokens=400,
        )

        data = json.loads(response.choices[0].message.content)

        offer_accepted = data.get("offer_accepted", False)
        accepted_offer_key = data.get("accepted_offer_key")

        # Hallucination guard — verify key actually exists in the valid list
        if (
            offer_accepted
            and accepted_offer_key
            and accepted_offer_key not in valid_offer_keys
        ):
            offer_accepted = False
            accepted_offer_key = None

        is_complete = (
            self._compute_completeness(data, session) if not offer_accepted else False
        )

        return ExtractionResult(
            num_travelers=data.get("num_travelers"),
            num_underage_travelers=data.get("num_underage_travelers"),
            departure_location=data.get("departure_location"),
            date=data.get("date"),
            response_message=data.get("response_message", ""),
            is_complete=is_complete,
            offer_accepted=offer_accepted,
            accepted_offer_key=accepted_offer_key,
        )
