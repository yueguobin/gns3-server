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
API routes for LLM model configurations.
"""

import logging
from typing import List, Optional
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, status

from gns3server import schemas
from gns3server.agent.gns3_copilot.provider_schema import (
    available_provider_schemas,
    build_models_request,
    declared_provider_names,
    normalize_models_payload,
)
from gns3server.controller.controller_error import (
    ControllerBadRequestError,
    ControllerNotFoundError,
)
from gns3server.db.repositories.llm_model_configs import LLMModelConfigsRepository
from gns3server.db.repositories.users import UsersRepository

from .dependencies.database import get_repository
from .dependencies.rbac import has_privilege

log = logging.getLogger(__name__)

router = APIRouter()


def _filter_api_key_from_config(config: dict) -> dict:
    """
    Remove API key from config dict for security.
    API keys should NEVER be returned via API endpoints.

    :param config: Configuration dictionary
    :return: Configuration dictionary with api_key set to None
    """
    filtered = config.copy()
    if "api_key" in filtered:
        filtered["api_key"] = None
    return filtered


# ============================================================================
# Provider Schema Endpoint
# ============================================================================


@router.get(
    "/llm-model-configs/provider-schema",
    response_model=schemas.ProviderSchemaListResponse,
    dependencies=[Depends(has_privilege("LLMConfig.Audit"))],
)
async def get_llm_provider_schemas(
    provider: Optional[str] = None,
) -> schemas.ProviderSchemaListResponse:
    """
    Field descriptors for the supported LLM providers, so the web UI can
    render the configuration form dynamically instead of hardcoding
    provider differences.

    Returns the intersection of providers declared in the registry
    (gns3server/agent/gns3_copilot/provider_schema.py) and langchain
    integration packages installed on this server.

    Required privilege: LLMConfig.Audit
    """
    provider_schemas = available_provider_schemas(provider)
    return schemas.ProviderSchemaListResponse(providers=provider_schemas, total=len(provider_schemas))


# ============================================================================
# Provider Models Endpoint
# ============================================================================

# A silent connection must fail fast; model listing is an interactive,
# form-filling call, not a long-running request.
_MODELS_FETCH_TIMEOUT_S = 10


async def _fetch_provider_models(url: str, headers: dict[str, str]) -> dict:
    """Call the provider's models endpoint.

    The API key only ever lives in the request headers: it is not logged
    and never echoed back.
    """
    timeout = aiohttp.ClientTimeout(total=_MODELS_FETCH_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    if response.status in (401, 403):
                        raise ControllerBadRequestError("Could not list models: the provider rejected the API key")
                    raise ControllerBadRequestError(
                        f"Could not list models: the provider returned HTTP {response.status}"
                    )
                return await response.json()
    except ControllerBadRequestError:
        raise
    except (aiohttp.ClientError, TimeoutError) as e:
        raise ControllerBadRequestError(f"Could not reach the provider to list models: {e}") from e


@router.post(
    "/llm-model-configs/provider-models",
    response_model=schemas.ProviderModelsResponse,
    dependencies=[Depends(has_privilege("LLMConfig.Audit"))],
)
async def fetch_llm_provider_models(request: schemas.ProviderModelsRequest) -> schemas.ProviderModelsResponse:
    """
    Fetch a provider's model catalog live through the server, so the web
    UI can offer a model dropdown without hardcoding model names.

    The API key from the request body is forwarded to the provider for
    this one call; it is never stored or logged. Model fields in the
    schema stay free text so a failed fetch can still be typed by hand.

    Required privilege: LLMConfig.Audit
    """
    if request.provider not in declared_provider_names():
        raise ControllerBadRequestError(
            f"Unsupported LLM provider '{request.provider}'. Declared providers: {', '.join(declared_provider_names())}"
        )
    if not request.api_key:
        raise ControllerBadRequestError("An API key is required to fetch the provider's model list")

    built = build_models_request(request.provider, request.api_key, request.base_url)
    if built is None:
        raise ControllerBadRequestError(f"Provider '{request.provider}' does not publish a model list API")
    url, headers = built

    payload = await _fetch_provider_models(url, headers)
    models = normalize_models_payload(payload)
    return schemas.ProviderModelsResponse(provider=request.provider, models=models, total=len(models))


# ============================================================================
# User LLM Model Configuration Endpoints
# ============================================================================


@router.get("/users/{user_id}/llm-model-configs", response_model=schemas.LLMModelConfigInheritedResponse)
async def get_user_llm_model_configs(
    user_id: UUID,
    current_user: schemas.User = Depends(has_privilege("LLMConfig.Audit")),
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigInheritedResponse:
    """
    Get user's effective LLM model configurations (own + inherited from groups).

    Required privilege: LLMConfig.Audit
    """

    try:
        result = await llm_repo.get_user_effective_configs(
            user_id, current_user_id=current_user.user_id, current_user_is_superadmin=current_user.is_superadmin
        )
        return schemas.LLMModelConfigInheritedResponse(
            configs=result["configs"], default_config=result.get("default_config"), total=len(result["configs"])
        )
    except Exception as e:
        log.error(f"Failed to retrieve user LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve LLM model configurations"
        )


@router.get(
    "/users/{user_id}/llm-model-configs/own",
    response_model=List[schemas.LLMModelConfigResponse],
    dependencies=[Depends(has_privilege("LLMConfig.Audit"))],
)
async def get_user_own_llm_model_configs(
    user_id: UUID, llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> List[schemas.LLMModelConfigResponse]:
    """
    Get user's own LLM model configurations (excluding inherited ones).

    Required privilege: LLMConfig.Audit
    """

    try:
        configs = await llm_repo.get_user_configs(user_id)
        return [
            schemas.LLMModelConfigResponse(
                config_id=config.config_id,
                name=config.name,
                model_type=config.model_type,
                config=_filter_api_key_from_config(config.config),
                user_id=config.user_id,
                group_id=config.group_id,
                is_default=config.is_default,
                version=config.version,
                created_at=config.created_at,
                updated_at=config.updated_at,
            )
            for config in configs
        ]
    except Exception as e:
        log.error(f"Failed to retrieve user's own LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve LLM model configurations"
        )


@router.get(
    "/users/{user_id}/llm-model-configs/default",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("LLMConfig.Audit"))],
)
async def get_user_default_llm_model_config(
    user_id: UUID, llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Get user's default LLM model configuration.

    Required privilege: LLMConfig.Audit
    """

    try:
        config = await llm_repo.get_user_default_config(user_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No default LLM model configuration found for user '{user_id}'",
            )

        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            name=config.name,
            model_type=config.model_type,
            config=_filter_api_key_from_config(config.config),
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            version=config.version,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to retrieve user's default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve LLM model configuration"
        )


