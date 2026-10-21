# SPDX-License-Identifier: GPL-3.0-or-later
#
# GNS3-Copilot - AI-powered Network Lab Assistant for GNS3
#
# This file is part of GNS3-Copilot project.
#
# GNS3-Copilot is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# GNS3-Copilot is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with GNS3-Copilot. If not, see <https://www.gnu.org/licenses/>.
#
# Copyright (C) 2025 Yue Guobin (岳国宾)
# Author: Yue Guobin (岳国宾)
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

# mypy: ignore-errors

"""
GNS3 Network Automation Assistant - LangGraph Agent

This module implements the core LangGraph agent workflow for GNS3-Copilot,
an AI-powered assistant for GNS3 network automation and management.

The agent provides:
- LangGraph-based state management and workflow
- Mode-aware tool orchestration for GNS3 operations
- Context-aware conversation handling
- Automatic conversation title generation
- Integration with GNS3 topology management

Copilot Modes:
- "teaching_assistant" (default): Diagnostic tools only, no configuration
  changes
- "lab_automation_assistant": Full diagnostic and configuration tools

"""

# Standard library imports
import json
import logging
import operator
from datetime import datetime
from typing import Annotated, Any, Literal

# Third-party imports
from langchain.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict

# Local imports
from gns3server.agent.gns3_copilot.agent.context_manager import (
    count_tokens,
    create_pre_model_hook,
)
from gns3server.agent.gns3_copilot.agent.evidence_store import (
    externalize_tool_output,
)
from gns3server.agent.gns3_copilot.agent.model_factory import (
    create_base_model_with_tools,
    create_title_model,
)
from gns3server.agent.gns3_copilot.gns3_client import GNS3TopologyTool
from gns3server.agent.gns3_copilot.gns3_client.context_helpers import (
    get_current_llm_config,
)
from gns3server.agent.gns3_copilot.prompts import load_system_prompt
from gns3server.agent.gns3_copilot.skills import DeviceSkillsTool, InjectionSkillsTool, PacketAnalysisSkillsTool
from gns3server.agent.gns3_copilot.skills.registry import get_prompt
from gns3server.agent.gns3_copilot.tools_v2 import (
    ExecuteMultipleDeviceCommands,
    ExecuteMultipleDeviceConfigCommands,
    GetEvidenceTool,
    GNS3CreateEllipseDrawingTool,
    GNS3CreateNodeTool,
    GNS3CreateRectangleDrawingTool,
    GNS3CreateTextDrawingTool,
    GNS3LinkTool,
    GNS3PacketFilterTool,
    GNS3StartNodeTool,
    GNS3StopNodeTool,
    GNS3SuspendNodeTool,
    GNS3TemplateTool,
    GNS3UpdateNodeNameTool,
    GNS3WaitTool,
    PacketAnalysisTool,
)
from gns3server.agent.gns3_copilot.tools_v2.vpcs_tools_netmiko import VPCSCommands

# Set up logger for GNS3-Copilot
logger = logging.getLogger(__name__)

# Note: LLM model configuration is now managed by the new llm_model_configs
# system. The model_factory module handles model creation with configuration
# from the database.

# Define tools for different copilot modes
# Teaching assistant mode: READ-ONLY diagnostic tools only
TEACHING_ASSISTANT_MODE_TOOLS = [
    GNS3TemplateTool(),  # Get GNS3 node templates
    GNS3CreateNodeTool(),  # Create new nodes in GNS3
    GNS3LinkTool(),  # Create links between nodes
    GNS3CreateTextDrawingTool(),  # Add text labels to the canvas
    GNS3CreateRectangleDrawingTool(),  # Add rectangle annotations to the canvas
    GNS3CreateEllipseDrawingTool(),  # Add ellipse annotations to the canvas
    GNS3StartNodeTool(),  # Start GNS3 nodes (returns immediately)
    GNS3WaitTool(),  # Wait for nodes to boot (pair with start_gns3_node)
    GNS3UpdateNodeNameTool(),  # Update node name
    ExecuteMultipleDeviceCommands(),  # Execute show/display/debug commands
    # (READ-ONLY)
    PacketAnalysisTool(),  # Protocol-oriented packet analysis with tshark
    GetEvidenceTool(),  # Retrieve full stored tool output (evidence)
    PacketAnalysisSkillsTool(),  # Query packet analysis protocol definitions
    DeviceSkillsTool(),  # Get device-specific skills and command knowledge
]

