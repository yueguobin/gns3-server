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
# Copyright (C) 2025 Guobin Yue
# Author: Guobin Yue
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""
Context Window Manager for GNS3-Copilot

This module provides intelligent context window management for LLM models,
including:
- Model-specific context window limits
- Accurate token counting using tiktoken
- Message trimming strategies (conservative/balanced/aggressive)
- System message preservation
- Tool definition token estimation
- Template variable injection for topology info

"""

import json
import logging
from typing import Any
from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Context strategy ratios
CONTEXT_STRATEGY_RATIOS = {
    "conservative": 0.60,  # 60% for input, 40% reserved for output
    "balanced": 0.75,  # 75% for input, 25% reserved for output
    "aggressive": 0.85,  # 85% for input, 15% reserved for output
}

DEFAULT_CONTEXT_STRATEGY = "balanced"

# ============================================================================
# Token Counting - Using tiktoken for accuracy
# ============================================================================

# Global tiktoken encoding cache (lazy loading)
_tiktoken_encoding = None


def _get_tiktoken_encoding():
    """
    Get tiktoken encoding instance (cached).

    Uses cl100k_base encoding (GPT-4) which is a good approximation
    for most modern LLMs including OpenAI, Anthropic, and DeepSeek.

    Returns:
        Encoding object

    Raises:
        ImportError: If tiktoken is not installed
    """
    global _tiktoken_encoding
    if _tiktoken_encoding is None:
        try:
            import tiktoken

            _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
            logger.debug("Using tiktoken (cl100k_base) for accurate token counting")
        except ImportError:
            raise ImportError(
                "tiktoken is required for accurate token counting. "
                "Please install it with: pip install tiktoken>=0.8.0"
            )
    return _tiktoken_encoding


def count_tokens_accurately(text: str) -> int:
    """
    Count tokens in text accurately using tiktoken.

    Args:
        text: The text to count tokens for

    Returns:
        Number of tokens

    Raises:
        ImportError: If tiktoken is not installed
    """
    if not text:
        return 0

    encoding = _get_tiktoken_encoding()
    try:
        return len(encoding.encode(text))
    except Exception as e:
        logger.error("tiktoken encoding failed: %s", e)
        raise


def count_messages_tokens(messages: list[Any]) -> int:
    """
    Count total tokens in a list of messages accurately.

    Args:
        messages: List of LangChain messages

    Returns:
        Total token count

    Raises:
        ImportError: If tiktoken is not installed
    """
    total = 0
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            # Handle both string and complex content
            content = str(msg.content)
            total += count_tokens_accurately(content)
    return total


# ============================================================================
# Tool Definition Token Estimation
# ============================================================================


def estimate_tool_tokens(tools: list[Any]) -> int:
    """
    Estimate the token count of tool definitions.

    When tools are bound to an LLM, their schemas (name, description, parameters)
    are converted to JSON and sent to the LLM. This function estimates how many
    tokens those definitions will consume.

    Args:
        tools: List of LangChain BaseTool instances

    Returns:
        Estimated token count for all tool definitions

    Raises:
        ImportError: If tiktoken is not installed
    """
    if not tools:
        return 0

    total_tokens = 0
    encoding = _get_tiktoken_encoding()

    for tool in tools:
        try:
            # Build tool schema as it would be sent to LLM
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description if hasattr(tool, "description") else "",
                },
            }

            # Add parameters schema if available
            if hasattr(tool, "args_schema") and tool.args_schema:
                try:
                    tool_schema["function"]["parameters"] = tool.args_schema.schema()
                except Exception:
                    # If schema generation fails, use empty object
                    tool_schema["function"]["parameters"] = {"type": "object"}

            # Count tokens in the schema
            schema_str = json.dumps(tool_schema, ensure_ascii=False)
            tool_tokens = len(encoding.encode(schema_str))
            total_tokens += tool_tokens

            logger.debug("Tool '%s': ~%d tokens (schema size: %d chars)", tool.name, tool_tokens, len(schema_str))

        except Exception as e:
            logger.error("Failed to estimate tokens for tool '%s': %s", tool.name, e)
            raise

    logger.info("Tool definitions estimated at ~%d total tokens (%d tools)", total_tokens, len(tools))
    return total_tokens


# ============================================================================
# Model Context Limits
# ============================================================================

# NOTE: Built-in model context limits have been removed.
# Model providers frequently update context limits, and maintaining this list is not sustainable.
# Users MUST configure context_limit explicitly in their LLM model configurations.
#
# For reference, common model context limits as of 2025:
# - OpenAI GPT-4o: 128K tokens
# - OpenAI GPT-4 Turbo: 128K tokens
# - OpenAI GPT-3.5 Turbo: 16K tokens
# - Anthropic Claude 3.5 Sonnet: 200K tokens
# - Google Gemini 1.5 Pro: 2.8M tokens
# - DeepSeek Chat: 128K tokens
#
# Always verify current limits from official provider documentation.


def get_model_context_limit(model_name: str, llm_config: dict[str, Any] | None = None) -> int:
    """
    Get the context window limit for a given model.

    IMPORTANT: context_limit MUST be provided in llm_config.
    Model providers frequently update context limits, so built-in defaults are NOT used.
    Users must configure this value explicitly.

    NOTE: context_limit unit is K tokens (1 K = 1000 tokens).
    Example: 128 means 128K = 128,000 tokens.

    Args:
        model_name: Name of the model (e.g., "gpt-4o", "deepseek-chat")
        llm_config: LLM config dict from database (must contain context_limit in K tokens)

    Returns:
        int: Maximum context window size in tokens (actual number, not K)

    Raises:
        ValueError: If context_limit is not provided or invalid
    """
    # Check database config for context_limit
    if llm_config and "context_limit" in llm_config:
        db_limit_k = llm_config["context_limit"]
        if isinstance(db_limit_k, int) and db_limit_k > 0:
            # Convert K tokens to actual tokens
            actual_tokens = db_limit_k * 1000
            logger.debug(
                "Using database config context limit: %dK tokens (%d tokens) for model '%s'",
                db_limit_k,
                actual_tokens,
                model_name,
            )
            return actual_tokens
        else:
            raise ValueError(
                f"Invalid context_limit in database config: {db_limit_k} "
                f"(type={type(db_limit_k).__name__}, expected positive integer in K tokens)"
            )

    # No context_limit provided - this is a configuration error
    raise ValueError(
        f"context_limit is required but not provided for model '{model_name}'. "
        f"Please configure context_limit in your LLM model configuration (unit: K tokens). "
        f"Example: 128 means 128K = 128,000 tokens. "
        f"Refer to the model provider's documentation for the current context window size."
    )


def calculate_max_tokens(
    model_limit: int, strategy: Literal["conservative", "balanced", "aggressive"] = DEFAULT_CONTEXT_STRATEGY
) -> int:
    """
    Calculate the maximum tokens to use, reserving space for output.

    Args:
        model_limit: Model's context window limit
        strategy: How aggressively to use the context window
            - "conservative": Use 60% of limit (safer, more reserved for output)
            - "balanced": Use 75% of limit (default)
            - "aggressive": Use 85% of limit (maximize input, minimal output reserve)

    Returns:
        int: Maximum tokens for input messages
    """
    ratio = CONTEXT_STRATEGY_RATIOS.get(strategy, CONTEXT_STRATEGY_RATIOS[DEFAULT_CONTEXT_STRATEGY])
    max_tokens = int(model_limit * ratio)

    logger.debug("Context limit: model=%d, strategy=%s, usable=%d tokens", model_limit, strategy, max_tokens)

    return max_tokens


# ============================================================================
# Message Trimming
# ============================================================================


def trim_messages_for_context(
    messages: list[Any],
    model_name: str,
    llm_config: dict[str, Any] | None = None,
    strategy: Literal["conservative", "balanced", "aggressive"] = DEFAULT_CONTEXT_STRATEGY,
    preserve_system: bool = True,
    tool_tokens: int = 0,
) -> list[Any]:
    """
    Trim messages to fit within model's context window.

    This function uses tiktoken for accurate token counting and intelligently
    reduces message history while preserving conversation flow.

    IMPORTANT: Tool definitions are sent separately by LangChain and count towards
    the context limit. This function accounts for tool tokens when making
    trimming decisions.

    Args:
        messages: List of LangChain messages (HumanMessage, AIMessage, etc.)
        model_name: Name of the LLM model being used
        llm_config: Optional LLM config dict from database (may contain context_limit)
        strategy: How aggressively to use the context window
        preserve_system: Whether to always preserve system messages
        tool_tokens: Token count for tool definitions (these are sent separately by LangChain)

    Returns:
        list: Trimmed list of messages that fit within context limit

    Examples:
        >>> messages = [HumanMessage("Hello"), AIMessage("Hi there!")]
        >>> trimmed = trim_messages_for_context(messages, "gpt-4o", tool_tokens=1000)
        >>> len(trimmed) <= len(messages)
        True
    """
    if not messages:
        return messages

    # Get model's context limit (from database config)
    model_limit = get_model_context_limit(model_name, llm_config)

    # Calculate usable tokens (reserve space for output)
    max_tokens = calculate_max_tokens(model_limit, strategy)

    # Account for tool tokens - these are sent separately by LangChain
    # and count towards the context limit
    available_for_messages = max_tokens - tool_tokens

    if available_for_messages < 0:
        logger.warning(
            "Tool definitions (%d tokens) exceed input budget (%d tokens). "
            "Consider reducing context_limit or using fewer tools.",
            tool_tokens,
            max_tokens,
        )
        available_for_messages = 0

    # Check if trimming is needed
    current_tokens = count_messages_tokens(messages)

    if current_tokens <= available_for_messages:
        logger.debug(
            "Messages fit in context: %d / %d tokens (available: %d, tools: %d)",
            current_tokens,
            max_tokens,
            available_for_messages,
            tool_tokens,
        )
        return messages

    logger.info(
        "Trimming messages: %d → %d tokens (budget: %d, tools: %d)",
        current_tokens,
        available_for_messages,
        max_tokens,
        tool_tokens,
    )

    # Manually separate and trim to ensure system messages are preserved
    # This is more reliable than using trim_messages with include_system
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

    # Calculate tokens for system messages (these will always be preserved)
    system_tokens = count_messages_tokens(system_msgs)

    # Calculate available tokens for non-system messages (after tools and system)
    available_for_other = available_for_messages - system_tokens

    if available_for_other <= 0:
        # Not enough space for system messages - keep only system messages
        logger.warning(
            "System messages (%d tokens) exceed available space (%d tokens), truncating to system only",
            system_tokens,
            available_for_messages,
        )
        return system_msgs[:1] if system_msgs else messages[-1:]

    # Trim non-system messages to fit available space
    trimmed_other = _trim_to_token_limit(other_msgs, available_for_other)

    # Combine system messages with trimmed conversation
    trimmed = system_msgs + trimmed_other

    logger.info(
        "Trimmed %d → %d messages (system: %d, history: %d → %d)",
        len(messages),
        len(trimmed),
        len(system_msgs),
        len(other_msgs),
        len(trimmed_other),
    )

    return trimmed


def _trim_to_token_limit(messages: list[Any], max_tokens: int) -> list[Any]:
    """
    Trim messages to fit within token limit using tiktoken.

    Intelligently removes oldest message groups while preserving:
    - AIMessage + ToolMessage pairs (must stay together)
    - Conversation coherence

    Always keeps at least the most recent message.

    Args:
        messages: List of messages to trim
        max_tokens: Maximum tokens allowed

    Returns:
        Trimmed list of messages
    """
    if not messages:
        return messages

    current_tokens = count_messages_tokens(messages)

    if current_tokens <= max_tokens:
        return messages

    # Build message groups to preserve AIMessage + ToolMessage pairs
    groups = _build_message_groups(messages)

    # Remove oldest groups until under token limit
    trimmed_groups = list(groups)
    while trimmed_groups and _count_groups_tokens(trimmed_groups) > max_tokens:
        # Always remove from beginning (oldest)
        trimmed_groups.pop(0)

    # Flatten groups back to message list
    trimmed = []
    for group in trimmed_groups:
        trimmed.extend(group)

    # Ensure at least one message remains
    if not trimmed and messages:
        # Return only the last message if nothing else fits
        trimmed = [messages[-1]]

    logger.debug(
        "Trimmed messages: removed %d groups, %d messages remain, %d → %d tokens",
        len(groups) - len(trimmed_groups),
        len(trimmed),
        current_tokens,
        _count_groups_tokens(trimmed_groups),
    )

    return trimmed


def _build_message_groups(messages: list[Any]) -> list[list[Any]]:
    """
    Build message groups where AIMessage + ToolMessage pairs stay together.

    Each group is either:
    - A standalone message (HumanMessage, SystemMessage)
    - An AIMessage with its following ToolMessages (must stay together)

    Args:
        messages: List of messages

    Returns:
        List of message groups
    """
    groups = []
    i = 0

    while i < len(messages):
        msg = messages[i]

        # If AIMessage with tool_calls, group it with all following ToolMessages
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            group = [msg]
            i += 1

            # Collect all following ToolMessages that match these tool_calls
            tool_call_ids = {tc["id"] for tc in msg.tool_calls}

            while i < len(messages):
                next_msg = messages[i]
                if isinstance(next_msg, ToolMessage):
                    # Check if this ToolMessage belongs to current AIMessage
                    if hasattr(next_msg, "tool_call_id") and next_msg.tool_call_id in tool_call_ids:
                        group.append(next_msg)
                        i += 1
                    else:
                        # ToolMessage belongs to a different AIMessage, stop
                        break
                else:
                    # Not a ToolMessage, stop grouping
                    break

            groups.append(group)
        else:
            # Standalone message (no tool_calls)
            groups.append([msg])
            i += 1

    return groups


def _count_groups_tokens(groups: list[list[Any]]) -> int:
    """Count total tokens in all groups."""
    total = 0
    for group in groups:
        for msg in group:
            if hasattr(msg, "content") and msg.content:
                total += count_tokens_accurately(str(msg.content))
    return total


# ============================================================================
# Token Usage Summary
# ============================================================================


def get_token_usage_summary(
    messages: list[Any],
    model_name: str,
    llm_config: dict[str, Any] | None = None,
    tool_tokens: int = 0,
) -> dict[str, Any]:
    """
    Get a summary of token usage for the given messages.

    Args:
        messages: List of LangChain messages
        model_name: Name of the LLM model
        llm_config: Optional LLM config dict from database (may contain context_limit in K tokens)
        tool_tokens: Optional token count for tool definitions

    Returns:
        dict: Token usage summary including:
            - estimated_tokens: Estimated total tokens (messages only)
            - tool_tokens: Token count for tool definitions
            - total_tokens: Sum of messages and tools
            - model_limit_k: Model's context window limit in K tokens
            - model_limit_tokens: Model's context window limit in actual tokens
            - usage_percentage: Percentage of context used (excluding tools)
            - total_usage_percentage: Percentage including tools
            - message_count: Number of messages
            - needs_trimming: Whether messages exceed 80% of limit
    """
    try:
        estimated_tokens = count_messages_tokens(messages)
    except Exception as e:
        logger.warning("Failed to count tokens: %s", e)
        estimated_tokens = 0

    model_limit_tokens = get_model_context_limit(model_name, llm_config)
    model_limit_k = model_limit_tokens // 1000
    usage_percentage = (estimated_tokens / model_limit_tokens * 100) if model_limit_tokens > 0 else 0
    total_tokens = estimated_tokens + tool_tokens
    total_usage_percentage = (total_tokens / model_limit_tokens * 100) if model_limit_tokens > 0 else 0

    return {
        "estimated_tokens": estimated_tokens,
        "tool_tokens": tool_tokens,
        "total_tokens": total_tokens,
        "model_limit_k": model_limit_k,
        "model_limit_tokens": model_limit_tokens,
        "usage_percentage": round(usage_percentage, 2),
        "total_usage_percentage": round(total_usage_percentage, 2),
        "message_count": len(messages),
        "needs_trimming": usage_percentage > 80,
    }


# ============================================================================
# Main Entry Point - Context Preparation with Template Injection
# ============================================================================


def prepare_context_messages(
    state_messages: list[Any],
    system_prompt: str,
    topology_context: str | None,
    model_name: str,
    llm_config: dict[str, Any] | None = None,
    tools: list[Any] | None = None,
) -> list[Any]:
    """
    Prepare full context messages for LLM call with automatic trimming.

    This is the main entry point for GNS3-Copilot to prepare messages
    before calling the LLM. It injects topology info into the system prompt
    using template variables and performs intelligent message trimming.

    Template Variable Injection:
        The system_prompt must contain the {{topology_info}} placeholder.
        This function will replace it with actual topology information or
        a placeholder message if topology is not available.

    Args:
        state_messages: Message history from conversation state
        system_prompt: System prompt text (must contain {{topology_info}} placeholder)
        topology_context: Optional topology information string
        model_name: Name of the LLM model
        llm_config: Optional LLM config dict from database (may contain context_limit and context_strategy)
        tools: Optional list of LangChain tools (for token estimation)

    Returns:
        list: Prepared messages ready for LLM invocation

    Examples:
        >>> messages = prepare_context_messages(
        ...     state_messages=[HumanMessage("Help me")],
        ...     system_prompt="You are a helpful assistant\\n\\n{{topology_info}}",
        ...     topology_context=None,
        ...     model_name="gpt-4o"
        ... )
        >>> len(messages)
        2  # System message + Human message
    """
    # Step 1: Get trimming strategy from config
    trim_strategy = DEFAULT_CONTEXT_STRATEGY
    if llm_config and "context_strategy" in llm_config:
        strategy = llm_config["context_strategy"]
        if strategy in CONTEXT_STRATEGY_RATIOS:
            trim_strategy = strategy
            logger.debug("Using context_strategy from config: %s", trim_strategy)
        else:
            logger.warning("Invalid context_strategy '%s', using '%s'", strategy, DEFAULT_CONTEXT_STRATEGY)

    # Step 2: Estimate tool tokens (tools are sent with each LLM call)
    tool_tokens = estimate_tool_tokens(tools) if tools else 0

    # Step 3: Inject topology info into system prompt using template variable
    # The system_prompt contains {{topology_info}} placeholder
    if topology_context:
        topology_formatted = f"Current Topology:\n{topology_context}"
        formatted_prompt = system_prompt.replace("{{topology_info}}", topology_formatted)
    else:
        # If no topology, use placeholder
        formatted_prompt = system_prompt.replace("{{topology_info}}", "(No topology information available)")

    # Step 4: Calculate token breakdown
    system_prompt_tokens = count_tokens_accurately(system_prompt)
    topology_tokens = count_tokens_accurately(topology_formatted) if topology_context else 0
    formatted_tokens = count_tokens_accurately(formatted_prompt)

    # Step 5: Build context messages (single system message with topology injected)
    context_messages = [SystemMessage(content=formatted_prompt)]

    # Step 6: Calculate conversation history tokens
    history_tokens = count_messages_tokens(state_messages)

    # Step 7: Combine with conversation history
    full_messages = context_messages + state_messages

    # Step 8: Trim if needed
    trimmed_messages = trim_messages_for_context(
        full_messages,
        model_name=model_name,
        llm_config=llm_config,
        strategy=trim_strategy,
        preserve_system=True,  # Always keep system prompts
        tool_tokens=tool_tokens,  # Account for tool definitions
    )

    # Step 9: Recalculate after trimming
    trimmed_history_tokens = count_messages_tokens([m for m in trimmed_messages if not isinstance(m, SystemMessage)])

    # Step 10: Log summary with detailed breakdown
    model_limit_k = get_model_context_limit(model_name, llm_config) // 1000

    if trimmed_history_tokens < history_tokens:
        # Trimming happened
        logger.info(
            "Context prepared (trimmed): system=%d (base=%d + topology=%d) + history=%d→%d + tools=%d = %d total / %dK limit (%.1f%%), strategy=%s",
            formatted_tokens,
            system_prompt_tokens,
            topology_tokens,
            history_tokens,
            trimmed_history_tokens,
            tool_tokens,
            formatted_tokens + trimmed_history_tokens + tool_tokens,
            model_limit_k,
            ((formatted_tokens + trimmed_history_tokens) / (model_limit_k * 1000)) * 100,
            trim_strategy,
        )
    else:
        # No trimming
        logger.info(
            "Context prepared: system=%d (base=%d + topology=%d) + history=%d + tools=%d = %d total / %dK limit (%.1f%%), strategy=%s",
            formatted_tokens,
            system_prompt_tokens,
            topology_tokens,
            history_tokens,
            tool_tokens,
            formatted_tokens + history_tokens + tool_tokens,
            model_limit_k,
            (formatted_tokens / (model_limit_k * 1000)) * 100,
            trim_strategy,
        )

    return trimmed_messages


# ============================================================================
# Module Test
# ============================================================================

if __name__ == "__main__":
    # Simple test
    test_messages = [HumanMessage(f"Message {i}") for i in range(100)]

    # Test with mock llm_config
    mock_config = {"context_limit": 8, "context_strategy": "conservative"}

    result = prepare_context_messages(
        state_messages=test_messages,
        system_prompt="You are GNS3 Copilot.\n\n{{topology_info}}",
        topology_context='{"project_id": "test", "nodes": 5}',
        model_name="gpt-4o",
        llm_config=mock_config,
        tools=None,
    )

    print(f"Original: {len(test_messages)} messages")
    print(f"Trimmed: {len(result)} messages")