@router.post(
    "/users/{user_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_privilege("LLMConfig.Modify"))],
)
async def create_user_llm_model_config(
    user_id: UUID,
    config_create: schemas.LLMModelConfigCreate,
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Create a new LLM model configuration for a user.

    Required privilege: LLMConfig.Modify

    IMPORTANT: context_limit is REQUIRED. Unit is K tokens (e.g., 128 = 128K = 128,000 tokens).
    Please check your model provider's documentation for the current context window size.
    """

    # Verify user exists
    user = await users_repo.get_user(user_id)
    if not user:
        raise ControllerNotFoundError(f"User '{user_id}' not found")

    # Validate context_limit is provided
    if not hasattr(config_create, "context_limit") or config_create.context_limit is None:
        raise ControllerBadRequestError(
            "context_limit is required (unit: K tokens, e.g., 128 = 128K = 128,000 tokens). "
            "Please check your model provider's documentation for the current context window size "
            "and specify it in the configuration."
        )

    # The provider must have declared metadata so the web UI can render a
    # form for it
    if config_create.provider not in declared_provider_names():
        raise ControllerBadRequestError(
            f"Unsupported LLM provider '{config_create.provider}'. "
            f"Declared providers: {', '.join(declared_provider_names())}"
        )

    try:
        # Extract config fields (excluding table-level fields)
        config_fields = config_create.model_dump(exclude={"name", "model_type", "is_default"})
        new_config = await llm_repo.create_user_config(
            user_id,
            config_create.name,
            config_create.model_type,
            config_fields,
            is_default=bool(config_create.is_default),
        )

        return schemas.LLMModelConfigResponse(
            config_id=new_config.config_id,
            name=new_config.name,
            model_type=new_config.model_type,
            config=_filter_api_key_from_config(new_config.config),
            user_id=new_config.user_id,
            group_id=new_config.group_id,
            is_default=new_config.is_default,
            version=new_config.version,
            created_at=new_config.created_at,
            updated_at=new_config.updated_at,
        )
    except ValueError as e:
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to create LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create LLM model configuration: {e}"
        )


@router.put(
    "/users/{user_id}/llm-model-configs/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("LLMConfig.Modify"))],
)
async def update_user_llm_model_config(
    user_id: UUID,
    config_id: UUID,
    config_update: schemas.LLMModelConfigUpdate,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Update a user's LLM model configuration.
    Supports optimistic locking via expected_version field.

    Required privilege: LLMConfig.Modify
    """

    # Reject switching to a provider without declared metadata. A legacy
    # config with an unknown provider may still be saved unchanged.
    stored_config = await llm_repo.get_user_config(config_id)
    if stored_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
        )
    new_provider = config_update.provider
    if (
        new_provider
        and new_provider != (stored_config.config or {}).get("provider")
        and new_provider not in declared_provider_names()
    ):
        raise ControllerBadRequestError(
            f"Unsupported LLM provider '{new_provider}'. Declared providers: {', '.join(declared_provider_names())}"
        )

    try:
        # Build updates dict with only non-None values
        updates = {k: v for k, v in config_update.model_dump().items() if v is not None}

        # Extract expected_version for optimistic locking
        expected_version = updates.pop("expected_version", None)

        updated_config = await llm_repo.update_user_config(
            config_id, user_id, updates, expected_version=expected_version
        )

        if not updated_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )

        return schemas.LLMModelConfigResponse(
            config_id=updated_config.config_id,
            name=updated_config.name,
            model_type=updated_config.model_type,
            config=_filter_api_key_from_config(updated_config.config),
            user_id=updated_config.user_id,
            group_id=updated_config.group_id,
            is_default=updated_config.is_default,
            version=updated_config.version,
            created_at=updated_config.created_at,
            updated_at=updated_config.updated_at,
        )
    except HTTPException:
        raise
    except ValueError as e:
        # Handle optimistic lock errors
        if "Concurrent modification" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to update LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update LLM model configuration"
        )