# Lab automation assistant mode: Full diagnostic AND configuration tools
LAB_AUTOMATION_ASSISTANT_MODE_TOOLS = [
    GNS3TemplateTool(),  # Get GNS3 node templates
    GNS3CreateNodeTool(),  # Create new nodes in GNS3
    GNS3LinkTool(),  # Create links between nodes
    GNS3CreateTextDrawingTool(),  # Add text labels to the canvas
    GNS3CreateRectangleDrawingTool(),  # Add rectangle annotations to the canvas
    GNS3CreateEllipseDrawingTool(),  # Add ellipse annotations to the canvas
    GNS3StartNodeTool(),  # Start GNS3 nodes (returns immediately)
    GNS3WaitTool(),  # Wait for nodes to boot (pair with start_gns3_node)
    GNS3StopNodeTool(),  # Stop GNS3 nodes
    GNS3SuspendNodeTool(),  # Suspend GNS3 nodes (preserve state)
    GNS3UpdateNodeNameTool(),  # Update node name
    ExecuteMultipleDeviceCommands(),  # Execute show/display/debug commands
    # (READ-ONLY)
    ExecuteMultipleDeviceConfigCommands(),  # Execute configuration commands
    VPCSCommands(),  # Execute VPCS commands using Netmiko
    PacketAnalysisTool(),  # Protocol-oriented packet analysis with tshark
    GetEvidenceTool(),  # Retrieve full stored tool output (evidence)
    PacketAnalysisSkillsTool(),  # Query packet analysis protocol definitions
    DeviceSkillsTool(),  # Get device-specific skills and command knowledge
]

# Troubleshooting injection mode: Tools for injecting network faults
# Focused on configuration commands and injection skills for fault injection
TROUBLESHOOTING_INJECTION_MODE_TOOLS = [
    ExecuteMultipleDeviceCommands(),  # Get device configurations (READ-ONLY)
    ExecuteMultipleDeviceConfigCommands(),  # Inject configuration changes
    GNS3PacketFilterTool(),  # Manage packet filters on links (delay, loss, corrupt, etc.)
    GetEvidenceTool(),  # Retrieve full stored tool output (evidence)
    InjectionSkillsTool(),  # Query injection skills and fault types
    GNS3TopologyTool(),  # Get topology information
]

# Default tools (legacy support - will be overridden by mode-specific tools)
tools = LAB_AUTOMATION_ASSISTANT_MODE_TOOLS

# Create combined tool lookup for tool_node (supports all modes)
# tool_node will receive tool calls based on mode-specific tools bound to the
# model
# Combine all tools from all modes and deduplicate by tool name
ALL_TOOLS = LAB_AUTOMATION_ASSISTANT_MODE_TOOLS
tools_by_name = {tool.name: tool for tool in ALL_TOOLS}

# Add troubleshooting injection tools to the global tool registry
for tool in TROUBLESHOOTING_INJECTION_MODE_TOOLS:
    if tool.name not in tools_by_name:
        tools_by_name[tool.name] = tool

# Log application startup
logger.info("GNS3-Copilot application starting up")

# Constants for conversation title management
DEFAULT_CONVERSATION_TITLE = "New Conversation"
UNTITLED_SESSION_FALLBACK = "Untitled Session"
TITLE_MAX_LENGTH = 40

# Per-turn hard budget defaults (Phase 1)
# The defaults sit below what the recursion limit allows, so a runaway
# turn ends with the budget's explained message instead of the silent
# remaining_steps guard: 10 calls * 2 nodes + headroom fits well inside
# recursion_limit=25, and 40 inside the injection mode limit of 100
DEFAULT_MAX_LLM_CALLS_PER_TURN = 10
DEFAULT_MAX_LLM_CALLS_PER_TURN_TROUBLESHOOTING = 40

# Abort flags storage for session-level abort tracking
# This is checked by conditional edge functions to stop the graph
_abort_flags: dict[str, bool] = {}


