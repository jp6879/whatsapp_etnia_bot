"""
LangChain tool definitions for EtniaAgent.

Tools are built via a factory function that closes over a `MessageManager` instance,
giving tools access to the offers database without global state.

Sentinel return format:
  "HANDOFF_WITH_OFFER:<offer_key>"  → user accepted a pre-built offer
  "HANDOFF_NO_OFFER:<reason>"       → all info gathered or edge case → human takeover
  "ASK:<text>"                      → question to ask the user (sent via WhatsApp)
  "OFFER:<message_text>"            → offer text to send to the user
  "ANSWER:<text>"                   → answer to a knowledge question

EtniaAgent.run() parses these sentinels to determine:
  - What to send to WhatsApp
  - Which SessionState to transition to
  - Which session fields to update
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from app.utils.message_manager import MessageManager

logger = logging.getLogger("agent.tools")


def build_etnia_tools(message_manager: "MessageManager"):
    """
    Returns a list of LangChain tools bound to the given message_manager instance.
    Call once at startup and reuse.
    """

    @tool
    async def present_offers(destination_key: str) -> str:
        """
        Retrieve and return the pre-built travel offer text for a given destination key.
        Call this when you need to present the available packages to the user.
        The returned text should be forwarded to the user as-is.

        Args:
            destination_key: The destination key from the session (e.g. 'turquia', 'europa').
        """
        logger.debug("[tool] present_offers called with key=%r", destination_key)
        offer_data = message_manager.get_offer_for_destination_key(destination_key)
        if not offer_data:
            return f"HANDOFF_NO_OFFER:no_offers_for_{destination_key}"
        return f"OFFER:{offer_data['message']}"

    @tool
    async def accept_offer(offer_key: str) -> str:
        """
        Signal that the user has explicitly accepted a pre-built travel offer.
        Only call this when the user clearly confirms they want the offer
        (they say 'sí', 'me interesa', 'perfecto', 'ese', 'lo quiero', etc.).

        Args:
            offer_key: The destination key of the accepted offer (e.g. 'turquia').
        """
        logger.debug("[tool] accept_offer called with key=%r", offer_key)
        return f"HANDOFF_WITH_OFFER:{offer_key}"

    @tool
    async def ask_for_info(question: str) -> str:
        """
        Ask the user for a single piece of missing information.
        Use this to request: number of adults, number of minors (children under 18),
        departure city, or travel date/month.
        Only ask for ONE field at a time.

        Args:
            question: A friendly, natural Spanish question to send to the user.
        """
        logger.debug("[tool] ask_for_info called with question=%r", question[:80])
        return f"ASK:{question}"

    @tool
    async def handoff_to_agent(reason: str) -> str:
        """
        Signal that this conversation should be handed off to a human travel advisor.
        Call this when ALL required information has been collected (adults, minors,
        departure city, travel date) or when the bot cannot help further.

        Args:
            reason: Brief explanation of why the handoff is happening
                    (e.g. 'info_completa', 'cliente_pide_asesor', 'destino_sin_oferta').
        """
        logger.debug("[tool] handoff_to_agent called with reason=%r", reason)
        return f"HANDOFF_NO_OFFER:{reason}"

    @tool
    async def answer_travel_question(question: str, destination: str = "") -> str:
        """
        Answer a general travel knowledge question from the user.
        Use this for questions about visas, best seasons to travel, what to pack,
        currency, safety, climate, or any other general travel information.
        Note: This is a placeholder for the RAG integration in Phase 3.
        For now, return a friendly message asking the user to ask an advisor.

        Args:
            question: The user's question about travel.
            destination: Optional destination context (e.g. 'Turquía').
        """
        logger.debug(
            "[tool] answer_travel_question question=%r destination=%r",
            question[:80],
            destination,
        )
        # Phase 3 will replace this with a RAG lookup via ChromaDB / pgvector.
        # For now, provide a helpful fallback so the agent doesn't fail.
        dest_context = f" sobre {destination}" if destination else ""
        answer = (
            f"Esa es una muy buena pregunta{dest_context}. "
            "Para darte la información más precisa posible, "
            "un asesor de Etnia Viajes se va a contactar con vos. "
            "¿Te puedo ayudar con algo más?"
        )
        return f"ANSWER:{answer}"

    return [
        present_offers,
        accept_offer,
        ask_for_info,
        handoff_to_agent,
        answer_travel_question,
    ]