@router.delete(
    "/users/{user_id}/llm-model-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("LLMConfig.Modify"))],
)
async def delete_user_llm_model_config(
    user_id: UUID,
    config_id: UUID,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> None:
    """
    Delete a user's LLM model configuration.

    Required privilege: LLMConfig.Modify
    """

    try:
        success = await llm_repo.delete_user_config(config_id, user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete LLM model configuration"
        )


@router.put(
    "/users/{user_id}/llm-model-configs/default/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("LLMConfig.Modify"))],
)
async def set_user_default_llm_model_config(
    user_id: UUID,
    config_id: UUID,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Set a user's default LLM model configuration.

    Required privilege: LLMConfig.Modify
    """

    try:
        success = await llm_repo.set_user_default_config(user_id, config_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )

        # Get the updated config
        config = await llm_repo.get_user_config(config_id)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )
        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            name=config.name,
            model_type=config.model_type,
            config=_filter_api_key_from_config(config.config),
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            version=config.version,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to set default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set default LLM model configuration"
        )


# ============================================================================
# Group LLM Model Configuration Endpoints
# ============================================================================


@router.get(
    "/groups/{group_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigListResponse,
    dependencies=[Depends(has_privilege("Group.Audit"))],
)
async def get_group_llm_model_configs(
    group_id: UUID, llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigListResponse:
    """
    Get all LLM model configurations for a user group.

    Required privilege: Group.Audit
    """

    try:
        configs = await llm_repo.get_group_configs(group_id)
        config_responses = [
            schemas.LLMModelConfigResponse(
                config_id=config.config_id,
                name=config.name,
                model_type=config.model_type,
                config=_filter_api_key_from_config(config.config),
                user_id=config.user_id,
                group_id=config.group_id,
                is_default=config.is_default,
                version=config.version,
                created_at=config.created_at,
                updated_at=config.updated_at,
            )
            for config in configs
        ]

        # Find default config (same logic as user configs)
        default_config = None
        for config in config_responses:
            if config.is_default:
                default_config = config
                break

        # Fallback to first config if no default is marked
        if default_config is None and config_responses:
            default_config = config_responses[0]

        return schemas.LLMModelConfigListResponse(
            configs=config_responses, default_config=default_config, total=len(config_responses)
        )
    except Exception as e:
        log.error(f"Failed to retrieve group LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve LLM model configurations"
        )


@router.get(
    "/groups/{group_id}/llm-model-configs/default",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("Group.Audit"))],
)
async def get_group_default_llm_model_config(
    group_id: UUID, llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Get group's default LLM model configuration.

    Required privilege: Group.Audit
    """

    try:
        config = await llm_repo.get_group_default_config(group_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No default LLM model configuration found for group '{group_id}'",
            )

        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            name=config.name,
            model_type=config.model_type,
            config=_filter_api_key_from_config(config.config),
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            version=config.version,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to retrieve group's default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve LLM model configuration"
        )


@router.post(
    "/groups/{group_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_privilege("Group.Modify"))],
)
async def create_group_llm_model_config(
    group_id: UUID,
    config_create: schemas.LLMModelConfigCreate,
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Create a new LLM model configuration for a user group.

    Required privilege: Group.Modify

    IMPORTANT: context_limit is REQUIRED. Unit is K tokens (e.g., 128 = 128K = 128,000 tokens).
    Please check your model provider's documentation for the current context window size.
    """

    # Verify group exists
    group = await users_repo.get_user_group(group_id)
    if not group:
        raise ControllerNotFoundError(f"User group '{group_id}' not found")

    # Validate context_limit is provided
    if not hasattr(config_create, "context_limit") or config_create.context_limit is None:
        raise ControllerBadRequestError(
            "context_limit is required (unit: K tokens, e.g., 128 = 128K = 128,000 tokens). "
            "Please check your model provider's documentation for the current context window size "
            "and specify it in the configuration."
        )

    # The provider must have declared metadata so the web UI can render a
    # form for it
    if config_create.provider not in declared_provider_names():
        raise ControllerBadRequestError(
            f"Unsupported LLM provider '{config_create.provider}'. "
            f"Declared providers: {', '.join(declared_provider_names())}"
        )

    try:
        # Extract config fields (excluding table-level fields)
        config_fields = config_create.model_dump(exclude={"name", "model_type", "is_default"})
        new_config = await llm_repo.create_group_config(
            group_id,
            config_create.name,
            config_create.model_type,
            config_fields,
            is_default=bool(config_create.is_default),
        )

        return schemas.LLMModelConfigResponse(
            config_id=new_config.config_id,
            name=new_config.name,
            model_type=new_config.model_type,
            config=_filter_api_key_from_config(new_config.config),
            user_id=new_config.user_id,
            group_id=new_config.group_id,
            is_default=new_config.is_default,
            version=new_config.version,
            created_at=new_config.created_at,
            updated_at=new_config.updated_at,
        )
    except ValueError as e:
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to create LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create LLM model configuration: {e}"
        )


@router.put(
    "/groups/{group_id}/llm-model-configs/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("Group.Modify"))],
)
async def update_group_llm_model_config(
    group_id: UUID,
    config_id: UUID,
    config_update: schemas.LLMModelConfigUpdate,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Update a group's LLM model configuration.
    Supports optimistic locking via expected_version field.

    Required privilege: Group.Modify
    """

    # Reject switching to a provider without declared metadata. A legacy
    # config with an unknown provider may still be saved unchanged.
    stored_config = await llm_repo.get_group_config(config_id)
    if stored_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
        )
    new_provider = config_update.provider
    if (
        new_provider
        and new_provider != (stored_config.config or {}).get("provider")
        and new_provider not in declared_provider_names()
    ):
        raise ControllerBadRequestError(
            f"Unsupported LLM provider '{new_provider}'. Declared providers: {', '.join(declared_provider_names())}"
        )

    try:
        # Build updates dict with only non-None values
        updates = {k: v for k, v in config_update.model_dump().items() if v is not None}

        # Extract expected_version for optimistic locking
        expected_version = updates.pop("expected_version", None)

        updated_config = await llm_repo.update_group_config(
            config_id, group_id, updates, expected_version=expected_version
        )

        if not updated_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )

        return schemas.LLMModelConfigResponse(
            config_id=updated_config.config_id,
            name=updated_config.name,
            model_type=updated_config.model_type,
            config=_filter_api_key_from_config(updated_config.config),
            user_id=updated_config.user_id,
            group_id=updated_config.group_id,
            is_default=updated_config.is_default,
            version=updated_config.version,
            created_at=updated_config.created_at,
            updated_at=updated_config.updated_at,
        )
    except HTTPException:
        raise
    except ValueError as e:
        # Handle optimistic lock errors
        if "Concurrent modification" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to update LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update LLM model configuration"
        )


@router.delete(
    "/groups/{group_id}/llm-model-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Group.Modify"))],
)
async def delete_group_llm_model_config(
    group_id: UUID,
    config_id: UUID,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> None:
    """
    Delete a group's LLM model configuration.

    Required privilege: Group.Modify
    """

    try:
        success = await llm_repo.delete_group_config(config_id, group_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete LLM model configuration"
        )


@router.put(
    "/groups/{group_id}/llm-model-configs/default/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("Group.Modify"))],
)
async def set_group_default_llm_model_config(
    group_id: UUID,
    config_id: UUID,
    llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository)),
) -> schemas.LLMModelConfigResponse:
    """
    Set a group's default LLM model configuration.

    Required privilege: Group.Modify
    """

    try:
        success = await llm_repo.set_group_default_config(group_id, config_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )

        # Get the updated config
        config = await llm_repo.get_group_config(config_id)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM model configuration '{config_id}' not found"
            )
        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            name=config.name,
            model_type=config.model_type,
            config=_filter_api_key_from_config(config.config),
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            version=config.version,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to set default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set default LLM model configuration"
        )
