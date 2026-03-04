# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of GNS3-Copilot.
#
# GNS3-Copilot is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# GNS3-Copilot is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details.
#
# You should have received a copy of the GNU Affero General Public License along
# with GNS3-Copilot. If not, see <https://www.gnu.org/licenses/>.

# mypy: ignore-errors

"""
GNS3 Network Automation Assistant

This module implements an AI-powered assistant for GNS3 network automation and management.
It uses LangChain for agent orchestration and DeepSeek LLM for natural language processing.
The assistant provides comprehensive GNS3 topology management capabilities including:
- Reading and analyzing GNS3 project topologies
- Creating and managing network nodes and links
- Executing network configuration and display commands on multiple devices
- Managing VPCS (Virtual PC Simulator) commands
- Starting and controlling GNS3 nodes

The assistant integrates with various tools to provide a complete network automation
solution for GNS3 environments.
"""

import operator
from typing import Annotated, Literal

from langchain.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict

import logging

from gns3_copilot.agent.model_factory import (
    create_base_model_with_tools,
    create_title_model,
)
from gns3_copilot.gns3_client import GNS3TopologyTool
from gns3_copilot.prompts import TITLE_PROMPT, load_system_prompt
import sys
from pathlib import Path
# Add backend to path for prompt_manager
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))
from gns3_copilot.tools_v2 import (
    ExecuteMultipleDeviceCommands,
    GNS3CreateNodeTool,
    GNS3LinkTool,
    GNS3StartNodeTool,
    GNS3TemplateTool,
    VPCSMultiCommands,
)

# Set up logger for GNS3-Copilot
logger = logging.getLogger(__name__)

# Note: LLM model configuration is now managed by the new llm_model_configs system.
# The model_factory module handles model creation with configuration from the database.

# Define the available tools for the agent
tools = [
    GNS3TemplateTool(),  # Get GNS3 node templates
    GNS3TopologyTool(),  # Read GNS3 topology information
    GNS3CreateNodeTool(),  # Create new nodes in GNS3
    GNS3LinkTool(),  # Create links between nodes
    GNS3StartNodeTool(),  # Start GNS3 nodes
    ExecuteMultipleDeviceCommands(),  # Execute show/display/debug commands on multiple devices (READ-ONLY)
    VPCSMultiCommands(),  # Execute VPCS commands on multiple devices
]
# Augment the LLM with tools
tools_by_name = {tool.name: tool for tool in tools}
# Model with tools will be created dynamically by the factory when needed

# Log application startup
logger.info("GNS3-Copilot application starting up")

# Constants for conversation title management
DEFAULT_CONVERSATION_TITLE = "New Conversation"
UNTITLED_SESSION_FALLBACK = "Untitled Session"
TITLE_MAX_LENGTH = 40


# Define state
class MessagesState(TypedDict):
    """
    GNS3-Copilot conversation state management class.

    Maintains the conversation state for the LangGraph workflow, including message history,
    call counters, and session titles for comprehensive dialogue management.

    Attributes:
        messages: List of conversation messages with cumulative updates using operator.add
        llm_calls: Counter for tracking the number of LLM invocations
        remaining_steps: Is automatically managed by LangGraph's RemainingSteps to track and limit recursion depth.
        conversation_title: Optional conversation title for session identification and management
        topology_info: Dictionary containing GNS3 project topology information
    """

    messages: Annotated[list[AnyMessage], operator.add]

    llm_calls: int

    remaining_steps: RemainingSteps

    # Optional conversation title
    conversation_title: str | None

    # Store the complete tuple selected by the user
    selected_project: tuple[str, str, int, int, str] | None

    # Store GNS3 topology information
    topology_info: dict | None