def check_abort_flag(session_id: str) -> bool:
    """
    Check if abort flag is set for a session.

    Args:
        session_id: Session identifier

    Returns:
        True if abort is requested, False otherwise
    """
    return _abort_flags.get(session_id, False)


def set_abort_flag(session_id: str):
    """
    Set abort flag for a session.

    Args:
        session_id: Session identifier
    """
    _abort_flags[session_id] = True
    logger.debug("Abort flag set for session: %s", session_id)


def clear_abort_flag(session_id: str):
    """
    Clear abort flag for a session.

    Args:
        session_id: Session identifier
    """
    _abort_flags[session_id] = False
    logger.debug("Abort flag cleared for session: %s", session_id)


# Define state
class MessagesState(TypedDict):
    """
    GNS3-Copilot conversation state management class.

    Maintains the conversation state for the LangGraph workflow, including
    message history, call counters, and session titles for comprehensive
    dialogue management.

    Attributes:
        messages: List of conversation messages with cumulative updates using
                 operator.add
        llm_calls: Per-turn counter of LLM invocations. Reset to 0 by the
                 stream inputs at the start of each turn, incremented within
                 the turn.
        turn_tokens: Per-turn accumulated token cost of the model calls
                 (input + output). Reset the same way as llm_calls.
        remaining_steps: Is automatically managed by LangGraph's RemainingSteps
                       to track and limit recursion depth.
        conversation_title: Optional conversation title for session
                          identification and management
        topology_info: Dictionary containing GNS3 project topology information
        session_id: Session identifier for abort tracking
        abort: Flag to signal abort request
    """

    messages: Annotated[list[AnyMessage], operator.add]

    llm_calls: int

    turn_tokens: int

    remaining_steps: RemainingSteps

    # Optional conversation title
    conversation_title: str | None

    # Store GNS3 topology information
    topology_info: dict | None

    # Session identifier for abort tracking
    session_id: str | None

    # Abort flag to signal stop request
    abort: bool


def resolve_turn_budget(llm_config: dict, copilot_mode: str) -> tuple[int, int | None]:
    """
    Resolve the per-turn hard budget from the LLM config.

    Both keys are optional entries in the llm_model_configs config JSON.
    Values of the wrong type, booleans, zero or negative numbers fall back
    to the defaults. The token budget is opt-in: without a positive value
    there is no token cap (token reporting quality varies by provider).
    """
    max_calls = llm_config.get("max_llm_calls_per_turn")
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls <= 0:
        max_calls = (
            DEFAULT_MAX_LLM_CALLS_PER_TURN_TROUBLESHOOTING
            if copilot_mode == "troubleshooting_injection"
            else DEFAULT_MAX_LLM_CALLS_PER_TURN
        )
    max_tokens = llm_config.get("max_total_tokens_per_turn")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        max_tokens = None
    return max_calls, max_tokens


