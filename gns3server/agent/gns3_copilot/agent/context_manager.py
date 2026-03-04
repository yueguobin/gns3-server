# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Context Window Manager for GNS3-Copilot
#
# This module manages context window limits for different LLM models,
# implementing intelligent message trimming and token counting strategies.

"""
Context Window Manager for GNS3-Copilot

This module provides context window management for different LLM models,
including:
- Model-specific context window limits
- Token counting for messages
- Message trimming strategies
- System message preservation
"""

import logging
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import trim_messages

logger = logging.getLogger(__name__)


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


def get_model_context_limit(
    model_name: str,
    llm_config: dict[str, Any] | None = None
) -> int:
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
                db_limit_k, actual_tokens, model_name
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
    model_limit: int,
    strategy: Literal["conservative", "balanced", "aggressive"] = "balanced"
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
    ratios = {
        "conservative": 0.60,
        "balanced": 0.75,
        "aggressive": 0.85,
    }

    ratio = ratios.get(strategy, 0.75)
    max_tokens = int(model_limit * ratio)

    logger.debug(
        "Context limit: model=%d, strategy=%s, usable=%d tokens",
        model_limit, strategy, max_tokens
    )

    return max_tokens


def trim_messages_for_context(
    messages: list[Any],
    model_name: str,
    llm_config: dict[str, Any] | None = None,
    strategy: Literal["conservative", "balanced", "aggressive"] = "balanced",
    preserve_system: bool = True,
) -> list[Any]:
    """
    Trim messages to fit within model's context window.

    This function uses LangChain's trim_messages utility to intelligently
    reduce message history while preserving conversation flow.

    Args:
        messages: List of LangChain messages (HumanMessage, AIMessage, etc.)
        model_name: Name of the LLM model being used
        llm_config: Optional LLM config dict from database (may contain context_limit)
        strategy: How aggressively to use the context window
        preserve_system: Whether to always preserve system messages

    Returns:
        list: Trimmed list of messages that fit within context limit

    Examples:
        >>> messages = [HumanMessage("Hello"), AIMessage("Hi there!")]
        >>> trimmed = trim_messages_for_context(messages, "gpt-4o")
        >>> len(trimmed) <= len(messages)
        True
    """
    if not messages:
        return messages

    # Get model's context limit (from database or built-in defaults)
    model_limit = get_model_context_limit(model_name, llm_config)

    # Calculate usable tokens (reserve space for output)
    max_tokens = calculate_max_tokens(model_limit, strategy)

    # Check if trimming is needed
    try:
        from langchain_core.messages.utils import count_tokens_approximately

        # Estimate current token count
        current_tokens = count_tokens_approximately(messages)

        if current_tokens <= max_tokens:
            logger.debug(
                "Messages fit in context: %d / %d tokens",
                current_tokens, max_tokens
            )
            return messages

        logger.info(
            "Trimming messages: %d → %d tokens (model: %s)",
            current_tokens, max_tokens, model_name
        )

    except Exception as e:
        logger.warning("Failed to count tokens: %s, proceeding with trim", e)

    # Trim messages using LangChain's utility
    try:
        trimmed = trim_messages(
            messages,
            strategy="last",  # Keep most recent messages
            max_tokens=max_tokens,
            preserve_system=preserve_system,
            start_on="human",  # Ensure we start with a human message
            end_on=("human", "tool", "ai"),  # End on human/tool/ai messages
        )

        logger.info(
            "Trimmed %d → %d messages",
            len(messages), len(trimmed)
        )

        return trimmed

    except Exception as e:
        logger.error("Failed to trim messages: %s", e, exc_info=True)

        # Fallback: simple slicing (keep last N messages)
        # Estimate average tokens per message (~100 tokens)
        fallback_msg_count = max(1, max_tokens // 100)

        logger.warning(
            "Using fallback trimming: keeping last %d messages",
            fallback_msg_count
        )

        # Always preserve system messages
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        return system_msgs + other_msgs[-fallback_msg_count:]


def get_token_usage_summary(
    messages: list[Any],
    model_name: str,
    llm_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Get a summary of token usage for the given messages.

    Args:
        messages: List of LangChain messages
        model_name: Name of the LLM model
        llm_config: Optional LLM config dict from database (may contain context_limit in K tokens)

    Returns:
        dict: Token usage summary including:
            - estimated_tokens: Estimated total tokens
            - model_limit_k: Model's context window limit in K tokens
            - model_limit_tokens: Model's context window limit in actual tokens
            - usage_percentage: Percentage of context used
            - message_count: Number of messages
            - needs_trimming: Whether messages exceed 80% of limit
    """
    try:
        from langchain_core.messages.utils import count_tokens_approximately

        estimated_tokens = count_tokens_approximately(messages)
    except Exception as e:
        logger.warning("Failed to count tokens: %s", e)
        estimated_tokens = 0

    model_limit_tokens = get_model_context_limit(model_name, llm_config)
    model_limit_k = model_limit_tokens // 1000
    usage_percentage = (estimated_tokens / model_limit_tokens * 100) if model_limit_tokens > 0 else 0

    return {
        "estimated_tokens": estimated_tokens,
        "model_limit_k": model_limit_k,
        "model_limit_tokens": model_limit_tokens,
        "usage_percentage": round(usage_percentage, 2),
        "message_count": len(messages),
        "needs_trimming": usage_percentage > 80,
    }


# Convenience function for GNS3-Copilot integration
def prepare_context_messages(
    state_messages: list[Any],
    system_prompt: str,
    topology_context: str | None,
    model_name: str,
    llm_config: dict[str, Any] | None = None,
) -> list[Any]:
    """
    Prepare full context messages for LLM call with automatic trimming.

    This is the main entry point for GNS3-Copilot to prepare messages
    before calling the LLM.

    Args:
        state_messages: Message history from conversation state
        system_prompt: System prompt text
        topology_context: Optional topology information string
        model_name: Name of the LLM model
        llm_config: Optional LLM config dict from database (may contain context_limit and context_strategy)

    Returns:
        list: Prepared messages ready for LLM invocation

    Examples:
        >>> messages = prepare_context_messages(
        ...     state_messages=[HumanMessage("Help me")],
        ...     system_prompt="You are a helpful assistant",
        ...     topology_context=None,
        ...     model_name="gpt-4o"
        ... )
        >>> len(messages)
        2  # System message + Human message
    """
    # Get trimming strategy from config (default: "balanced")
    trim_strategy = "balanced"
    if llm_config and "context_strategy" in llm_config:
        strategy = llm_config["context_strategy"]
        if strategy in ["conservative", "balanced", "aggressive"]:
            trim_strategy = strategy
            logger.debug("Using context_strategy from config: %s", trim_strategy)
        else:
            logger.warning("Invalid context_strategy '%s', using 'balanced'", strategy)

    # Build base context (system + topology)
    context_messages = [SystemMessage(content=system_prompt)]

    if topology_context:
        context_messages.append(
            SystemMessage(content=f"Current Topology:\n{topology_context}")
        )

    # Combine with conversation history
    full_messages = context_messages + state_messages

    # Trim if needed
    trimmed_messages = trim_messages_for_context(
        full_messages,
        model_name=model_name,
        llm_config=llm_config,
        strategy=trim_strategy,
        preserve_system=True,  # Always keep system prompts
    )

    # Log summary
    summary = get_token_usage_summary(trimmed_messages, model_name, llm_config)
    logger.info(
        "Context prepared: %d msgs, ~%d tokens / %dK limit (%.1f%%), strategy=%s",
        summary["message_count"],
        summary["estimated_tokens"],
        summary["model_limit_k"],
        summary["usage_percentage"],
        trim_strategy
    )

    return trimmed_messages


if __name__ == "__main__":
    # Simple test
    test_messages = [
        HumanMessage(f"Message {i}") for i in range(100)
    ]

    result = trim_messages_for_context(
        test_messages,
        model_name="gpt-4o",
        strategy="balanced"
    )

    print(f"Original: {len(test_messages)} messages")
    print(f"Trimmed: {len(result)} messages")
