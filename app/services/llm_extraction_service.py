from pydantic import Field
import logging
from openai import AsyncOpenAI
from app.config import get_openai_settings
from app.services.agents.system_prompts import (
    COMBINED_EXTRACTION_SYSTEM_INTRO,
    COMBINED_EXTRACTION_SYSTEM_RULES,
    EXTRACTION_SYSTEM_RULES,
)
from pydantic import BaseModel

logger = logging.getLogger("extractor")


class ExtractionResult(BaseModel):
    num_travelers: int | None = Field(default=None)
    num_underage_travelers: int | None = Field(default=None)
    departure_location: str | None = Field(default=None)
    date: str | None = Field(default=None)
    response_message: str = Field(
        default=""
    )  # Friendly Spanish message to send back to the user
    is_complete: bool = Field(
        default=False
    )  # True when all required fields have been collected
    # Populated only by extract_with_offers()
    offer_accepted: bool = Field(default=False)


class LLMExtractionService:
    MAX_HISTORY_MESSAGES = 30

    def __init__(self):
        self.client = AsyncOpenAI(api_key=get_openai_settings().OPENAI_API_KEY)

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

    def _compute_completeness(self, data: ExtractionResult, session: dict) -> bool:
        merged_travelers = (
            data.num_travelers
            if data.num_travelers is not None
            else session.get("num_travelers")
        )
        merged_underage = (
            data.num_underage_travelers
            if data.num_underage_travelers is not None
            else session.get("num_underage_travelers")
        )
        merged_departure = (
            data.departure_location
            if data.departure_location is not None
            else session.get("departure_location")
        )
        merged_date = data.date if data.date is not None else session.get("date")

        required_fields = session.get("required_fields", ["date"])
        date_required = (
            "date" in required_fields
            or "fecha" in " ".join(map(str, required_fields)).lower()
        )
        return (
            merged_travelers is not None
            and merged_underage is not None
            and merged_departure is not None
            and (not date_required or merged_date is not None)
        )

    def _append_history_turn(
        self,
        session: dict,
        user_message: str,
        assistant_message: str,
    ) -> None:
        history = session.setdefault("messages_history", [])
        history.append({"role": "user", "content": user_message})
        if assistant_message:
            history.append({"role": "assistant", "content": assistant_message})

    def _trim_history(self, session: dict) -> None:
        history = session.get("messages_history", [])
        if len(history) > self.MAX_HISTORY_MESSAGES:
            session["messages_history"] = history[-self.MAX_HISTORY_MESSAGES :]

    async def extract(self, message: str, session: dict) -> ExtractionResult:
        """
        Stage 3 extraction agent — custom quote flow only.

        Called only after the user has rejected the pre-built offers.
        Extracts: num_travelers, num_underage_travelers, departure_location, date.
        """
        known_str = self._build_known_str(session)
        history = self.build_messages_history(session)

        system_rules = EXTRACTION_SYSTEM_RULES.format(known_str=known_str)

        messages = [
            *history,
            {"role": "system", "content": system_rules},
            {"role": "user", "content": message},
        ]

        try:
            response = await self.client.chat.completions.parse(
                model="gpt-4o-mini",
                messages=messages,
                response_format=ExtractionResult,
                max_tokens=350,
            )
            data = response.choices[0].message.parsed
            if data is None:
                raise ValueError("LLM returned no parsed payload")
        except Exception as exc:
            logger.exception("[extract] LLM parse failed: %s", exc)
            fallback = ExtractionResult(
                response_message=(
                    "Perdón, no llegué a entender bien. ¿Me podés confirmar cuántos "
                    "adultos viajan, si hay menores, desde qué ciudad salen y en qué fecha?"
                ),
                is_complete=False,
            )
            self._append_history_turn(session, message, fallback.response_message)
            self._trim_history(session)
            return fallback

        logger.debug("[extract] raw LLM response: %s", data)
        is_complete = self._compute_completeness(data, session)
        data.is_complete = is_complete

        self._append_history_turn(session, message, data.response_message)
        self._trim_history(session)

        return data

    async def combined_extraction_answer(
        self,
        message: str,
        session: dict,
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
        history = self.build_messages_history(session)
        system_intro = COMBINED_EXTRACTION_SYSTEM_INTRO.format(destination=destination)
        system_rules = COMBINED_EXTRACTION_SYSTEM_RULES

        messages = [
            {"role": "system", "content": system_intro},
            *history,
            {"role": "system", "content": system_rules},
            {"role": "user", "content": message},
        ]

        try:
            response = await self.client.chat.completions.parse(
                model="gpt-4o-mini",
                messages=messages,
                response_format=ExtractionResult,
                max_tokens=400,
            )
            data = response.choices[0].message.parsed
            if data is None:
                raise ValueError("LLM returned no parsed payload")
        except Exception as exc:
            logger.exception("[extract_with_offers] LLM parse failed: %s", exc)
            fallback = ExtractionResult(
                response_message=(
                    "¡Gracias! Para ayudarte mejor, ¿me confirmás desde qué ciudad salen "
                    "y para cuántas personas es el viaje?"
                ),
                offer_accepted=False,
                is_complete=False,
            )
            self._append_history_turn(session, message, fallback.response_message)
            self._trim_history(session)
            return fallback

        logger.debug("[extract_with_offers] raw LLM response: %s", data)

        self._append_history_turn(session, message, data.response_message)
        self._trim_history(session)

        offer_accepted = data.offer_accepted
        is_complete = self._compute_completeness(data, session)

        data.is_complete = is_complete
        data.offer_accepted = offer_accepted

        return data
