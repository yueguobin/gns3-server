"""
LLM Model Configuration Helper for GNS3 Copilot

This module provides utility functions to retrieve LLM model configurations
using a hybrid approach:
1. Get config_id via API (respects priority logic)
2. Get full config via Repository (includes API key)
3. Decrypt API key for LLM service calls

This allows the copilot module to access API keys that are hidden from API responses
while leveraging the API's default_config selection logic.

Usage:
    from gns3_copilot.utils.llm_config_helper import get_user_llm_config

    # Get user's default LLM config (with API key)
    config = get_user_llm_config(user_id, jwt_token, gns3_url)
    if config:
        provider = config['provider']
        api_key = config['api_key']
        model = config['model']
"""

import logging
from typing import Optional, Dict, Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


async def get_user_llm_config(
    user_id: UUID,
    jwt_token: str,
    gns3_url: Optional[str] = None,
    timeout: float = 5.0
) -> Optional[Dict[str, Any]]:
    """
    Get user's default LLM model configuration with API key using hybrid approach.

    Step 1: Call API to get default_config's config_id (respects priority logic)
    Step 2: Query Repository to get full config (includes encrypted API key)
    Step 3: Decrypt API key for LLM service usage

    Args:
        user_id: User UUID
        jwt_token: JWT token for API authentication
        gns3_url: GNS3 server URL (optional, will auto-detect if not provided)
        timeout: HTTP request timeout in seconds

    Returns:
        Configuration dict with provider, api_key, model, etc., or None if not found

    Example:
        config = await get_user_llm_config(user_id, jwt_token)
        if config:
            print(f"Provider: {config['provider']}")
            print(f"Model: {config['model']}")
            print(f"API Key: {config['api_key']}")
            print(f"Source: {config['source']}")
    """
    try:
        # Step 1: Get GNS3 URL if not provided
        if gns3_url is None:
            gns3_url = _detect_gns3_url()
            if not gns3_url:
                logger.error("Failed to detect GNS3 server URL")
                return None

        # Step 2: Call API to get default_config
        logger.debug(f"Fetching default config for user {user_id} from API...")
        api_response = await _call_llm_configs_api(gns3_url, user_id, jwt_token, timeout)

        if not api_response:
            logger.warning(f"No LLM model configurations found for user {user_id}")
            return None

        default_config = api_response.get("default_config")
        if not default_config:
            logger.warning(f"No default LLM model configuration found for user {user_id}")
            return None

        config_id = default_config.get("config_id")
        source = default_config.get("source")  # "user" or "group"

        logger.debug(
            f"API returned default_config: config_id={config_id}, source={source}"
        )

        # Step 3: Query Repository for full config
        full_config = await _get_full_config_from_db(config_id, source)
        if not full_config:
            logger.error(f"Failed to retrieve full config from database: config_id={config_id}")
            return None

        # Step 4: Decrypt API key
        from gns3server.utils.encryption import decrypt, is_encrypted

        config_data = full_config.config.copy()
        if "api_key" in config_data and config_data["api_key"]:
            try:
                if is_encrypted(config_data["api_key"]):
                    config_data["api_key"] = decrypt(config_data["api_key"])
                    logger.debug("Successfully decrypted API key")
            except Exception as e:
                logger.error(f"Failed to decrypt API key: {e}")
                config_data["api_key"] = None
        else:
            logger.warning("No API key found in configuration")

        # Step 5: Build simplified config dict
        llm_config = {
            "config_id": full_config.config_id,
            "name": full_config.name,
            "model_type": full_config.model_type,
            "source": source,
            "group_name": default_config.get("group_name"),
            "user_id": full_config.user_id,
            "group_id": full_config.group_id,
            **config_data  # provider, api_key, model, temperature, etc.
        }

        logger.info(
            f"Successfully retrieved LLM config for user {user_id}: "
            f"provider={llm_config.get('provider')}, "
            f"model={llm_config.get('model')}, "
            f"source={llm_config.get('source')}"
        )

        return llm_config

    except Exception as e:
        logger.error(f"Failed to retrieve LLM config for user {user_id}: {e}", exc_info=True)
        return None


