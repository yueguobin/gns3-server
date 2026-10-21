#!/usr/bin/env python
#
# Copyright (C) 2026 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Offline tests for the GNS3-Copilot LangGraph agent (Phase 0).

The graph is compiled with an in-memory checkpointer and driven through the
seams installed by CopilotGraphHarness: a scripted model, fake tools and
stubbed prompt loading. No provider, GNS3 server or skills repository is
involved. See docs/gns3-copilot/roadmap/copilot-hardening-roadmap.md.
"""

import json

import pytest
from langchain_core.messages import ToolMessage

from tests.agent.copilot_fakes import (
    DEFAULT_TITLE,
    CopilotGraphHarness,
    FakeTool,
    ScriptedChatModel,
    ai_text,
    ai_tool_call,
)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    harness = CopilotGraphHarness(monkeypatch, evidence_db_path=tmp_path / "test_evidence.db")
    yield harness
    harness.close()


def test_react_round_trip_executes_tool_and_finishes(harness):
    fake = harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_show", {"devices": ["r1"]}),
            ai_text("Diagnosis complete"),
        ]
    )

    result = harness.run("check r1")

    messages = result["messages"]
    assert len(messages) == 4  # Human, AI tool call, Tool result, AI final
    assert result["llm_calls"] == 2
    assert fake.calls == [{"devices": ["r1"]}]
    tool_msg = messages[2]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.name == "fake_show"
    assert json.loads(tool_msg.content) == {"status": "ok", "tool": "fake_show"}
    assert messages[3].content == "Diagnosis complete"
    # First full turn also generates the conversation title
    assert result["conversation_title"] == DEFAULT_TITLE


def test_tool_error_becomes_error_observation(harness):
    harness.register_tool(FakeTool("fake_boom", error=ValueError("boom")))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_boom", {}),
            ai_text("recovered from the failure"),
        ]
    )

    result = harness.run("run the failing tool")

    tool_msg = result["messages"][2]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.content.startswith("Error:")
    assert "boom" in tool_msg.content
    # The loop continues after the failure: the model sees the error and
    # produces a final answer
    assert result["messages"][3].content == "recovered from the failure"


def test_model_failure_propagates_as_graph_error(harness):
    harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel([RuntimeError("provider is down")])

    with pytest.raises(RuntimeError, match="provider is down"):
        harness.run("anything")


def test_abort_set_during_tool_execution_ends_turn(harness):
    session_id = "abort-during-tool"

    def set_abort(args):
        harness.copilot.set_abort_flag(session_id)

    harness.register_tool(FakeTool("fake_slow", side_effect=set_abort))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_slow", {}),
            ai_text("never reached"),
        ]
    )

    result = harness.run("run the slow tool", session_id=session_id)

    # recursion_limit_continue sees the abort flag after tool_node and ends
    # the turn: the tool result is the last message, no further llm call
    assert isinstance(result["messages"][-1], ToolMessage)
    assert result["llm_calls"] == 1


def test_abort_with_pending_tool_calls_fills_aborted_results(harness):
    session_id = "abort-pending-calls"

    class FlaggingModel(ScriptedChatModel):
        # Sets the abort flag from inside the model call, which is where a
        # real user abort lands when it arrives during llm_call
        def invoke(self, messages, config=None, **kwargs):
            harness.copilot.set_abort_flag(session_id)
            return super().invoke(messages, config, **kwargs)

    harness.register_tool(FakeTool("fake_show"))
    harness.model = FlaggingModel([ai_tool_call("fake_show", {}, call_id="call_9")])

    result = harness.run("trigger abort", session_id=session_id)

    messages = result["messages"]
    # Human, AI tool call (pending), aborted Tool result
    assert len(messages) == 3
    aborted = messages[2]
    assert isinstance(aborted, ToolMessage)
    assert aborted.tool_call_id == "call_9"
    assert aborted.metadata.get("aborted") is True
    assert json.loads(aborted.content)["status"] == "aborted"
    # The real tool never ran
    assert harness.registry["fake_show"].calls == []


def test_title_generated_once_on_first_turn_only(harness):
    harness.model = ScriptedChatModel([ai_text("first answer")])
    result = harness.run("question one")
    assert result["conversation_title"] == DEFAULT_TITLE
    assert harness.title_calls == 1

    harness.model = ScriptedChatModel([ai_text("second answer")])
    result = harness.run("question two")

    # Second turn on the same thread: no title regeneration. llm_calls is a
    # per-turn counter — the run inputs reset it to 0, so this turn's single
    # model call reads 1 again (title state persists, the counter does not)
    assert harness.title_calls == 1
    assert result["conversation_title"] == DEFAULT_TITLE
    assert result["llm_calls"] == 1


def test_recursion_guard_ends_turn_before_hard_limit(harness):
    harness.register_tool(FakeTool("fake_loop"))
    harness.model = ScriptedChatModel([ai_tool_call("fake_loop", {})] * 6)

    # Without the remaining_steps guard the always-looping model exhausts
    # recursion_limit and graph.invoke raises GraphRecursionError
    result = harness.run("loop forever", recursion_limit=8, remaining_steps=8)

    assert isinstance(result["messages"][-1], ToolMessage)
    assert result["llm_calls"] <= 3


def test_missing_llm_config_degrades_gracefully(harness):
    harness.model = ScriptedChatModel([])
    harness.title_model = ScriptedChatModel([])

    result = harness.run("hello", llm_config=None)

    # llm_call skips the model entirely; the title falls back and the turn
    # still ends cleanly
    assert result["llm_calls"] == 0
    assert harness.model.calls == 0
    assert harness.title_model.calls == 0
    assert result["conversation_title"] == "Untitled Session"


def test_call_budget_ends_turn_with_graceful_message(harness):
    harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel([ai_tool_call("fake_show", {})] * 5 + [ai_text("done")])

    result = harness.run(
        "keep going",
        llm_config=dict(harness.llm_config, max_llm_calls_per_turn=2),
        recursion_limit=50,
        remaining_steps=50,
    )

    # The third llm_call entry hits the budget guard before invoking the model
    assert harness.model.calls == 2
    assert result["llm_calls"] == 2
    messages = result["messages"]
    # Human, AI tool call, Tool, AI tool call, Tool, graceful message
    assert len(messages) == 6
    graceful = messages[-1]
    assert "budget" in graceful.content.lower()
    assert graceful.metadata.get("budget_exhausted") is True
    assert not getattr(graceful, "tool_calls", None)


def test_default_call_budget_fires_before_recursion_guard(harness):
    harness.register_tool(FakeTool("fake_loop"))
    harness.model = ScriptedChatModel([ai_tool_call("fake_loop", {})] * 20)

    # Default recursion_limit (25) with no budget configured: the default
    # budget of 10 model calls must end the turn, with the explained
    # message, before the silent remaining_steps guard does
    result = harness.run("loop forever")

    assert harness.model.calls == 10
    assert result["llm_calls"] == 10
    assert result["messages"][-1].metadata.get("budget_exhausted") is True


def test_token_accumulation_prefers_reported_usage(harness):
    harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_show", {}, usage={"input_tokens": 100, "output_tokens": 50}),
            ai_text("done", usage={"input_tokens": 10, "output_tokens": 5}),
        ]
    )

    result = harness.run("collect usage")

    # No token cap configured, but the reported usage still accumulates
    assert result["turn_tokens"] == 165
    assert result["llm_calls"] == 2


def test_token_budget_ends_turn(harness):
    harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_show", {}, usage={"input_tokens": 100, "output_tokens": 50}),
            ai_tool_call("fake_show", {}),
            ai_text("never reached"),
        ]
    )

    result = harness.run(
        "spend tokens",
        llm_config=dict(harness.llm_config, max_total_tokens_per_turn=100),
        recursion_limit=50,
        remaining_steps=50,
    )

    # The first call reported 150 tokens, so the second entry is over budget
    assert harness.model.calls == 1
    assert result["turn_tokens"] == 150
    graceful = result["messages"][-1]
    assert graceful.metadata.get("budget_exhausted") is True
    assert "tokens" in graceful.content


def test_token_estimate_used_when_usage_missing(harness):
    harness.register_tool(FakeTool("fake_show"))
    harness.model = ScriptedChatModel([ai_text("a final answer with some words in it")])

    result = harness.run("estimate tokens")

    # No usage_metadata on the scripted response: the tiktoken estimate
    # over request and response text still feeds the counter
    assert result["turn_tokens"] > 0


# ---------------------------------------------------------------------------
# Phase 2: evidence externalization
# ---------------------------------------------------------------------------


def _evidence_row_count(harness) -> int:
    import sqlite3

    conn = sqlite3.connect(harness.evidence_db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM tool_evidence").fetchone()[0]
    finally:
        conn.close()


def test_large_tool_output_externalized_to_evidence(harness):
    big_output = "B" * 1_000_000
    harness.register_tool(FakeTool("fake_big", result=big_output))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_big", {}),
            ai_text("done"),
        ]
    )

    result = harness.run("read something huge")

    # The ToolMessage in the state is a small bounded view, not the payload
    tool_msg = result["messages"][2]
    assert len(tool_msg.content) < 6000
    view = json.loads(tool_msg.content)
    assert view["size_chars"] == 1_000_000
    assert view["head"] == "B" * 2048
    assert view["evidence_id"]
    assert "get_evidence" in view["note"]

    # The evidence row in the store holds the full output
    from gns3server.agent.gns3_copilot.agent.evidence_store import get_store

    row = get_store(harness.evidence_db_path).get(view["evidence_id"])
    assert row is not None
    assert row["content"] == big_output
    assert row["tool_name"] == "fake_big"
    assert row["thread_id"] == "test-session"


def test_get_evidence_tool_reads_back_full_output(harness):
    big_output = "".join(f"line {i:06d} of the device output\n" for i in range(2000))
    harness.register_tool(FakeTool("fake_big", result=big_output))

    class EvidenceReadingModel(ScriptedChatModel):
        # First call requests the big tool; the second reads the evidence
        # id out of the ToolMessage that came back and retrieves it; the
        # third finishes from the scripted queue
        def invoke(self, messages, config=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ai_tool_call("fake_big", {})
            if self.calls == 2:
                tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
                view = json.loads(tool_msgs[-1].content)
                return ai_tool_call(
                    "get_evidence",
                    {"tool_input": json.dumps({"evidence_id": view["evidence_id"]})},
                )
            return super().invoke(messages, config, **kwargs)

    harness.model = EvidenceReadingModel([ai_text("all read")])

    result = harness.run("retrieve the full output")

    messages = result["messages"]
    # Human, AI tool call, bounded view, AI get_evidence call, window, final
    assert len(messages) == 6
    retrieval = json.loads(messages[4].content)
    assert retrieval["evidence_id"] == json.loads(messages[2].content)["evidence_id"]
    assert retrieval["returned_chars"] == 3000  # default window
    assert retrieval["has_more"] is True
    assert retrieval["content"].startswith("line 000000")
    # The retrieval window is a result with a content field, not a
    # truncated view: it stays inline and is not externalized again
    assert "note" not in retrieval


def test_get_evidence_tool_paging(harness):
    from gns3server.agent.gns3_copilot.agent.evidence_store import get_store
    from gns3server.agent.gns3_copilot.gns3_client.context_helpers import (
        set_current_evidence_db_path,
    )
    from gns3server.agent.gns3_copilot.tools_v2 import GetEvidenceTool

    content = "x" * 10000
    row = get_store(harness.evidence_db_path).save(thread_id="test-session", tool_name="fake", content=content)
    set_current_evidence_db_path(harness.evidence_db_path)

    tool = GetEvidenceTool()
    first = tool.invoke({"tool_input": json.dumps({"evidence_id": row["evidence_id"], "offset": 9000, "limit": 2000})})
    assert first["returned_chars"] == 1000
    assert first["has_more"] is False

    missing = tool.invoke({"tool_input": json.dumps({"evidence_id": "no-such-id"})})
    assert "error" in missing


def test_small_tool_output_stays_inline(harness):
    harness.register_tool(FakeTool("fake_small", result={"status": "ok"}))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_small", {}),
            ai_text("done"),
        ]
    )

    result = harness.run("small output")

    # Unchanged behaviour: no evidence row, the result is the message
    assert json.loads(result["messages"][2].content) == {"status": "ok"}
    assert _evidence_row_count(harness) == 0


def test_dict_output_keys_summary_in_view(harness):
    big_dict = {
        "r1": "interface up\n" + "detail " * 2000,
        "r2": "interface down\n" + "detail " * 2000,
    }
    harness.register_tool(FakeTool("fake_devices", result=big_dict))
    harness.model = ScriptedChatModel(
        [
            ai_tool_call("fake_devices", {}),
            ai_text("done"),
        ]
    )

    result = harness.run("check devices")

    view = json.loads(result["messages"][2].content)
    # One status line per key keeps the model oriented
    assert view["keys_summary"] == {"r1": "interface up", "r2": "interface down"}
    assert view["evidence_id"]


def test_large_output_degrades_without_store(monkeypatch):
    harness = CopilotGraphHarness(monkeypatch)  # no evidence database path
    try:
        harness.register_tool(FakeTool("fake_big", result="Z" * 100_000))
        harness.model = ScriptedChatModel(
            [
                ai_tool_call("fake_big", {}),
                ai_text("done"),
            ]
        )

        result = harness.run("no store configured")

        view = json.loads(result["messages"][2].content)
        assert "evidence_id" not in view
        assert view["head"] == "Z" * 2048
    finally:
        harness.close()
