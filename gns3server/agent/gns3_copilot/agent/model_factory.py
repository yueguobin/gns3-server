"""
Model Factory for FlowNet-Lab Agent

This module provides factory functions to create fresh LLM model instances.
Configuration can be loaded from:
1. Passed llm_config dictionary (from new llm_model_configs system)
2. Environment variables (fallback for backward compatibility)
"""

import logging
import os
from typing import Any, Optional

from langchain.chat_models import init_chat_model

logger = logging.getLogger(__name__)


def _load_llm_config(llm_config: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """
    Load model configuration from llm_config dict or environment variables.

    Args:
        llm_config: Optional configuration dictionary from llm_model_configs system.
                    If not provided, will load from environment variables.

    Returns:
        Dictionary containing model configuration.
    """
    if llm_config:
        # Use provided configuration (from llm_model_configs system)
        return {
            "model_name": llm_config.get("model", ""),
            "model_provider": llm_config.get("provider", ""),
            "api_key": llm_config.get("api_key", ""),
            "base_url": llm_config.get("base_url", ""),
            "temperature": str(llm_config.get("temperature", "0")),
        }
    else:
        # Fallback to environment variables
        return {
            "model_name": os.getenv("MODEL_NAME", ""),
            "model_provider": os.getenv("MODE_PROVIDER", ""),
            "api_key": os.getenv("MODEL_API_KEY", ""),
            "base_url": os.getenv("BASE_URL", ""),
            "temperature": os.getenv("TEMPERATURE", "0"),
        }


def create_base_model() -> Any:
    """
    Create a fresh base LLM model instance from current environment variables.

    This function reads environment variables fresh every time it's called,
    allowing configuration changes to take effect immediately.

    Returns:
        Any: A new LLM model instance configured with current env vars.
              The actual type depends on the provider (e.g., ChatOpenAI, etc.).

    Raises:
        ValueError: If required environment variables are missing or invalid.
    """
    env_vars = _load_llm_config()

    # Log the loaded configuration (mask sensitive data)
    logger.info(
        "Creating base model: name=%s, provider=%s, base_url=%s, temperature=%s",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
        env_vars["temperature"],
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature=env_vars["temperature"],
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Base model created successfully")
        return model

    except Exception as e:
        logger.error("Failed to create base model: %s", e)
        raise RuntimeError(f"Failed to create base model: {e}") from e


def create_title_model() -> Any:
    """
    Create a fresh title generation model instance.

    This creates a model instance suitable for generating conversation titles.
    It uses the same configuration as the base model but with a higher temperature
    for more creative output.

    Returns:
        Any: A new LLM model instance for title generation.
              The actual type depends on the provider.

    Raises:
        ValueError: If required environment variables are missing or invalid.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating title model: name=%s, provider=%s, base_url=%s, temperature=1.0",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="1.0",  # Higher temperature for more creative titles
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Title model created successfully")
        return model

    except Exception as e:
        logger.error("Failed to create title model: %s", e)
        raise RuntimeError(f"Failed to create title model: {e}") from e


def create_model_with_tools(
    model: Any,
    tools: list[Any],
) -> Any:
    """
    Bind tools to a model instance.

    Args:
        model: The base model instance.
        tools: List of tools to bind to the model.

    Returns:
        Any: A model instance with tools bound (type varies by provider).

    Raises:
        RuntimeError: If tool binding fails.
    """
    try:
        model_with_tools = model.bind_tools(tools)
        logger.info("Model bound with %d tools successfully", len(tools))
        return model_with_tools
    except Exception as e:
        logger.error("Failed to bind tools to model: %s", e)
        raise RuntimeError(f"Failed to bind tools to model: {e}") from e


def create_note_organizer_model() -> Any:
    """
    Create a fresh model instance for note organization.

    This creates a model instance suitable for organizing and formatting notes.
    It uses the same configuration as the base model but with a lower temperature
    for more consistent and predictable output.

    Returns:
        Any: A new LLM model instance for note organization.
              The actual type depends on the provider.

    Raises:
        ValueError: If required environment variables are missing or invalid.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating note organizer model: name=%s, provider=%s, base_url=%s, temperature=0.3",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="0.3",  # Lower temperature for more consistent note organization
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Note organizer model created successfully")
        return model

    except Exception as e:
        logger.error("Failed to create note organizer model: %s", e)
        raise RuntimeError(f"Failed to create note organizer model: {e}") from e


def create_base_model_with_tools(tools: list[Any]) -> Any:
    """
    Create a fresh base model instance with tools bound.

    This is a convenience function that combines creating the base model
    and binding tools to it.

    Args:
        tools: List of tools to bind to the model.

    Returns:
        Any: A new model instance with tools bound (type varies by provider).

    Raises:
        ValueError: If required environment variables are missing.
        RuntimeError: If model creation or tool binding fails.
    """
    base_model = create_base_model()
    return create_model_with_tools(base_model, tools)


def create_window_agent_base_model() -> Any:
    """
    Create a base model instance for Window Agent (without tools).

    This creates a model instance suitable for Window Agent (voice mode).
    Uses temperature=0 for precise, deterministic responses.

    Returns:
        Any: A new base LLM model instance (without tools bound).
              The actual type depends on the provider.

    Raises:
        ValueError: If required environment variables are missing.
        RuntimeError: If model creation fails.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating Window Agent base model: name=%s, provider=%s, base_url=%s, temperature=0",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        # Create model with temperature=0 for voice mode (precise, concise responses)
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="0",  # Force temperature=0 for voice mode
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Window Agent base model created successfully (no tools)")
        return model

    except Exception as e:
        logger.error("Failed to create Window Agent base model: %s", e)
        raise RuntimeError(f"Failed to create Window Agent base model: {e}") from e


def create_window_agent_model_with_tools(tools: list[Any]) -> Any:
    """
    Create a model instance with tools for Window Agent.

    Window Agent runs in VOICE mode and needs precise, deterministic responses.
    Uses temperature=0 for consistency.

    Args:
        tools: List of tools to bind to the model.

    Returns:
        Any: A new model instance with tools bound (type varies by provider).

    Raises:
        ValueError: If required environment variables are missing.
        RuntimeError: If model creation or tool binding fails.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating Window Agent model: name=%s, provider=%s, base_url=%s, temperature=0",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        # Create model with temperature=0 for voice mode (precise, concise responses)
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="0",  # Force temperature=0 for voice mode
            configurable_fields="any",
            config_prefix="foo",
        )

        # Bind tools
        model_with_tools = model.bind_tools(tools)
        logger.info("Window Agent model created with %d tools", len(tools))
        return model_with_tools

    except Exception as e:
        logger.error("Failed to create Window Agent model: %s", e)
        raise RuntimeError(f"Failed to create Window Agent model: {e}") from e


def create_experiment_planner_model() -> Any:
    """
    Create a fresh model instance for experiment planning.

    This creates a model instance suitable for generating GNS3 lab experiment plans.
    It uses the same configuration as the base model but with a moderate temperature
    to balance creativity and accuracy in lab design.

    Returns:
        Any: A new LLM model instance for experiment planning.
              The actual type depends on the provider.

    Raises:
        ValueError: If required environment variables are missing or invalid.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating experiment planner model: name=%s, provider=%s, base_url=%s, temperature=0.7",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="0.7",  # Moderate temperature for balanced creativity and accuracy
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Experiment planner model created successfully")
        return model

    except Exception as e:
        logger.error("Failed to create experiment planner model: %s", e)
        raise RuntimeError(f"Failed to create experiment planner model: {e}") from e


def create_vision_model():
    """
    Create a fresh Qwen-VL vision model instance for network topology recognition.

    This creates a vision model instance using Qwen-VL through DashScope SDK
    for recognizing network topology diagrams from images.

    Returns:
        QwenVisionModel: A new Qwen-VL vision model instance.

    Raises:
        ImportError: If dashscope package is not installed.
        ValueError: If QWEN_API_KEY is not configured.
        RuntimeError: If model creation fails.
    """
    from gns3_copilot.agent.qwen_vision_model import create_qwen_vision_model

    logger.info("Creating Qwen-VL vision model")

    try:
        model = create_qwen_vision_model()
        logger.info("Qwen-VL vision model created successfully")
        return model
    except Exception as e:
        logger.error("Failed to create Qwen-VL vision model: %s", e)
        raise RuntimeError(f"Failed to create Qwen-VL vision model: {e}") from e


def create_presentation_eval_model() -> Any:
    """
    Create a fresh model instance for presentation evaluation.

    This creates a model instance suitable for evaluating network engineer
    presentations. Uses moderate temperature for balanced objective assessment.

    Returns:
        Any: A new LLM model instance for presentation evaluation.

    Raises:
        ValueError: If required environment variables are missing.
        RuntimeError: If model creation fails.
    """
    env_vars = _load_llm_config()

    logger.info(
        "Creating presentation evaluator model: name=%s, provider=%s, base_url=%s, temperature=0.5",
        env_vars["model_name"],
        env_vars["model_provider"],
        env_vars["base_url"] if env_vars["base_url"] else "default",
    )

    # Validate required fields
    if not env_vars["model_name"]:
        raise ValueError("MODEL_NAME environment variable is required")

    if not env_vars["model_provider"]:
        raise ValueError("MODE_PROVIDER environment variable is required")

    try:
        model = init_chat_model(
            env_vars["model_name"],
            model_provider=env_vars["model_provider"],
            api_key=env_vars["api_key"],
            base_url=env_vars["base_url"],
            temperature="0.5",  # Moderate temperature for balanced evaluation
            configurable_fields="any",
            config_prefix="foo",
        )

        logger.info("Presentation evaluator model created successfully")
        return model

    except Exception as e:
        logger.error("Failed to create presentation evaluator model: %s", e)
        raise RuntimeError(f"Failed to create presentation evaluator model: {e}") from e
