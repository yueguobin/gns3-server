"""
GNS3 Connector Factory Module

This module provides factory functions for creating Gns3Connector instances.
It creates appropriately configured connectors using JWT token authentication.

The URL resolution strategy follows a priority order:
1. Explicitly provided URL parameter
2. Runtime configuration from Controller.instance().compute("local")
3. Static configuration from Config.instance().settings.Server
4. Fallback to localhost:3080

Main Functions:
    get_gns3_connector: Create a Gns3Connector with JWT token

Example:
    from gns3server.agent.gns3_copilot.gns3_client import get_gns3_connector

    # Auto-detect URL from Controller or Config
    connector = get_gns3_connector(jwt_token="your_token")
    if connector:
        # Use connector to interact with GNS3 server
        projects = connector.projects

Authentication:
    - JWT token based authentication
"""

import logging
from typing import Optional
from uuid import UUID

from gns3server.agent.gns3_copilot.gns3_client.custom_gns3fy import Gns3Connector

logger = logging.getLogger(__name__)

# Fallback default URL
DEFAULT_GNS3_URL = "http://127.0.0.1:3080"


def _get_url_from_controller() -> Optional[str]:
    """Try to get GNS3 server URL from running Controller instance.

    Returns:
        URL string if successful, None otherwise
    """
    try:
        from gns3server.controller import Controller

        controller = Controller.instance()
        local_compute = controller.get_compute("local")

        url = f"{local_compute.protocol}://{local_compute.host}:{local_compute.port}"
        logger.debug(
            "Got GNS3 URL from Controller: %s (protocol=%s, host=%s, port=%s)",
            url,
            local_compute.protocol,
            local_compute.host,
            local_compute.port,
        )
        return url
    except ImportError as e:
        logger.debug("Cannot import Controller: %s", str(e))
        return None
    except AttributeError as e:
        logger.debug("Controller instance not available: %s", str(e))
        return None
    except KeyError as e:
        logger.debug("Local compute not found in Controller: %s", str(e))
        return None
    except Exception as e:
        logger.warning("Unexpected error getting URL from Controller: %s", str(e))
        return None


def _get_url_from_config() -> Optional[str]:
    """Try to get GNS3 server URL from Config settings.

    Returns:
        URL string if successful, None otherwise
    """
    try:
        from gns3server.config import Config

        server_config = Config.instance().settings.Server
        url = f"{server_config.protocol.value}://{server_config.host}:{server_config.port}"
        logger.debug(
            "Got GNS3 URL from Config: %s (protocol=%s, host=%s, port=%s)",
            url,
            server_config.protocol.value,
            server_config.host,
            server_config.port,
        )
        return url
    except ImportError as e:
        logger.debug("Cannot import Config: %s", str(e))
        return None
    except AttributeError as e:
        logger.debug("Config settings not available: %s", str(e))
        return None
    except Exception as e:
        logger.warning("Unexpected error getting URL from Config: %s", str(e))
        return None


