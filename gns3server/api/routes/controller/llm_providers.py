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
API routes for LLM provider metadata.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gns3server import schemas

from .dependencies.authentication import get_current_active_user

import logging

log = logging.getLogger(__name__)


router = APIRouter()

# Computed once per process: the list only changes if the installed langchain
# stack changes, which requires a server restart anyway.
_providers_cache: Optional[schemas.LLMProviderList] = None


def _load_llm_providers() -> schemas.LLMProviderList:
    """
    Build the list of LLM model providers supported by the installed langchain stack.

    Delegates the enumeration to the GNS3-copilot utils package, which reads
    langchain's built-in provider registry (the same registry used by
    init_chat_model to instantiate chat models from user LLM model
    configurations) and probes each provider package with importlib.

    Raises:
        ImportError: If langchain is not installed (ai-features extra).
        RuntimeError: If the installed langchain version does not expose
            the (private) provider registry.
    """

    from gns3server.agent.gns3_copilot.utils.llm_providers import list_llm_providers

    return schemas.LLMProviderList(**list_llm_providers())


@router.get(
    "/llm/providers",
    response_model=schemas.LLMProviderList,
    dependencies=[Depends(get_current_active_user)]
)
def get_llm_providers() -> schemas.LLMProviderList:
    """
    Return the LLM model providers supported by the langchain stack installed on this server.

    Required privilege: None (authenticated users only)
    """

    global _providers_cache
    if _providers_cache is None:
        try:
            _providers_cache = _load_llm_providers()
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="langchain is not available. Install AI dependencies with: pip install gns3-server[ai-features]"
            )
        except RuntimeError as e:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(e))
    return _providers_cache


@router.post(
    "/llm/models",
    response_model=schemas.LLMModelList,
)
async def list_llm_models(
    request: Request,
    body: Optional[schemas.LLMModelsRequest] = None,
    current_user: schemas.User = Depends(get_current_active_user),
) -> schemas.LLMModelList:
    """
    List the models available from an LLM provider.

    Connection parameters may be supplied in the body (e.g. while filling in
    an unsaved configuration form); when omitted, the requester's default LLM
    model configuration is used. The API key only authenticates the upstream
    request and is never returned.

    Required privilege: None (authenticated users only)
    """

    provider = base_url = api_key = None
    if body:
        provider, base_url, api_key = body.provider, body.base_url, body.api_key

    if not provider:
        from gns3server.agent.gns3_copilot.utils.llm_config_helper import get_user_llm_config_with_app

        config = await get_user_llm_config_with_app(current_user.user_id, request.app)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No default LLM model configuration found for the current user",
            )
        provider = config.get("provider")
        base_url = config.get("base_url")
        api_key = config.get("api_key")

    try:
        from gns3server.agent.gns3_copilot.utils.llm_providers import list_provider_models

        data = await list_provider_models(provider, base_url, api_key)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="langchain is not available. Install AI dependencies with: pip install gns3-server[ai-features]"
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    return schemas.LLMModelList(**data)