def _response_token_cost(response: Any, prepared_messages: list) -> int:
    """
    Token cost of one model call.

    Prefers provider-reported usage_metadata; falls back to a tiktoken
    estimate over the request and response text, so providers that do not
    report usage still feed the budget.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage:
        try:
            return int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        except (TypeError, ValueError):
            logger.debug("Unusable usage_metadata %r, falling back to estimate", usage)
    estimated = sum(count_tokens(str(getattr(m, "content", "") or "")) for m in prepared_messages)
    estimated += count_tokens(str(getattr(response, "content", "") or ""))
    return estimated


def _budget_exhausted_message(calls_used: int, max_calls: int, tokens_used: int, max_tokens: int | None) -> AIMessage:
    """
    Build the assistant message that ends a turn when the budget runs out.

    The message is a plain assistant answer (no tool calls), so the turn
    ends through the normal completion path and the frontend renders it
    like any other reply instead of an error event.
    """
    if calls_used >= max_calls:
        reason = f"{calls_used} model calls (limit: {max_calls})"
    else:
        reason = f"{tokens_used} tokens (limit: {max_tokens})"
    content = (
        f"I stopped here because this turn reached its budget: {reason}. "
        "All commands and results collected so far are saved in this conversation. "
        "Send a new message to continue with a fresh budget. If the limit is too "
        "low for the task, raise 'max_llm_calls_per_turn' or "
        "'max_total_tokens_per_turn' in the model configuration."
    )
    return AIMessage(
        content=content,
        metadata={
            "created_at": datetime.utcnow().isoformat(),
            "budget_exhausted": True,
        },
    )


def _build_model_with_tools(mode_tools: list, llm_config: dict | None) -> Any:
    """
    Build the chat model with tools bound for one llm_call step.

    Test seam for offline graph tests: they replace this per test case (at
    call time, via monkeypatch) with a scripted model so the graph runs
    without a real provider. See tests/agent/copilot_fakes.py.
    """
    return create_base_model_with_tools(mode_tools, llm_config=llm_config)


# Define llm call  node
def llm_call(state: dict, config: RunnableConfig | None = None):
    """
    LLM decides whether to call a tool or not.

    Uses pre_model_hook pattern for automatic topology injection and
    message trimming, ensuring separation of concerns and complete
    history preservation in state["messages"].
    """

    logger.debug("LLM call node invoked")

    # Get llm_config from request-scoped context variable
    llm_config = get_current_llm_config()

    if not llm_config:
        logger.error("LLM config not found in context")
        return {
            "messages": [],
            "llm_calls": state.get("llm_calls", 0),
            "topology_info": None,
        }

    logger.debug(
        "LLM config retrieved from context: provider=%s, model=%s",
        llm_config.get("provider"),
        llm_config.get("model"),
    )

    # Defensive check: skip LLM call if no user messages
    messages = state.get("messages", [])
    if not messages or len(messages) == 0:
        logger.warning("No messages in state, skipping LLM call")
        return {
            "messages": [],
            "llm_calls": state.get("llm_calls", 0),
            "topology_info": None,
        }

    # Select the copilot mode first: the budget defaults depend on it
    copilot_mode = llm_config.get("copilot_mode", "teaching_assistant").lower()

    # Hard budget guard (per turn): check before the model call so a
    # runaway tool loop ends with an explained assistant message instead
    # of the silent remaining_steps guard or a provider error
    max_llm_calls, max_total_tokens = resolve_turn_budget(llm_config, copilot_mode)
    llm_calls_used = state.get("llm_calls", 0) or 0
    turn_tokens_used = state.get("turn_tokens", 0) or 0
    if llm_calls_used >= max_llm_calls or (max_total_tokens is not None and turn_tokens_used >= max_total_tokens):
        logger.info(
            "Turn budget exhausted after %d calls / %d tokens (limits: %d calls / %s tokens) — ending turn",
            llm_calls_used,
            turn_tokens_used,
            max_llm_calls,
            max_total_tokens,
        )
        return {
            "messages": [_budget_exhausted_message(llm_calls_used, max_llm_calls, turn_tokens_used, max_total_tokens)],
            "llm_calls": llm_calls_used,
            "turn_tokens": turn_tokens_used,
            "topology_info": state.get("topology_info"),
            "session_id": state.get("session_id"),
        }

    # Get project_id from config configurable (set when starting the chat)
    project_id = None
    topology_info = None
    if config and config.get("configurable"):
        project_id = config["configurable"].get("project_id")

    # Retrieve topology information if available
    if project_id:
        try:
            topology_tool = GNS3TopologyTool()
            topology = topology_tool._run(project_id=project_id)

            if topology and "error" not in topology:
                topology_info = topology
                logger.info(
                    "Successfully retrieved topology for project_id: %s, name: %s",
                    project_id,
                    topology.get("name"),
                )
            else:
                logger.warning(
                    "Failed to retrieve topology for project_id %s: %s",
                    project_id,
                    topology.get("error", "Unknown error") if topology else "No result",
                )
        except Exception as e:
            logger.warning(
                "Error retrieving topology for project_id %s: %s",
                project_id,
                e,
            )

    # Store topology_info in state for pre_model_hook to access
    state["topology_info"] = topology_info

    # Select tools based on copilot_mode (computed before the budget check)
    if copilot_mode == "lab_automation_assistant":
        mode_tools = LAB_AUTOMATION_ASSISTANT_MODE_TOOLS
        logger.info("Using LAB_AUTOMATION_ASSISTANT mode tools (includes configuration tools)")
    elif copilot_mode == "troubleshooting_injection":
        mode_tools = TROUBLESHOOTING_INJECTION_MODE_TOOLS
        logger.info("Using TROUBLESHOOTING_INJECTION mode tools (fault injection)")
    else:  # teaching_assistant mode (default)
        mode_tools = TEACHING_ASSISTANT_MODE_TOOLS
        logger.info("Using TEACHING_ASSISTANT mode tools (diagnostic tools only)")

    # Create pre_model_hook for automatic topology injection and trimming
    # Load system prompt based on copilot_mode configuration
    system_prompt = load_system_prompt(llm_config)
    pre_hook = create_pre_model_hook(
        system_prompt=system_prompt,
        get_topology_func=lambda s: s.get("topology_info"),
        get_llm_config_func=get_current_llm_config,
        get_tools_func=lambda: mode_tools,  # Pass mode-specific tools for
        # token estimation
    )

    # Create fresh model with tools for each LLM call
    logger.debug(
        "Creating model with tools: provider=%s, model=%s, mode=%s, tools=%d",
        llm_config.get("provider"),
        llm_config.get("model"),
        copilot_mode,
        len(mode_tools),
    )
    model_with_tools = _build_model_with_tools(mode_tools, llm_config)

    # Call pre_hook directly to prepare messages (topology injection +
    # trimming)
    # Note: LangGraph's pre_model_hook only works with prebuilt agents, not
    # custom StateGraph
    logger.debug("Calling pre_hook to prepare %d messages", len(messages))
    prepared_state = pre_hook({"messages": messages, "topology_info": topology_info})
    prepared_messages = prepared_state["messages"]
    logger.info("Messages prepared: %d → %d", len(messages), len(prepared_messages))

    # Invoke model with prepared messages
    response = model_with_tools.invoke(prepared_messages)

    # Add metadata with created_at timestamp to AI response
    if hasattr(response, "metadata"):
        existing_metadata = response.metadata or {}
        response.metadata = {
            **existing_metadata,
            "created_at": datetime.utcnow().isoformat(),
        }
    else:
        # LangChain messages should have metadata attribute, but defensive
        # fallback
        try:
            response.metadata = {"created_at": datetime.utcnow().isoformat()}
        except Exception:
            logger.warning("Could not add metadata to AI response")

    logger.info(
        "LLM call completed: tool_calls=%d",
        len(response.tool_calls) if hasattr(response, "tool_calls") else 0,
    )

    # Accumulate the turn's token cost (provider-reported usage preferred,
    # tiktoken estimate otherwise) so the next entry can enforce the budget
    turn_tokens = turn_tokens_used + _response_token_cost(response, prepared_messages)

    return {
        "messages": [response],
        "llm_calls": llm_calls_used + 1,
        "turn_tokens": turn_tokens,
        "topology_info": topology_info,
        "session_id": state.get("session_id"),
    }


def _build_title_model(llm_config: dict | None) -> Any:
    """
    Build the lightweight title generation model.

    Test seam, same purpose as _build_model_with_tools.
    """
    return create_title_model(llm_config=llm_config)


# Define generate title node
def generate_title(state: MessagesState, config: RunnableConfig | None = None) -> dict:
    """
    Generate a conversation title using a lightweight assistant LLM
    (title_model). This node is only executed when no title has been set yet
    (first round only).
    """

    # Get llm_config from request-scoped context variable
    llm_config = get_current_llm_config()

    if not llm_config:
        logger.error("LLM config not found in context, cannot generate title")
        return {"conversation_title": UNTITLED_SESSION_FALLBACK, "session_id": state.get("session_id")}

    # Only generate a title if it hasn't been set yet
    current_title = state.get("conversation_title")
    if current_title in [None, "New Conversation"]:
        logger.debug("Title generation triggered for session")
        messages = state["messages"]

        # Load title prompt from external repository
        title_prompt = get_prompt("title")
        if not title_prompt:
            logger.error("Title prompt not found in external repository")
            return {"conversation_title": UNTITLED_SESSION_FALLBACK, "session_id": state.get("session_id")}

        # Build the prompt for title generation
        title_prompt_messages = [
            SystemMessage(content=title_prompt),
            messages[0],  # User's first message
            messages[-1],  # Assistant's final response in this turn
        ]

        # Call the title generation model (create fresh instance for each call)
        try:
            title_model = _build_title_model(llm_config)
            response = title_model.invoke(
                title_prompt_messages,
                config={"configurable": {"foo_temperature": 1.0}},
            )
            raw_content = response.content

            new_title = raw_content.strip()

            # Validate the generated title
            if not new_title or len(new_title) < 3:
                raise ValueError(f"Generated title too short or empty: '{new_title}'")

            if new_title in [
                "New Conversation",
                "Untitled Session",
                "GNS3 Session",
            ]:
                raise ValueError(f"Generated title is a default value: '{new_title}'")

            # Safety: truncate long titles and avoid line breaks
            if len(new_title) > TITLE_MAX_LENGTH:
                new_title = new_title[: TITLE_MAX_LENGTH - 2] + "..."

            # Remove unwanted characters
            new_title = new_title.replace("\n", " ").replace('"', "").replace("'", "")

            logger.debug("Generated new title: %s", new_title)
            return {"conversation_title": new_title, "session_id": state.get("session_id")}

        except Exception as e:
            logger.error(f"Title generation failed: {e}, using fallback")

            # Improved fallback: Use user's first message content
            if messages and len(messages) > 0:
                first_message = messages[0]
                if hasattr(first_message, "content"):
                    fallback_title = first_message.content[:30].strip()
                    # Remove newlines and extra spaces
                    fallback_title = fallback_title.replace("\n", " ").strip()
                    # Collapse multiple spaces
                    while "  " in fallback_title:
                        fallback_title = fallback_title.replace("  ", " ")

                    # Truncate if needed
                    if len(fallback_title) > 28:
                        fallback_title = fallback_title[:28] + ".."

                    if fallback_title:
                        logger.info(
                            "Using fallback title from user message: '%s'",
                            fallback_title,
                        )
                        return {"conversation_title": fallback_title, "session_id": state.get("session_id")}

            # Final fallback
            logger.info(
                "Using final fallback title: '%s'",
                UNTITLED_SESSION_FALLBACK,
            )
            return {"conversation_title": UNTITLED_SESSION_FALLBACK, "session_id": state.get("session_id")}

    # Title already exists → no update needed
    return {}


# Define tool node
def tool_node(state: dict, config: RunnableConfig | None = None):
    """Performs the tool call"""

    tool_calls = state["messages"][-1].tool_calls
    logger.debug("Tool node invoked: tool_calls=%d", len(tool_calls))

    result = []
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        logger.debug("Executing tool: %s with args: %s", tool_name, tool_call["args"])
        tool = tools_by_name[tool_name]
        try:
            observation = tool.invoke(tool_call["args"])
            logger.debug(
                "Tool %s completed: output_length=%d",
                tool_name,
                len(str(observation)) if observation else 0,
            )
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e, exc_info=True)
            observation = f"Error: {e!s}"

        # Serialize observation to JSON string if it's not already a string
        # This ensures ToolMessage.content is always JSON format, not Python
        # str()
        observation_obj = observation
        if not isinstance(observation, str):
            observation = json.dumps(observation, ensure_ascii=False, indent=2)

        # Phase 2 (evidence externalization): large outputs go to the
        # evidence store; the ToolMessage carries a bounded view with an
        # evidence id the model retrieves through get_evidence. Small
        # outputs pass through unchanged.
        observation = externalize_tool_output(
            tool_name=tool_name,
            serialized=observation,
            observation=observation_obj,
            thread_id=state.get("session_id"),
            tool_call_id=tool_call["id"],
        )

        # Create ToolMessage with metadata including created_at
        tool_msg = ToolMessage(
            content=observation,
            tool_call_id=tool_call["id"],
            name=tool_call["name"],
            metadata={"created_at": datetime.utcnow().isoformat()},
        )
        result.append(tool_msg)

    return {"messages": result, "session_id": state.get("session_id")}


# Abort handler node - provides tool results when aborting
def abort_handler_node(state: dict) -> dict:
    """
    Handles abort by providing tool result messages for pending tool_calls.
    This ensures message history consistency and prevents checkpoint corruption.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"session_id": state.get("session_id")}

    last_message = messages[-1]
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {"session_id": state.get("session_id")}

    result = []
    for tool_call in last_message.tool_calls:
        tool_msg = ToolMessage(
            content=json.dumps(
                {
                    "status": "aborted",
                    "message": "Tool execution was aborted by user",
                    "tool_call_id": tool_call["id"],
                }
            ),
            tool_call_id=tool_call["id"],
            name=tool_call["name"],
            metadata={"created_at": datetime.utcnow().isoformat(), "aborted": True},
        )
        result.append(tool_msg)

    logger.info("Abort handler: generated %d aborted tool messages", len(result))
    return {"messages": result, "session_id": state.get("session_id")}


