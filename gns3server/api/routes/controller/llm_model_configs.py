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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from uuid import UUID
from typing import List

from gns3server import schemas
from gns3server.controller.controller_error import (
    ControllerError,
    ControllerBadRequestError,
    ControllerNotFoundError,
)

from gns3server.db.repositories.llm_model_configs import LLMModelConfigsRepository
from gns3server.db.repositories.users import UsersRepository

from .dependencies.database import get_repository
from .dependencies.rbac import has_privilege

import logging

log = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# User LLM Model Configuration Endpoints
# ============================================================================

@router.get(
    "/users/{user_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigInheritedResponse,
    dependencies=[Depends(has_privilege("User.Audit"))]
)
async def get_user_llm_model_configs(
        user_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigInheritedResponse:
    """
    Get user's effective LLM model configurations (own + inherited from groups).

    Required privilege: User.Audit
    """

    try:
        result = await llm_repo.get_user_effective_configs(user_id)
        return schemas.LLMModelConfigInheritedResponse(
            configs=result["configs"],
            default_config=result.get("default_config"),
            total=len(result["configs"])
        )
    except Exception as e:
        log.error(f"Failed to retrieve user LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve LLM model configurations"
        )


@router.get(
    "/users/{user_id}/llm-model-configs/own",
    response_model=List[schemas.LLMModelConfigResponse],
    dependencies=[Depends(has_privilege("User.Audit"))]
)
async def get_user_own_llm_model_configs(
        user_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> List[schemas.LLMModelConfigResponse]:
    """
    Get user's own LLM model configurations (excluding inherited ones).

    Required privilege: User.Audit
    """

    try:
        configs = await llm_repo.get_user_configs(user_id)
        return [
            schemas.LLMModelConfigResponse(
                config_id=config.config_id,
                config=config.config,
                user_id=config.user_id,
                group_id=config.group_id,
                is_default=config.is_default,
                created_at=config.created_at,
                updated_at=config.updated_at
            )
            for config in configs
        ]
    except Exception as e:
        log.error(f"Failed to retrieve user's own LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve LLM model configurations"
        )


@router.post(
    "/users/{user_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_privilege("User.Modify"))]
)
async def create_user_llm_model_config(
        user_id: UUID,
        config_create: schemas.LLMModelConfigCreate,
        users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Create a new LLM model configuration for a user.

    Required privilege: User.Modify
    """

    # Verify user exists
    user = await users_repo.get_user(user_id)
    if not user:
        raise ControllerNotFoundError(f"User '{user_id}' not found")

    try:
        config_data = config_create.model_dump(exclude={"is_default"})
        new_config = await llm_repo.create_user_config(
            user_id,
            config_data,
            is_default=config_create.is_default
        )

        return schemas.LLMModelConfigResponse(
            config_id=new_config.config_id,
            config=new_config.config,
            user_id=new_config.user_id,
            group_id=new_config.group_id,
            is_default=new_config.is_default,
            created_at=new_config.created_at,
            updated_at=new_config.updated_at
        )
    except ValueError as e:
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to create LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create LLM model configuration"
        )


@router.put(
    "/users/{user_id}/llm-model-configs/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("User.Modify"))]
)
async def update_user_llm_model_config(
        user_id: UUID,
        config_id: UUID,
        config_update: schemas.LLMModelConfigUpdate,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Update a user's LLM model configuration.

    Required privilege: User.Modify
    """

    try:
        # Build updates dict with only non-None values
        updates = {k: v for k, v in config_update.model_dump().items() if v is not None}

        updated_config = await llm_repo.update_user_config(config_id, user_id, updates)

        if not updated_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )

        return schemas.LLMModelConfigResponse(
            config_id=updated_config.config_id,
            config=updated_config.config,
            user_id=updated_config.user_id,
            group_id=updated_config.group_id,
            is_default=updated_config.is_default,
            created_at=updated_config.created_at,
            updated_at=updated_config.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to update LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update LLM model configuration"
        )


@router.delete(
    "/users/{user_id}/llm-model-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("User.Modify"))]
)
async def delete_user_llm_model_config(
        user_id: UUID,
        config_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> None:
    """
    Delete a user's LLM model configuration.

    Required privilege: User.Modify
    """

    try:
        success = await llm_repo.delete_user_config(config_id, user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete LLM model configuration"
        )


@router.put(
    "/users/{user_id}/llm-model-configs/default/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("User.Modify"))]
)
async def set_user_default_llm_model_config(
        user_id: UUID,
        config_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Set a user's default LLM model configuration.

    Required privilege: User.Modify
    """

    try:
        success = await llm_repo.set_user_default_config(user_id, config_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )

        # Get the updated config
        config = await llm_repo.get_user_config(config_id)
        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            config=config.config,
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            created_at=config.created_at,
            updated_at=config.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to set default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default LLM model configuration"
        )


# ============================================================================
# Group LLM Model Configuration Endpoints
# ============================================================================

@router.get(
    "/groups/{group_id}/llm-model-configs",
    response_model=List[schemas.LLMModelConfigResponse],
    dependencies=[Depends(has_privilege("Group.Audit"))]
)
async def get_group_llm_model_configs(
        group_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> List[schemas.LLMModelConfigResponse]:
    """
    Get all LLM model configurations for a user group.

    Required privilege: Group.Audit
    """

    try:
        configs = await llm_repo.get_group_configs(group_id)
        return [
            schemas.LLMModelConfigResponse(
                config_id=config.config_id,
                config=config.config,
                user_id=config.user_id,
                group_id=config.group_id,
                is_default=config.is_default,
                created_at=config.created_at,
                updated_at=config.updated_at
            )
            for config in configs
        ]
    except Exception as e:
        log.error(f"Failed to retrieve group LLM model configs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve LLM model configurations"
        )


@router.post(
    "/groups/{group_id}/llm-model-configs",
    response_model=schemas.LLMModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_privilege("Group.Modify"))]
)
async def create_group_llm_model_config(
        group_id: UUID,
        config_create: schemas.LLMModelConfigCreate,
        users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Create a new LLM model configuration for a user group.

    Required privilege: Group.Modify
    """

    # Verify group exists
    group = await users_repo.get_user_group(group_id)
    if not group:
        raise ControllerNotFoundError(f"User group '{group_id}' not found")

    try:
        config_data = config_create.model_dump(exclude={"is_default"})
        new_config = await llm_repo.create_group_config(
            group_id,
            config_data,
            is_default=config_create.is_default
        )

        return schemas.LLMModelConfigResponse(
            config_id=new_config.config_id,
            config=new_config.config,
            user_id=new_config.user_id,
            group_id=new_config.group_id,
            is_default=new_config.is_default,
            created_at=new_config.created_at,
            updated_at=new_config.updated_at
        )
    except ValueError as e:
        raise ControllerBadRequestError(str(e))
    except Exception as e:
        log.error(f"Failed to create LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create LLM model configuration"
        )


@router.put(
    "/groups/{group_id}/llm-model-configs/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("Group.Modify"))]
)
async def update_group_llm_model_config(
        group_id: UUID,
        config_id: UUID,
        config_update: schemas.LLMModelConfigUpdate,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Update a group's LLM model configuration.

    Required privilege: Group.Modify
    """

    try:
        # Build updates dict with only non-None values
        updates = {k: v for k, v in config_update.model_dump().items() if v is not None}

        updated_config = await llm_repo.update_group_config(config_id, group_id, updates)

        if not updated_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )

        return schemas.LLMModelConfigResponse(
            config_id=updated_config.config_id,
            config=updated_config.config,
            user_id=updated_config.user_id,
            group_id=updated_config.group_id,
            is_default=updated_config.is_default,
            created_at=updated_config.created_at,
            updated_at=updated_config.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to update LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update LLM model configuration"
        )


@router.delete(
    "/groups/{group_id}/llm-model-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Group.Modify"))]
)
async def delete_group_llm_model_config(
        group_id: UUID,
        config_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> None:
    """
    Delete a group's LLM model configuration.

    Required privilege: Group.Modify
    """

    try:
        success = await llm_repo.delete_group_config(config_id, group_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete LLM model configuration"
        )


@router.put(
    "/groups/{group_id}/llm-model-configs/default/{config_id}",
    response_model=schemas.LLMModelConfigResponse,
    dependencies=[Depends(has_privilege("Group.Modify"))]
)
async def set_group_default_llm_model_config(
        group_id: UUID,
        config_id: UUID,
        llm_repo: LLMModelConfigsRepository = Depends(get_repository(LLMModelConfigsRepository))
) -> schemas.LLMModelConfigResponse:
    """
    Set a group's default LLM model configuration.

    Required privilege: Group.Modify
    """

    try:
        success = await llm_repo.set_group_default_config(group_id, config_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"LLM model configuration '{config_id}' not found"
            )

        # Get the updated config
        config = await llm_repo.get_group_config(config_id)
        return schemas.LLMModelConfigResponse(
            config_id=config.config_id,
            config=config.config,
            user_id=config.user_id,
            group_id=config.group_id,
            is_default=config.is_default,
            created_at=config.created_at,
            updated_at=config.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to set default LLM model config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default LLM model configuration"
        )
