"""
Tests for the tool call streaming accumulator content handling.

Anthropic streaming chunks carry text as a list of content blocks instead
of a plain string; the chunks yielded to the SSE layer must contain str
content or the route drops them (ChatResponse.content is Optional[str]).
"""

from typing import Any

from langchain_core.messages import AIMessageChunk

from gns3server.agent.gns3_copilot.utils.tool_call_stream import ToolCallStreamAccumulator


def _stream_event(chunk: AIMessageChunk) -> dict[str, Any]:
    return {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "metadata": {}}


def test_plain_text_content_passes_through() -> None:
    accumulator = ToolCallStreamAccumulator()
    chunks = accumulator.process_event(_stream_event(AIMessageChunk(content="hello")))

    assert chunks == [{"type": "content", "content": "hello", "message_id": None}]


def test_content_block_list_is_flattened_to_text() -> None:
    """The langchain block format must not leak into the str-typed chunk."""
    accumulator = ToolCallStreamAccumulator()
    chunk = AIMessageChunk(
        content=[
            {"text": "Hello ", "type": "text", "index": 0},
            {"text": "world", "type": "text", "index": 0},
        ]
    )
    chunks = accumulator.process_event(_stream_event(chunk))

    assert chunks == [{"type": "content", "content": "Hello world", "message_id": None}]


def test_chunk_without_text_emits_nothing() -> None:
    """Empty text blocks (e.g. thinking with display omitted) stay hidden."""
    accumulator = ToolCallStreamAccumulator()
    chunk = AIMessageChunk(content=[{"text": "", "type": "text", "index": 0}])
    chunks = accumulator.process_event(_stream_event(chunk))

    assert chunks == []
