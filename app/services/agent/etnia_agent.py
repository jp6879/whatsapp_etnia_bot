"""
EtniaAgent — LangChain-powered travel assistant for Etnia Viajes.

Architecture (LangChain 0.3+ / 1.x compatible):
  - Uses ChatOpenAI.bind_tools() for OpenAI function-calling.
  - A hand-rolled async tool-calling loop replaces the deprecated AgentExecutor.
  - Tool sentinels are parsed to update session state deterministically.
  - Conversation history is loaded from the existing Redis session dict.

Feature flag: Only active when `USE_LANGCHAIN_AGENT=true` in `.env`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from app.core.enums import SessionState
from app.services.agent.prompts import ETNIA_SYSTEM_PROMPT, ETNIA_NO_OFFERS_PROMPT
from app.services.agent.tools import build_etnia_tools
from app.config import wpp_settings, openai_settings

if TYPE_CHECKING:
    from app.utils.message_manager import MessageManager

logger = logging.getLogger("agent")

# Max tool-calling rounds per user turn (safety valve)
_MAX_ITERATIONS = 5


# ── Apply LangSmith env vars as early as possible ─────────────────────────────
def _configure_langsmith() -> None:
    """Set LangSmith env vars from AppSettings so the SDK picks them up."""
    if wpp_settings.LANGCHAIN_TRACING_V2 and wpp_settings.LANGCHAIN_API_KEY:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", wpp_settings.LANGCHAIN_API_KEY)
        os.environ.setdefault("LANGCHAIN_PROJECT", wpp_settings.LANGCHAIN_PROJECT)
        logger.info(
            "[LangSmith] Tracing enabled → project=%r", wpp_settings.LANGCHAIN_PROJECT
        )
    else:
        logger.debug("[LangSmith] Tracing disabled.")


# ── Result dataclass returned by EtniaAgent.run() ─────────────────────────────


@dataclass
class AgentResult:
    """
    Structured result from one agent turn.

    Attributes:
        messages_to_send: List of text messages to send to WhatsApp, in order.
        new_state:        Target SessionState after this turn.
        session_updates:  Dict of field updates to merge into the session dict.
    """

    messages_to_send: list[str] = field(default_factory=list)
    new_state: SessionState = SessionState.EXTRACTING_INFORMATION
    session_updates: dict = field(default_factory=dict)


# ── Sentinel parser ────────────────────────────────────────────────────────────


def _parse_sentinel(output: str) -> tuple[str, str]:
    """Split 'TYPE:payload' sentinel into (type, payload)."""
    if ":" in output:
        t, _, payload = output.partition(":")
        return t.strip(), payload.strip()
    return "UNKNOWN", output


def _build_known_info(session: dict) -> str:
    lines = []
    if session.get("num_travelers") is not None:
        lines.append(f"  - Adultos: {session['num_travelers']}")
    if session.get("num_underage_travelers") is not None:
        lines.append(f"  - Menores: {session['num_underage_travelers']}")
    if session.get("departure_location"):
        lines.append(f"  - Ciudad de salida: {session['departure_location']}")
    if session.get("date"):
        lines.append(f"  - Fecha / mes: {session['date']}")
    return "\n".join(lines) if lines else "  (Ninguna todavía)"


def _session_to_lc_history(session: dict) -> list:
    """Convert messages_history [{role, content}] → LangChain message objects."""
    result = []
    for msg in session.get("messages_history", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
    return result


# ── EtniaAgent ─────────────────────────────────────────────────────────────────


class EtniaAgent:
    """
    LangChain-powered travel assistant. Instantiate once and reuse per request.

    Uses ChatOpenAI.bind_tools() + a manual async tool-calling loop.
    Compatible with langchain-openai on any version that supports bind_tools.
    """

    def __init__(self, message_manager: "MessageManager") -> None:
        _configure_langsmith()

        self._message_manager = message_manager

        # Build tools and create a name→callable lookup for the dispatch loop
        raw_tools = build_etnia_tools(message_manager)
        self._tool_map: dict[str, Any] = {t.name: t for t in raw_tools}

        self._llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            api_key=openai_settings.OPENAI_API_KEY,
        ).bind_tools(raw_tools)

        logger.info(
            "[EtniaAgent] Initialized with %d tools: %s",
            len(raw_tools),
            list(self._tool_map),
        )

    async def run(self, session: dict, message: str) -> AgentResult:
        """
        Execute one agent turn using an async tool-calling loop.

        Args:
            session: Current Redis session dict.
            message: The user's latest WhatsApp message.

        Returns:
            AgentResult with messages to send, new state, and session updates.
        """
        destination = session.get("destination", "el destino seleccionado")
        offer_type = session.get("offer_type", "")
        destination_key = session.get("destination_key", "")
        known_info = _build_known_info(session)

        has_offers = (
            self._message_manager.get_offer_for_destination_key(destination_key)
            is not None
        )
        if has_offers:
            system_content = ETNIA_SYSTEM_PROMPT.format(
                destination=destination,
                offer_type=offer_type,
                destination_key=destination_key,
                known_info=known_info,
            )
        else:
            system_content = ETNIA_NO_OFFERS_PROMPT.format(destination=destination)

        # Build the message list: system + history + current user message
        messages: list = [SystemMessage(content=system_content)]
        messages.extend(_session_to_lc_history(session))
        messages.append(HumanMessage(content=message))

        logger.debug(
            "[EtniaAgent.run] destination=%r state=%r history=%d",
            destination,
            session.get("state"),
            len(messages) - 2,
        )

        try:
            result = await self._run_loop(messages)
        except Exception as exc:
            logger.error("[EtniaAgent.run] Error: %s", exc, exc_info=True)
            return AgentResult(
                messages_to_send=[
                    "Disculpá, tuve un problema técnico. Un asesor se va a contactar con vos. 😊"
                ],
                new_state=SessionState.HANDOFF_NO_OFFER,
            )
        return result

    async def _run_loop(self, messages: list) -> AgentResult:
        """
        Core async tool-calling loop.

        Calls the LLM, processes tool calls, feeds results back, and repeats
        until the model responds with a final text answer or a terminal sentinel.
        """
        tool_outputs: list[str] = []

        for iteration in range(_MAX_ITERATIONS):
            ai_message: AIMessage = await self._llm.ainvoke(messages)
            messages.append(ai_message)

            # If there are no tool calls, the model produced a final text answer
            if not getattr(ai_message, "tool_calls", None):
                final_text = ai_message.content or ""
                logger.debug(
                    "[EtniaAgent] No tool calls on iter %d — final text", iteration
                )
                return self._build_result_from_text(final_text, tool_outputs)

            # Execute all tool calls in this round
            for tool_call in ai_message.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_call_id = tool_call["id"]

                logger.debug(
                    "[EtniaAgent] iter=%d → tool=%r args=%r",
                    iteration,
                    tool_name,
                    tool_args,
                )

                tool_fn = self._tool_map.get(tool_name)
                if tool_fn is None:
                    tool_output = f"ERROR: unknown tool {tool_name}"
                else:
                    tool_output = await tool_fn.ainvoke(tool_args)

                tool_outputs.append(str(tool_output))
                messages.append(
                    ToolMessage(content=str(tool_output), tool_call_id=tool_call_id)
                )

                # Short-circuit on terminal sentinels — no need to keep looping
                sentinel_type, _ = _parse_sentinel(str(tool_output))
                if sentinel_type in ("HANDOFF_WITH_OFFER", "HANDOFF_NO_OFFER"):
                    logger.debug(
                        "[EtniaAgent] Terminal sentinel %r — short-circuiting",
                        sentinel_type,
                    )
                    return self._parse_tool_outputs(tool_outputs)

        # Safety: hit max iterations → hand off to a human
        logger.warning(
            "[EtniaAgent] Hit max iterations (%d) — handing off", _MAX_ITERATIONS
        )
        return AgentResult(
            messages_to_send=[
                "Un asesor va a retomar la conversación para ayudarte mejor. 😊"
            ],
            new_state=SessionState.HANDOFF_NO_OFFER,
        )

    def _parse_tool_outputs(self, tool_outputs: list[str]) -> AgentResult:
        """Interpret gathered tool output strings into a final AgentResult."""
        result = AgentResult()

        for output in tool_outputs:
            sentinel, payload = _parse_sentinel(output)

            if sentinel == "HANDOFF_WITH_OFFER":
                result.new_state = SessionState.HANDOFF_WITH_OFFER
                result.session_updates["accepted_offer_key"] = payload
                result.messages_to_send = [
                    "✨ ¡Perfecto! Un asesor se va a contactar con vos para "
                    "coordinar los detalles y confirmar la reserva. 😊"
                ]
                logger.info("[EtniaAgent] → HANDOFF_WITH_OFFER key=%r", payload)
                return result  # terminal

            elif sentinel == "HANDOFF_NO_OFFER":
                result.new_state = SessionState.HANDOFF_NO_OFFER
                result.messages_to_send = [
                    "Perfecto, ya tenemos toda la información. "
                    "Un asesor se va a contactar con vos para armarte una propuesta. 😊"
                ]
                logger.info("[EtniaAgent] → HANDOFF_NO_OFFER reason=%r", payload)
                return result  # terminal

            elif sentinel == "ASK":
                result.messages_to_send.append(payload)
                result.new_state = SessionState.EXTRACTING_INFORMATION

            elif sentinel == "OFFER":
                result.messages_to_send.append(payload)

            elif sentinel == "ANSWER":
                result.messages_to_send.append(payload)

        if not result.messages_to_send:
            result.messages_to_send = ["¿Me podés contar algo más sobre tu viaje?"]
        return result

    def _build_result_from_text(
        self, text: str, prior_tool_outputs: list[str]
    ) -> AgentResult:
        """Handle the case where the model returned text instead of a tool call."""
        # If prior tool calls already collected messages (ASK, OFFER, ANSWER, or HANDOFF),
        # prefer those over the model's final text — they are more structured.
        if prior_tool_outputs:
            result = self._parse_tool_outputs(prior_tool_outputs)
            if result.messages_to_send:
                return result

        # Fall back to the model's direct text output
        if text:
            return AgentResult(
                messages_to_send=[text],
                new_state=SessionState.EXTRACTING_INFORMATION,
            )

        return AgentResult(
            messages_to_send=["¿Me podés contar algo más sobre tu viaje?"],
            new_state=SessionState.EXTRACTING_INFORMATION,
        )