def get_gns3_connector(jwt_token: str, url: Optional[str] = None) -> Optional[Gns3Connector]:
    """Create and return a Gns3Connector instance with JWT authentication.

    URL Resolution Strategy (in order):
        1. Explicitly provided `url` parameter
        2. Runtime configuration from Controller.instance().compute("local")
        3. Static configuration from Config.instance().settings.Server
        4. Fallback to DEFAULT_GNS3_URL (http://127.0.0.1:3080)

    Args:
        jwt_token: JWT token for authentication
        url: GNS3 server URL (optional, auto-detected if not provided)

    Returns:
        Gns3Connector instance if parameters are valid, None otherwise

    Example:
        # Auto-detect URL from Controller or Config
        connector = get_gns3_connector(jwt_token="your_jwt_token")

        # Or specify custom URL
        connector = get_gns3_connector(
            jwt_token="your_jwt_token",
            url="http://custom-server:3080"
        )

        if connector:
            projects = connector.projects
        else:
            logger.error("Failed to create GNS3 connector")
    """
    try:
        # Validate JWT token
        if not jwt_token:
            logger.error("JWT token parameter is required")
            return None

        # Resolve URL with fallback strategy
        if url is None:
            logger.debug("No URL provided, attempting auto-detection...")

            # Strategy 1: Try to get from running Controller
            url = _get_url_from_controller()
            if url:
                logger.info("Using GNS3 server URL from Controller: %s", url)
            else:
                # Strategy 2: Fall back to Config
                logger.debug("Controller not available, trying Config...")
                url = _get_url_from_config()
                if url:
                    logger.info("Using GNS3 server URL from Config: %s", url)
                else:
                    # Strategy 3: Use default fallback
                    logger.debug("Config not available, using default URL")
                    url = DEFAULT_GNS3_URL
                    logger.warning(
                        "Using fallback default URL: %s. "
                        "This may not be correct if your GNS3 server is configured differently. "
                        "Consider providing the URL explicitly or ensuring gns3server is running.",
                        url
                    )
        else:
            logger.info("Using explicitly provided GNS3 server URL: %s", url)

        # Validate URL
        if not url:
            logger.error("Failed to resolve GNS3 server URL")
            return None

        # Create connector
        logger.debug("Creating Gns3Connector with URL=%s", url)
        connector = Gns3Connector(
            url=url,
            jwt_token=jwt_token,
            api_version=3,
        )
        logger.info("Successfully created Gns3Connector for URL: %s", url)
        return connector

    except Exception as e:
        logger.error("Failed to create Gns3Connector: %s", str(e), exc_info=True)
        return None


async def get_gns3_connector_with_llm_config(
    user_id,
    jwt_token: str,
    url: Optional[str] = None
) -> Optional[dict]:
    """
    Create Gns3Connector and retrieve LLM model configuration for the user.

    This is a convenience function that combines:
    1. get_gns3_connector() - Create GNS3 API connector
    2. get_user_llm_config() - Retrieve user's default LLM config with API key

    Args:
        user_id: User UUID (can be string or UUID object)
        jwt_token: JWT token for authentication
        url: GNS3 server URL (optional, auto-detected if not provided)

    Returns:
        Dictionary with keys:
        - connector: Gns3Connector instance
        - llm_config: Dict with provider, api_key, model, etc.
        Or None if failed

    Example:
        result = await get_gns3_connector_with_llm_config(user_id, jwt_token)
        if result:
            connector = result["connector"]
            llm_config = result["llm_config"]

            # Use connector for GNS3 operations
            projects = connector.projects

            # Use LLM config for AI operations
            provider = llm_config["provider"]
            api_key = llm_config["api_key"]
            model = llm_config["model"]
        else:
            logger.error("Failed to initialize GNS3 connector or LLM config")
    """
    try:
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        # Step 1: Create GNS3 connector
        connector = get_gns3_connector(jwt_token=jwt_token, url=url)
        if not connector:
            logger.error("Failed to create GNS3 connector")
            return None

        # Step 2: Detect URL if not provided
        if url is None:
            url = _detect_url_for_api()

        # Step 3: Get LLM config
        from gns3server.agent.gns3_copilot.utils.llm_config_helper import get_user_llm_config

        llm_config = await get_user_llm_config(
            user_id=user_id,
            jwt_token=jwt_token,
            gns3_url=url
        )

        if not llm_config:
            logger.warning(f"No LLM config found for user {user_id}")
            # Still return result with connector only
            return {
                "connector": connector,
                "llm_config": None
            }

        logger.info(
            f"Successfully initialized GNS3 connector and LLM config for user {user_id}: "
            f"connector_url={connector.url}, "
            f"llm_provider={llm_config.get('provider')}, "
            f"llm_model={llm_config.get('model')}"
        )

        return {
            "connector": connector,
            "llm_config": llm_config
        }

    except Exception as e:
        logger.error(f"Failed to get GNS3 connector with LLM config: {e}", exc_info=True)
        return None