# Define llm call  node
def llm_call(state: dict, config: dict = None):
    """LLM decides whether to call a tool or not"""

    # Extract user authentication info from LangGraph config
    configurable = config.get("configurable", {}) if config else {}
    user_id = configurable.get("user_id")
    jwt_token = configurable.get("jwt_token")

    # Defensive check: skip LLM call if no user messages
    messages = state.get("messages", [])
    if not messages or len(messages) == 0:
        return {
            "messages": [],
            "llm_calls": state.get("llm_calls", 0),
            "topology_info": None,
        }

    # Get mode from state (if provided), default to "text"
    mode = state.get("mode", "text")

    # Get system prompt based on ENGLISH_LEVEL configuration
    # load_system_prompt() will select base_prompt.py or english_level_prompt_a1-c2.py
    # based on the ENGLISH_LEVEL environment variable
    current_prompt = load_system_prompt()

    # print(current_prompt)

    # Get the previously stored project tuple
    selected_p = state.get("selected_project")

    # Construct context messages
    context_messages = []
    topology_info = None

    if selected_p:
        # Convert tuple information to natural language to tell LLM which project user selected
        project_info = (
            "User has selected project: "
            f"Project_Name={selected_p[0]}, "
            f"Project_ID={selected_p[1]}, "
            f"Device_Number={selected_p[2]}, "
            f"Link_Number={selected_p[3]}, "
            f"Status={selected_p[4]}"
        )

        # Try to retrieve topology information
        try:
            topology_tool = GNS3TopologyTool()
            topology = topology_tool._run(project_id=selected_p[1])

            if topology and "error" not in topology:
                topology_info = topology
                logger.info(
                    "Successfully retrieved topology for project: %s", selected_p[0]
                )

                # Convert topology dict to string for LLM consumption
                topology_context = str(topology)
                context_messages.append(
                    SystemMessage(
                        content=f"Current Context: {project_info}\n\nTopology:\n{topology_context}"
                    )
                )
            else:
                logger.warning(
                    "Failed to retrieve topology: %s",
                    topology.get("error", "Unknown error"),
                )
                context_messages.append(
                    SystemMessage(content=f"Current Context: {project_info}")
                )
        except Exception as e:
            logger.warning("Error retrieving topology: %s", e)
            context_messages.append(
                SystemMessage(content=f"Current Context: {project_info}")
            )

    # Merge message lists
    full_messages = (
        [SystemMessage(content=current_prompt)] + context_messages + state["messages"]
    )
    # print(full_messages)

    # Create fresh model with tools for each LLM call
    # This ensures configuration changes take effect immediately
    # Pass user_id and jwt_token for per-user LLM config and API authentication
    model_with_tools = create_base_model_with_tools(
        tools,
        user_id=user_id,
        jwt_token=jwt_token
    )

    # Store jwt_token in state for Tools to use when calling GNS3 API
    return {
        "messages": [model_with_tools.invoke(full_messages)],
        "llm_calls": state.get("llm_calls", 0) + 1,
        "topology_info": topology_info,
        "jwt_token": jwt_token,
    }


