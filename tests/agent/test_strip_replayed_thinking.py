"""
Tests for stripping thinking blocks from replayed history.

Claude 5.x thinking blocks carry a signature bound to the conversation
prefix (system prompt included) they were produced with. The copilot
re-injects a live topology snapshot on every call, so replayed thinking
blocks fail signature validation; they are stripped before invoking.
"""

from langchain_core.messages import AIMessage, HumanMessage

from gns3server.agent.gns3_copilot.agent import gns3_copilot as mod


def test_plain_string_content_untouched():
    messages = [HumanMessage(content="hello"), AIMessage(content="hi")]
    assert mod._strip_replayed_thinking(messages) == messages


def test_thinking_blocks_removed_tool_use_kept():
    message = AIMessage(
        content=[
            {"type": "thinking", "thinking": "plan", "signature": "sig"},
            {"type": "tool_use", "id": "t1", "name": "get_topology", "input": {}},
        ]
    )
    result = mod._strip_replayed_thinking([message])

    assert len(result) == 1
    assert result[0].content == [{"type": "tool_use", "id": "t1", "name": "get_topology", "input": {}}]


def test_redacted_thinking_removed_too():
    message = AIMessage(
        content=[
            {"type": "redacted_thinking", "data": "blob"},
            {"type": "text", "text": "answer"},
        ]
    )
    result = mod._strip_replayed_thinking([message])

    assert result[0].content == [{"type": "text", "text": "answer"}]


def test_thinking_only_message_keeps_a_placeholder_text_block():
    """An assistant turn must not collapse to empty content."""
    message = AIMessage(content=[{"type": "thinking", "thinking": "plan", "signature": "sig"}])
    result = mod._strip_replayed_thinking([message])

    assert result[0].content == [{"type": "text", "text": ""}]


def test_messages_without_blocks_pass_through():
    messages = [HumanMessage(content="q"), AIMessage(content="a")]
    result = mod._strip_replayed_thinking(messages)

    assert result == messages
    assert result[0] is messages[0]
