"""
Tests for the copilot title generation node.

The title request must end with a user message: the current Anthropic
models reject assistant-message prefill (400 "The conversation must end
with a user message"). The transcript is therefore folded into one user
message instead of replaying the raw thread messages.
"""

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from gns3server.agent.gns3_copilot.agent import gns3_copilot as mod


class _FakeTitleModel:
    """Records the messages and returns a fixed title."""

    def __init__(self, calls: list[tuple[list[BaseMessage], Any]]) -> None:
        self._calls = calls

    def invoke(self, messages: list[BaseMessage], config: Any = None) -> SimpleNamespace:
        self._calls.append((messages, config))
        return SimpleNamespace(text="QinQ Topology Overview")


def _patch_agent(monkeypatch, llm_config: dict, calls: list) -> None:
    monkeypatch.setattr(mod, "get_current_llm_config", lambda: llm_config)
    monkeypatch.setattr(mod, "get_prompt", lambda name: "Generate a concise title.")
    monkeypatch.setattr(mod, "create_title_model", lambda llm_config: _FakeTitleModel(calls))


def test_title_request_ends_with_user_message(monkeypatch) -> None:
    calls: list = []
    _patch_agent(
        monkeypatch,
        {"provider": "anthropic", "model": "claude-opus-5-5"},
        calls,
    )

    state = {
        "messages": [
            HumanMessage(content="hello"),
            AIMessage(content=[{"text": "Hi there, how can I help?", "type": "text", "index": 0}]),
        ],
        "session_id": "s1",
    }

    result = mod.generate_title(state)

    assert result == {"conversation_title": "QinQ Topology Overview", "session_id": "s1"}

    messages, config = calls[0]
    # System prompt first, transcript second - and the transcript is a user
    # message so no provider sees an assistant turn at the end.
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[-1], HumanMessage)
    # Both sides of the conversation made it into the transcript, blocks
    # flattened to text.
    assert "User: hello" in messages[-1].content
    assert "Assistant: Hi there, how can I help?" in messages[-1].content
    # Anthropic gets no sampling override (temperature is deprecated).
    assert config is None


def test_existing_title_short_circuits(monkeypatch) -> None:
    calls: list = []
    _patch_agent(monkeypatch, {"provider": "deepseek"}, calls)

    state = {
        "messages": [HumanMessage(content="hello")],
        "conversation_title": "Already Named",
        "session_id": "s1",
    }

    assert mod.generate_title(state) == {}
    assert calls == []
