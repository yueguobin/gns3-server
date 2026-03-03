"""
Dynamic prompt loader for GNS3 Network Automation Assistant

This module provides functionality to dynamically load system prompts based on English proficiency levels.
It supports loading different prompts for A1, A2, B1, B2, C1, and C2 English levels from environment variables.

Note: Voice/text mode selection is now handled by backend/services/prompt_manager.py
based on the 'mode' parameter ('voice' or 'text') in API requests.
"""

import importlib
import logging
import os
from typing import cast

logger = logging.getLogger(__name__)

# Mapping of English levels to their corresponding prompt modules
ENGLISH_LEVEL_PROMPT_MAP = {
    "NORMAL PROMPT": "base_prompt",
    "A1": "english_level_prompt_a1",
    "A2": "english_level_prompt_a2",
    "B1": "english_level_prompt_b1",
    "B2": "english_level_prompt_b2",
    "C1": "english_level_prompt_c1",
    "C2": "english_level_prompt_c2",
}


def _load_base_prompt() -> str:
    """
    Load the base_prompt system prompt.

    Returns:
        str: The base_prompt system prompt content.

    Raises:
        ImportError: If there's an error importing the base_prompt module.
        AttributeError: If the SYSTEM_PROMPT is not found in the base_prompt module.
    """
    try:
        # Import the base_prompt module
        base_prompt_module = importlib.import_module("gns3_copilot.prompts.base_prompt")

        # Get the SYSTEM_PROMPT from the module
        if hasattr(base_prompt_module, "SYSTEM_PROMPT"):
            system_prompt = cast(str, base_prompt_module.SYSTEM_PROMPT)
            logger.info("Successfully loaded prompt: source=base_prompt.py")
            return system_prompt
        else:
            raise AttributeError("SYSTEM_PROMPT not found in base_prompt module")

    except ImportError as e:
        logger.error("Failed to import base_prompt module: %s", e)
        raise ImportError(f"Failed to import base_prompt module: {e}") from e

    except AttributeError as e:
        logger.error("Error accessing SYSTEM_PROMPT in base_prompt module: %s", e)
        raise AttributeError(
            f"Error accessing SYSTEM_PROMPT in base_prompt module: {e}"
        ) from e


def _load_regular_level_prompt(level: str | None = None) -> str:
    """
    Load regular prompt based on English proficiency level.

    Args:
        level (str, optional): English proficiency level (A1, A2, B1, B2, C1, C2).
                              If not provided, will use base_prompt.

    Returns:
        str: The regular system prompt content for the specified English level.
    """
    # Normalize level to uppercase if provided
    if level:
        level = level.upper().strip()

    # If no valid English level is specified, use base_prompt
    if not level or level not in ENGLISH_LEVEL_PROMPT_MAP:
        logger.info(
            "Loading prompt: source=base_prompt.py (ENGLISH_LEVEL='%s', using default)",
            level
        )
        return _load_base_prompt()

    # Get the module name for the level
    module_name = ENGLISH_LEVEL_PROMPT_MAP[level]

    try:
        # Import the module dynamically
        prompt_module = importlib.import_module(f"gns3_copilot.prompts.{module_name}")

        # Get the SYSTEM_PROMPT from the module
        if hasattr(prompt_module, "SYSTEM_PROMPT"):
            base_prompt = cast(str, prompt_module.SYSTEM_PROMPT)
            logger.info(
                "Loading prompt: source=%s.py (ENGLISH_LEVEL='%s')",
                module_name,
                level
            )
            return base_prompt
        else:
            raise AttributeError(f"SYSTEM_PROMPT not found in module {module_name}")

    except ImportError as e:
        logger.error("Failed to import regular prompt module '%s': %s", module_name, e)
        # Fallback to base_prompt
        logger.info("Loading prompt: source=base_prompt.py (fallback due to import error)")
        return _load_base_prompt()

    except AttributeError as e:
        logger.error(
            "Error accessing SYSTEM_PROMPT in regular prompt module '%s': %s",
            module_name,
            e,
        )
        # Fallback to base_prompt
        logger.info("Loading prompt: source=base_prompt.py (fallback due to attribute error)")
        return _load_base_prompt()


def load_system_prompt(level: str | None = None) -> str:
    """
    Load system prompt based on English proficiency level.

    This function loads the appropriate system prompt based on the ENGLISH_LEVEL
    environment variable or the provided level parameter.

    Args:
        level (str, optional): English proficiency level (A1, A2, B1, B2, C1, C2).
                              If not provided, will read from ENGLISH_LEVEL environment variable.

    Returns:
        str: The system prompt content for the specified English level.

    Raises:
        ImportError: If there's an error importing the prompt module.
        AttributeError: If the SYSTEM_PROMPT is not found in the module.
    """
    # Determine the English level to use
    if not level:
        # Get ENGLISH_LEVEL from environment variable
        level = os.getenv("ENGLISH_LEVEL", "")
        logger.debug("Retrieved ENGLISH_LEVEL from environment: '%s'", level)

    # Return regular level prompt
    return _load_regular_level_prompt(level)
