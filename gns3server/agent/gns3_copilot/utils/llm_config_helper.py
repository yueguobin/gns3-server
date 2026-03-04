"""
LLM Model Configuration Helper for GNS3 Copilot

This module provides utility functions to retrieve LLM model configurations
with decrypted API keys by directly accessing the database.

Usage:
    from gns3server.agent.gns3_copilot.utils.llm_config_helper import get_user_llm_config_with_app

    # Get user's default LLM config (with API key)
    config = await get_user_llm_config_with_app(user_id, app)
    if config:
        provider = config['provider']
        api_key = config['api_key']
        model = config['model']
"""

import logging
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def get_user_llm_config_with_app(
    user_id: UUID,
    app: FastAPI
) -> Optional[Dict[str, Any]]:
    """
    Get user's default LLM model configuration with decrypted API key.

    This function directly accesses the database through the app reference,
    bypassing API security restrictions to get the complete configuration including
    decrypted API keys, even for inherited group configurations.

    Args:
        user_id: User UUID
        app: FastAPI application instance

    Returns:
        Configuration dict with provider, api_key, model, etc., or None if not found

    Example:
        config = await get_user_llm_config_with_app(user_id, app)
        if config:
            print(f"Provider: {config['provider']}")
            print(f"Model: {config['model']}")
            print(f"API Key: {config['api_key']}")
            print(f"Source: {config['source']}")
    """
    from gns3server.db.tasks import get_user_llm_config_full

    try:
        user_id_str = str(user_id)
        config = await get_user_llm_config_full(user_id_str, app)

        if config:
            logger.info(
                f"Successfully retrieved LLM config for user {user_id}: "
                f"provider={config.get('provider')}, model={config.get('model')}"
            )
        else:
            logger.warning(f"No LLM configuration found for user {user_id}")

        return config

    except Exception as e:
        logger.error(f"Failed to retrieve LLM config for user {user_id}: {e}", exc_info=True)
        return None