# Define generate title node
def generate_title(state: MessagesState, config: dict = None) -> dict:
    """
    Generate a conversation title using a lightweight assistant LLM (title_model).
    This node is only executed when no title has been set yet (first round only).
    """

    # Extract user authentication info from LangGraph config
    configurable = config.get("configurable", {}) if config else {}
    user_id = configurable.get("user_id")
    jwt_token = configurable.get("jwt_token")

    # Only generate a title if it hasn't been set yet
    current_title = state.get("conversation_title")
    if current_title in [None, "New Conversation"]:
        logger.info("Title generation triggered for session")
        messages = state["messages"]

        # Build the prompt for title generation
        title_prompt_messages = [
            SystemMessage(content=TITLE_PROMPT),
            messages[0],  # User's first message
            messages[-1],  # Assistant's final response in this turn
        ]

        # Call the title generation model (create fresh instance for each call)
        try:
            # Create fresh title model instance from current env configuration
            # Pass user_id and jwt_token for per-user LLM config
            title_model = create_title_model(user_id=user_id, jwt_token=jwt_token)
            response = title_model.invoke(
                title_prompt_messages, config={"configurable": {"foo_temperature": 1.0}}
            )
            raw_content = response.content

            new_title = raw_content.strip()

            # Validate the generated title
            if not new_title or len(new_title) < 3:
                raise ValueError(f"Generated title too short or empty: '{new_title}'")

            if new_title in ["New Conversation", "Untitled Session", "GNS3 Session"]:
                raise ValueError(f"Generated title is a default value: '{new_title}'")

            # Safety: truncate long titles and avoid line breaks
            if len(new_title) > TITLE_MAX_LENGTH:
                new_title = new_title[:TITLE_MAX_LENGTH - 2] + "..."

            # Remove unwanted characters
            new_title = new_title.replace("\n", " ").replace('"', "").replace("'", "")

            logger.info("Generated new title: %s", new_title)
            return {"conversation_title": new_title}

        except Exception as e:
            logger.error(f"Title generation failed: {e}, using fallback")

            # Improved fallback: Use user's first message content
            if messages and len(messages) > 0:
                first_message = messages[0]
                if hasattr(first_message, 'content'):
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
                        logger.info(f"Using fallback title from user message: '{fallback_title}'")
                        return {"conversation_title": fallback_title}

            # Final fallback
            logger.info(f"Using final fallback title: '{UNTITLED_SESSION_FALLBACK}'")
            return {"conversation_title": UNTITLED_SESSION_FALLBACK}

    # Title already exists → no update needed
    return {}


# Define tool node
def tool_node(state: dict):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(
            content=observation,
            tool_call_id=tool_call["id"],
            name=tool_call["name"]
        ))
    return {"messages": result}


# Routing logic after the LLM node
def should_continue(
    state: MessagesState,
) -> Literal["tool_node", "title_generator_node", END]:
    """
    Determine the next step after the LLM has produced a response.

    - If the LLM requested any tool calls → route to tool_node
    - If this is the first complete turn (llm_calls == 1) and no title exists → generate a title
    - Otherwise → conversation is complete, go to END
    """
    last_message = state["messages"][-1]
    llm_calls = state.get("llm_calls", 0)
    current_title = state.get("conversation_title")

    # LLM requested one or more tool executions
    if last_message.tool_calls:
        return "tool_node"

    # First full interaction completed and title not yet generated
    if current_title in [None, "New Conversation"]:
        logger.info(
            "First turn finished, no title yet → routing to 'title_generator_node'"
        )
        return "title_generator_node"

    # Normal completion (multi-turn conversation or title already exists)
    return END


# Routing logic after the tool node, Check remaining_steps
def recursion_limit_continue(state: MessagesState) -> Literal["llm_call", END]:
    """
    Routing logic after tool execution to prevent infinite recursion.

    Determines whether to continue with another LLM call or end the conversation
    based on remaining steps and message type.

    Args:
        state: Current conversation state with messages and remaining steps

    Returns:
        "llm_call" to continue processing, END to terminate conversation

    Logic:
        - If the last message is ToolMessage and steps >= 4: continue to LLM
        - Otherwise: end the conversation to prevent infinite loops
    """
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

# Add edges to connect nodes
agent_builder.add_edge(START, "llm_call")
# Conditional routing after LLM response
# Determines the next step based on whether LLM needs to call tools or generate title
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "tool_node": "tool_node",  # Route to tool execution if LLM requested tools
        "title_generator_node": "title_generator_node",  # Generate title on first interaction
        END: END,  # End conversation if no tools needed
    },
)
# Conditional routing after tool execution
# Prevents infinite recursion by checking remaining steps before continuing
agent_builder.add_conditional_edges(
    "tool_node",
    recursion_limit_continue,
    {
        "llm_call": "llm_call",  # Continue to LLM if tools executed and steps remain
        END: END,  # End conversation to prevent infinite loops
    },
)

agent_builder.add_edge("title_generator_node", END)