async def _call_llm_configs_api(
    gns3_url: str,
    user_id: UUID,
    jwt_token: str,
    timeout: float
) -> Optional[Dict[str, Any]]:
    """
    Call GNS3 API to get user's LLM model configurations.

    Args:
        gns3_url: GNS3 server URL
        user_id: User UUID
        jwt_token: JWT token for authentication
        timeout: Request timeout in seconds

    Returns:
        API response dict, or None if failed
    """
    try:
        url = f"{gns3_url}/v3/access/users/{user_id}/llm-model-configs"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }

        logger.debug(f"Calling API: GET {url}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"LLM configs endpoint returned 404 for user {user_id}")
                return None
            else:
                logger.error(
                    f"API returned error {response.status_code}: {response.text}"
                )
                return None

    except httpx.TimeoutException:
        logger.error(f"Timeout while calling LLM configs API")
        return None
    except Exception as e:
        logger.error(f"Failed to call LLM configs API: {e}", exc_info=True)
        return None


async def _get_full_config_from_db(config_id: UUID, source: str) -> Optional[Any]:
    """
    Get full configuration from database by config_id.

    Args:
        config_id: Configuration UUID
        source: Configuration source ("user" or "group")

    Returns:
        Full config object from database, or None if not found
    """
    try:
        from gns3server.db.repositories.llm_model_configs import LLMModelConfigsRepository
        from gns3server.db import get_session

        with get_session() as db_session:
            repo = LLMModelConfigsRepository(db_session)

            if source == "user":
                logger.debug(f"Fetching user config from DB: config_id={config_id}")
                config = await repo.get_user_config(config_id)
            else:
                logger.debug(f"Fetching group config from DB: config_id={config_id}")
                config = await repo.get_group_config(config_id)

            if config:
                logger.debug(f"Successfully retrieved config from DB: config_id={config_id}")
            else:
                logger.warning(f"Config not found in DB: config_id={config_id}, source={source}")

            return config

    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to retrieve config from DB: {e}", exc_info=True)
        return None


def _detect_gns3_url() -> Optional[str]:
    """
    Auto-detect GNS3 server URL using existing connector_factory logic.

    Returns:
        GNS3 server URL, or None if detection failed
    """
    try:
        from gns3_copilot.gns3_client.connector_factory import (
            _get_url_from_controller,
            _get_url_from_config,
            DEFAULT_GNS3_URL
        )

        # Try Controller first
        url = _get_url_from_controller()
        if url:
            logger.debug(f"Auto-detected GNS3 URL from Controller: {url}")
            return url

        # Try Config
        url = _get_url_from_config()
        if url:
            logger.debug(f"Auto-detected GNS3 URL from Config: {url}")
            return url

        # Fallback
        logger.warning(f"Using fallback GNS3 URL: {DEFAULT_GNS3_URL}")
        return DEFAULT_GNS3_URL

    except ImportError as e:
        logger.error(f"Failed to import connector_factory: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to auto-detect GNS3 URL: {e}", exc_info=True)
        return None


# Synchronous wrapper for backward compatibility
def get_user_llm_config_sync(user_id: UUID, jwt_token: str, gns3_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Synchronous wrapper for get_user_llm_config.

    This is a convenience function for code that cannot use async/await.
    It runs the async function in a new event loop.

    Args:
        user_id: User UUID
        jwt_token: JWT token for API authentication
        gns3_url: GNS3 server URL (optional)

    Returns:
        Configuration dict, or None if not found
    """
    import asyncio

    try:
        # Try to get running event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, we need to run in a separate thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    get_user_llm_config(user_id, jwt_token, gns3_url)
                )
                return future.result(timeout=10)
        else:
            # No loop running, use run() directly
            return asyncio.run(get_user_llm_config(user_id, jwt_token, gns3_url))
    except Exception as e:
        logger.error(f"Failed to run async get_user_llm_config: {e}", exc_info=True)
        return None
