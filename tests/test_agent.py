"""
Phase 2 — EtniaAgent tests.

Run with:
    pytest tests/test_agent.py -v

All tests mock ChatOpenAI so they run offline with no API keys.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_message_manager(has_offers: bool = True):
    mm = MagicMock()
    if has_offers:
        mm.get_offer_for_destination_key.return_value = {
            "message": "🌍 Paquete Europa 14 días — desde USD 2.800 por persona",
            "summary_for_bot": "Europa 14 días desde Buenos Aires a partir de USD 2.800 p/p",
        }
    else:
        mm.get_offer_for_destination_key.return_value = None
    mm.get_iata_code = AsyncMock(return_value="EZE")
    return mm


def _make_session(state="presenting_offers") -> dict:
    return {
        "state": state,
        "destination": "Europa",
        "offer_type": "standard",
        "destination_key": "europa",
        "full_name": "Test User",
        "date_of_contact": "2026-03-10 21:00",
        "count_requests": 2,
        "messages_history": [
            {"role": "assistant", "content": "¡Hola! Somos Etnia Viajes"},
            {"role": "assistant", "content": "🌍 Paquete Europa..."},
            {"role": "assistant", "content": "¿Qué te parecen estas opciones?"},
        ],
        "num_travelers": None,
        "num_underage_travelers": None,
        "departure_location": None,
        "departure_iata_code": None,
        "date": None,
    }


def _ai_message_with_tool_call(
    tool_name: str, args: dict, tool_call_id: str = "call_1"
) -> AIMessage:
    """Build a fake AIMessage that contains a tool_call (as LangChain sends them)."""
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": args, "id": tool_call_id}]
    return msg


def _ai_message_text(text: str) -> AIMessage:
    """Build a fake AIMessage with plain text (no tool calls)."""
    msg = AIMessage(content=text)
    msg.tool_calls = []
    return msg


# Helper: build an EtniaAgent with mocked _llm
def _make_agent(mm, llm_responses: list):
    """
    Instantiate EtniaAgent with a mocked _llm that returns responses in sequence.
    llm_responses: list of AIMessage objects returned by successive ainvoke() calls.
    """
    from unittest.mock import patch

    with patch("app.services.agent.etnia_agent._configure_langsmith"):
        with patch("app.services.agent.etnia_agent.ChatOpenAI") as MockLLM:
            mock_llm_instance = MagicMock()
            mock_llm_instance.bind_tools.return_value = mock_llm_instance
            mock_llm_instance.ainvoke = AsyncMock(side_effect=llm_responses)
            MockLLM.return_value = mock_llm_instance

            from app.services.agent.etnia_agent import EtniaAgent

            agent = EtniaAgent(mm)
            agent._llm = mock_llm_instance
    return agent


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_agent_handoff_with_offer_on_acceptance():
    """
    When the LLM calls accept_offer and gets HANDOFF_WITH_OFFER sentinel,
    EtniaAgent.run() should return new_state=HANDOFF_WITH_OFFER and a confirm message.
    """
    from app.core.enums import SessionState

    mm = _make_message_manager()
    session = _make_session()

    # LLM first responds with a tool call, then the loop short-circuits
    tool_call_msg = _ai_message_with_tool_call("accept_offer", {"offer_key": "europa"})

    agent = _make_agent(mm, [tool_call_msg])
    result = await agent.run(session=session, message="Sí, me interesa ese paquete")

    assert result.new_state == SessionState.HANDOFF_WITH_OFFER
    assert result.session_updates.get("accepted_offer_key") == "europa"
    assert len(result.messages_to_send) == 1
    assert "asesor" in result.messages_to_send[0].lower()


async def test_agent_handoff_no_offer_when_info_complete():
    """
    When the LLM calls handoff_to_agent (all info collected),
    EtniaAgent.run() should return new_state=HANDOFF_NO_OFFER.
    """
    from app.core.enums import SessionState

    mm = _make_message_manager()
    session = _make_session(state="extracting_information")
    session.update({"num_travelers": 2, "num_underage_travelers": 0, "date": "julio"})

    tool_call_msg = _ai_message_with_tool_call(
        "handoff_to_agent", {"reason": "info_completa"}
    )

    agent = _make_agent(mm, [tool_call_msg])
    result = await agent.run(session=session, message="Salimos de Córdoba")

    assert result.new_state == SessionState.HANDOFF_NO_OFFER
    assert len(result.messages_to_send) == 1
    assert "asesor" in result.messages_to_send[0].lower()


async def test_agent_ask_for_info_stays_in_extraction():
    """
    When the LLM calls ask_for_info, the state should stay EXTRACTING_INFORMATION
    and the question should be in messages_to_send.
    """
    from app.core.enums import SessionState

    mm = _make_message_manager()
    session = _make_session()

    # Round 1: tool call ask_for_info
    tool_call_msg = _ai_message_with_tool_call(
        "ask_for_info", {"question": "¿Desde qué ciudad argentina salís?"}
    )
    # Round 2: LLM says nothing more (no more tool calls)
    final_msg = _ai_message_text("")

    agent = _make_agent(mm, [tool_call_msg, final_msg])
    result = await agent.run(session=session, message="Somos 2 adultos")

    assert result.new_state == SessionState.EXTRACTING_INFORMATION
    assert any("ciudad" in m.lower() for m in result.messages_to_send)


async def test_agent_graceful_degradation_on_error():
    """
    If the LLM raises an exception, EtniaAgent.run() should return
    a fallback HANDOFF_NO_OFFER result instead of propagating the error.
    """
    from app.core.enums import SessionState

    mm = _make_message_manager()
    session = _make_session()

    from unittest.mock import patch

    with patch("app.services.agent.etnia_agent._configure_langsmith"):
        with patch("app.services.agent.etnia_agent.ChatOpenAI") as MockLLM:
            mock_llm_instance = MagicMock()
            mock_llm_instance.bind_tools.return_value = mock_llm_instance
            mock_llm_instance.ainvoke = AsyncMock(
                side_effect=RuntimeError("OpenAI timeout")
            )
            MockLLM.return_value = mock_llm_instance

            from importlib import reload
            import app.services.agent.etnia_agent as ea_mod

            reload(ea_mod)

            agent = ea_mod.EtniaAgent(mm)
            agent._llm = mock_llm_instance

            result = await agent.run(session=session, message="Hola")

    assert result.new_state == SessionState.HANDOFF_NO_OFFER
    assert len(result.messages_to_send) == 1
    assert "problema" in result.messages_to_send[0].lower()
