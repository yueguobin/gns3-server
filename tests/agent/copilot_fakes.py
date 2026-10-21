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
Offline fakes and a graph harness for GNS3-Copilot graph tests (Phase 0).

The harness drives the copilot StateGraph without a model provider, without a
GNS3 server and without the external skills repository. Per test case, and at
call time (never at import time), it replaces:

- model construction (the _build_model_with_tools / _build_title_model seams
  in gns3_copilot.py),
- the tool registry (tools_by_name — a copy that tests register fakes into),
- prompt loading (load_system_prompt / get_prompt).

Tests install a ScriptedChatModel on the harness; its response queue drives
the ReAct loop. See docs/gns3-copilot/roadmap/copilot-hardening-roadmap.md.
"""

import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

# Private on purpose: set_current_llm_config(None) is not a valid call (it
# reads config.get()), so clearing the context var goes through the var
# itself. Test-only reach into the module is acceptable here.
from gns3server.agent.gns3_copilot.gns3_client.context_helpers import (
    _llm_config_context,
    set_current_llm_config,
)

DEFAULT_SESSION_ID = "test-session"
DEFAULT_TITLE = "Test Session Title"

# Sentinel for CopilotGraphHarness.run(): use the harness llm_config
_USE_HARNESS_CONFIG = object()


def ai_text(text: str, usage: dict | None = None) -> AIMessage:
    """An AIMessage with plain text content (a final answer)."""
    message = AIMessage(content=text)
    if usage is not None:
        message.usage_metadata = usage
    return message


def ai_tool_call(tool_name: str, args: dict, call_id: str = "call_1", usage: dict | None = None) -> AIMessage:
    """An AIMessage requesting one tool call."""
    message = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args, "id": call_id, "type": "tool_call"}],
    )
    if usage is not None:
        message.usage_metadata = usage
    return message


class ScriptedChatModel:
    """
    Replays a queue of prepared responses through invoke().

    An Exception instance in the queue is raised instead of returned, so a
    test can script failed model calls. bind_tools() returns self because
    llm_call binds tools before invoking.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, config=None, **kwargs):
        self.calls += 1
        if not self._responses:
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeTool:
    """A tool-shaped object for the tools_by_name registry."""

    def __init__(self, name, result=None, error=None, side_effect=None):
        """
        Args:
            name: tool name the scripted model asks for.
            result: canned return value (JSON-serializable).
            error: exception to raise instead of returning a result.
            side_effect: callable(args) run before the result is returned.
        """
        self.name = name
        self.description = f"Fake tool {name} for offline graph tests"
        self._result = result if result is not None else {"status": "ok", "tool": name}
        self._error = error
        self._side_effect = side_effect
        self.calls = []

    def invoke(self, args, config=None, **kwargs):
        self.calls.append(args)
        if self._side_effect is not None:
            self._side_effect(args)
        if self._error is not None:
            raise self._error
        return self._result


class CopilotGraphHarness:
    """
    Drives the copilot StateGraph offline.

    Instantiate once per test through the harness fixture; monkeypatch
    undoes every installed replacement at test teardown, and close() clears
    the request-scoped llm config context var so tests do not leak context
    into each other.
    """

    def __init__(self, monkeypatch, llm_config=None):
        from gns3server.agent.gns3_copilot.agent import gns3_copilot as copilot_module

        self.copilot = copilot_module
        self.llm_config = llm_config or {
            "provider": "test",
            "model": "scripted",
            "context_limit": 128,
            "context_strategy": "balanced",
            "copilot_mode": "teaching_assistant",
        }
        # Tests assign a fresh ScriptedChatModel before each run()
        self.model = ScriptedChatModel([])
        self.title_model = ScriptedChatModel([ai_text(DEFAULT_TITLE)])
        self.title_calls = 0
        self.registry = dict(copilot_module.tools_by_name)

        monkeypatch.setattr(copilot_module, "_build_model_with_tools", self._build_model)
        monkeypatch.setattr(copilot_module, "_build_title_model", self._build_title_model)
        monkeypatch.setattr(copilot_module, "tools_by_name", self.registry)
        monkeypatch.setattr(copilot_module, "load_system_prompt", self._load_system_prompt)
        monkeypatch.setattr(copilot_module, "get_prompt", self._get_prompt)
        self._graph = copilot_module.agent_builder.compile(checkpointer=InMemorySaver())

    # -- seams installed into the copilot module --------------------------

    def _build_model(self, mode_tools, llm_config=None):
        return self.model

    def _build_title_model(self, llm_config=None):
        self.title_calls += 1
        return self.title_model

    def _load_system_prompt(self, llm_config=None):
        return "You are the offline test copilot.\n\n{{topology_info}}"

    def _get_prompt(self, name):
        return "Generate a short conversation title."

    # -- driving ----------------------------------------------------------

    def register_tool(self, tool) -> FakeTool:
        """Register a fake tool under its name and return it."""
        self.registry[tool.name] = tool
        return tool

    def run(
        self,
        message,
        session_id=DEFAULT_SESSION_ID,
        recursion_limit=25,
        remaining_steps=20,
        llm_config=_USE_HARNESS_CONFIG,
    ):
        """
        Run one turn (one user message through the full tool loop) and
        return the final graph state.

        llm_config accepts the harness default (sentinel), a dict, or None.
        None leaves the request context without a config, which is how a
        degraded run is produced (llm_call skips the model entirely).
        """
        if llm_config is _USE_HARNESS_CONFIG:
            set_current_llm_config(self.llm_config)
        else:
            _llm_config_context.set(llm_config)
        self.copilot.clear_abort_flag(session_id)

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": recursion_limit,
        }
        inputs = {
            "messages": [HumanMessage(content=message, id=str(uuid.uuid4()))],
            "llm_calls": 0,
            "turn_tokens": 0,
            "remaining_steps": remaining_steps,
            "session_id": session_id,
            "abort": False,
        }
        return self._graph.invoke(inputs, config=config)

    def state(self, session_id=DEFAULT_SESSION_ID):
        """Read the checkpointed state for a session (after run())."""
        return self._graph.get_state({"configurable": {"thread_id": session_id}})

    def close(self):
        """Clear the llm config context var so it cannot leak into later tests."""
        _llm_config_context.set(None)