# Routing logic after the LLM node
def should_continue(
    state: MessagesState,
) -> Literal["tool_node", "title_generator_node", "abort_handler_node", END]:
    """
    Determine the next step after the LLM has produced a response.

    - If abort flag is set → end the conversation
    - If the LLM requested any tool calls → route to tool_node
    - If this is the first complete turn (llm_calls == 1) and no title
      exists → generate a title
    - Otherwise → conversation is complete, go to END
    """
    # Check abort flag first
    session_id = state.get("session_id")
    if session_id and check_abort_flag(session_id):
        last_message = state["messages"][-1]
        # If there's a tool_calls message, we need to handle it properly
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "abort_handler_node"
        return END

    last_message = state["messages"][-1]
    current_title = state.get("conversation_title")

    # LLM requested one or more tool executions
    # Defensive getattr: when llm_call returns early (for example with no
    # llm_config), the last message is still the HumanMessage, which has no
    # tool_calls attribute
    if getattr(last_message, "tool_calls", None):
        return "tool_node"

    # First full interaction completed and title not yet generated
    if current_title in [None, "New Conversation"]:
        return "title_generator_node"

    # Normal completion (multi-turn conversation or title already exists)
    return END


# Routing logic after the tool node, Check remaining_steps
def recursion_limit_continue(state: MessagesState) -> Literal["llm_call", END]:
    """
    Routing logic after tool execution to prevent infinite recursion.

    Determines whether to continue with another LLM call or end the
    conversation based on remaining steps and message type.

    Args:
        state: Current conversation state with messages and remaining steps

    Returns:
        "llm_call" to continue processing, END to terminate conversation

    Logic:
        - If abort flag is set → end the conversation
        - If the last message is ToolMessage and steps >= 4: continue to LLM
        - Otherwise: end the conversation to prevent infinite loops
    """
    # Check abort flag first
    session_id = state.get("session_id")
    if session_id and check_abort_flag(session_id):
        return END

    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage):
        if state["remaining_steps"] < 4:
            return END
        return "llm_call"

    return END


# Build and compile the agent
# Build workflow
agent_builder = StateGraph(MessagesState)

# Add nodes
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_node("title_generator_node", generate_title)
agent_builder.add_node("abort_handler_node", abort_handler_node)

# Add edges to connect nodes
agent_builder.add_edge(START, "llm_call")
# Conditional routing after LLM response
# Determines the next step based on whether LLM needs to call tools or
# generate title
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "tool_node": "tool_node",  # Route to tool execution if LLM requested
        # tools
        "title_generator_node": "title_generator_node",  # Generate title on
        # first interaction
        "abort_handler_node": "abort_handler_node",  # Handle abort with tool calls
        END: END,  # End conversation if no tools needed
    },
)
# Conditional routing after tool execution
# Prevents infinite recursion by checking remaining steps before continuing
agent_builder.add_conditional_edges(
    "tool_node",
    recursion_limit_continue,
    {
        "llm_call": "llm_call",  # Continue to LLM if tools executed and steps
        # remain
        END: END,  # End conversation to prevent infinite loops
    },
)

agent_builder.add_edge("title_generator_node", END)
agent_builder.add_edge("abort_handler_node", END)