def _detect_url_for_api() -> Optional[str]:
    """
    Detect GNS3 server URL for API calls.

    Uses the same priority order as get_gns3_connector:
    1. Controller.instance().compute("local")
    2. Config.instance().settings.Server
    3. Fallback to DEFAULT_GNS3_URL

    Returns:
        URL string, or None if detection failed
    """
    # Try Controller first
    url = _get_url_from_controller()
    if url:
        return url

    # Try Config
    url = _get_url_from_config()
    if url:
        return url

    # Fallback
    return DEFAULT_GNS3_URL


def get_gns3_server_host() -> str:
    """
    Get GNS3 server hostname from Controller or Config.

    This is a convenience function for extracting the hostname only,
    useful for Nornir tools that need the GNS3 server address.

    Uses the same priority order as get_gns3_connector:
    1. Controller.instance().compute("local")
    2. Config.instance().settings.Server
    3. Fallback to DEFAULT_GNS3_URL host

    Returns:
        Hostname/IP address string

    Example:
        from gns3server.agent.gns3_copilot.gns3_client import get_gns3_server_host

        host = get_gns3_server_host()
        print(f"GNS3 server host: {host}")
    """
    url = _detect_url_for_api()

    # Extract host from URL
    # URL format: protocol://host:port
    try:
        # Remove protocol prefix
        host_part = url.split("://")[1]
        # Extract host (before the port)
        host = host_part.split(":")[0]
        logger.debug("Extracted GNS3 server host: %s from URL: %s", host, url)
        return host
    except Exception as e:
        logger.warning("Failed to extract host from URL %s: %s, using fallback", url, e)
        return DEFAULT_GNS3_URL.split("://")[1].split(":")[0]


def get_llm_config(user_id, jwt_token: str, app=None) -> Optional[dict]:
    """
    Get LLM model configuration for a user.

    This function retrieves the user's LLM configuration from the database.
    When `app` is provided, it directly accesses the database (bypassing API restrictions).
    Otherwise, it falls back to API call (which may mask group config API keys).

    Args:
        user_id: User UUID (can be string or UUID object)
        jwt_token: JWT token for authentication
        app: FastAPI application instance (optional, for direct database access)

    Returns:
        Dictionary with LLM configuration keys (provider, model, api_key, etc.),
        or None if not found.

    Example:
        from gns3server.agent.gns3_copilot.gns3_client import get_llm_config

        config = get_llm_config(user_id, jwt_token)
        if config:
            provider = config['provider']
            model = config['model']
            api_key = config['api_key']
    """
    import asyncio
    import threading

    try:
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        # If app is provided, use direct database access (preferred)
        if app is not None:
            from gns3server.agent.gns3_copilot.utils.llm_config_helper import get_user_llm_config_with_app

            # Run the async function in sync context
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context with a running loop
                # This shouldn't happen since this is a sync function
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        get_user_llm_config_with_app(user_id, app)
                    )
                    return future.result(timeout=10)
            except RuntimeError:
                # No running event loop - we're in a sync context
                pass

            # Try to get an existing event loop, or create a new one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Loop is running but not the running loop (edge case)
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            get_user_llm_config_with_app(user_id, app)
                        )
                        return future.result(timeout=10)
                else:
                    # Loop exists but not running - use it
                    return loop.run_until_complete(get_user_llm_config_with_app(user_id, app))
            except RuntimeError:
                # No event loop exists - create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(get_user_llm_config_with_app(user_id, app))
                finally:
                    loop.close()

        # Fallback: No app provided, try API call (will mask group config API keys)
        logger.warning("No app provided for get_llm_config, group config API keys may be masked")
        return None

    except Exception as e:
        logger.error("Failed to get LLM config for user %s: %s", user_id, e)
        return None
