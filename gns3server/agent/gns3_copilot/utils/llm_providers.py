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
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with GNS3-Copilot. If not, see <https://www.gnu.org/licenses/>.
#
# Copyright (C) 2026 Yue Guobin (岳国宾)
# Author: Yue Guobin (岳国宾)
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""

LLM Provider Enumeration for GNS3 Copilot

This module enumerates the LLM model providers supported by the installed
langchain stack. The provider keys are exactly the values accepted by
init_chat_model's model_provider parameter (the same factory the copilot
uses to instantiate chat models from user LLM model configurations).

Usage:
    from gns3server.agent.gns3_copilot.utils.llm_providers import (
        list_llm_providers,
    )

    data = list_llm_providers()
    for provider in data["providers"]:
        print(provider["name"], provider["installed"])
"""

import importlib
import importlib.util
import json
import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

logger = logging.getLogger(__name__)


# Default public endpoints per provider key; used when the caller does not
# supply a base_url. Providers not listed here require an explicit base_url.
_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "xai": "https://api.x.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "perplexity": "https://api.perplexity.ai",
    "mistralai": "https://api.mistral.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "upstage": "https://api.upstage.ai/v1/solar",
    "ollama": "http://localhost:11434",
    "anthropic": "https://api.anthropic.com",
}

_GOOGLE_GENAI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


async def _fetch_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    GET a JSON document with a short timeout.

    Raises:
        RuntimeError: If the request fails or returns a non-200 status.
    """

    import aiohttp

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                body = await response.text()
                if response.status != 200:
                    detail = body[:200] if body else response.reason
                    raise RuntimeError(f"{url} returned {response.status}: {detail}")
                return json.loads(body)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Could not reach {url}: {e}") from e


def _models_result(provider: str, base_url: Optional[str], models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sort and package a model list into the list_provider_models result format.
    """

    for m in models:
        m.setdefault("name", None)
        m.setdefault("owned_by", None)
        m.setdefault("context_length", None)
    models.sort(key=lambda m: m["model_id"])
    return {"provider": provider, "base_url": base_url, "models": models}


async def list_provider_models(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List the models available from an LLM provider.

    The API key (when required by the provider) is only used to authenticate
    the upstream request; it is never included in the result.

    Args:
        provider: Provider key (as returned by list_llm_providers)
        base_url: Provider base URL; defaults to the provider's public
            endpoint when known
        api_key: API key for providers that require one

    Returns:
        Dictionary with "provider", "base_url" and "models" (a list of
        {"model_id", "name", "owned_by", "context_length"} dicts, sorted
        by model_id).

    Raises:
        ValueError: If the provider has no known default base URL and none
            was supplied, or the provider is not supported.
        RuntimeError: If the provider endpoint cannot be reached or rejects
            the request.
    """

    if provider == "ollama":
        resolved_base = base_url or _DEFAULT_BASE_URLS["ollama"]
        data = await _fetch_json(f"{resolved_base.rstrip('/')}/api/tags", {})
        models = [
            {"model_id": m.get("name") or m.get("model", ""), "name": m.get("model")}
            for m in data.get("models", [])
        ]
        return _models_result(provider, resolved_base, models)

    if provider == "anthropic":
        resolved_base = base_url or _DEFAULT_BASE_URLS["anthropic"]
        headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        data = await _fetch_json(f"{resolved_base.rstrip('/')}/v1/models?limit=1000", headers)
        models = [
            {"model_id": m.get("id", ""), "name": m.get("display_name")}
            for m in data.get("data", [])
        ]
        return _models_result(provider, resolved_base, models)

    if provider == "google_genai":
        headers = {}
        if api_key:
            headers["x-goog-api-key"] = api_key
        data = await _fetch_json(f"{_GOOGLE_GENAI_MODELS_URL}?pageSize=1000", headers)
        models = [
            {
                "model_id": m.get("name", "").removeprefix("models/"),
                "name": m.get("displayName"),
                "context_length": m.get("inputTokenLimit"),
            }
            for m in data.get("models", [])
        ]
        return _models_result(provider, None, models)

    if provider in ("azure_openai", "azure_ai", "bedrock", "anthropic_bedrock", "bedrock_converse"):
        # These providers authenticate with deployment-specific or signed
        # credentials and have no uniform list-models endpoint.
        raise ValueError(f"Model listing is not supported for provider '{provider}'")

    # Everything else is queried through the OpenAI-compatible /models
    # endpoint (this also covers aggregator platforms such as OpenRouter).
    resolved_base = base_url or _DEFAULT_BASE_URLS.get(provider)
    if not resolved_base:
        raise ValueError(f"No default base URL known for provider '{provider}', base_url is required")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = await _fetch_json(f"{resolved_base.rstrip('/')}/models", headers)
    models = [
        {
            "model_id": m.get("id", ""),
            "name": m.get("name"),
            "owned_by": m.get("owned_by"),
            "context_length": m.get("context_length"),
        }
        for m in data.get("data", [])
    ]
    return _models_result(provider, resolved_base, models)


def _introspect_chat_model_params(cls: type) -> List[Dict[str, Any]]:
    """
    Extract the configurable parameters of a langchain chat model class.

    Walks the pydantic field definitions of the class, excluding the generic
    runnable plumbing inherited from BaseChatModel (callbacks, cache, tags,
    ...). Both the field name and its alias (when set) are reported: chat
    model classes enable populate_by_name, so either keyword is accepted
    (e.g. ChatOpenAI's model_name is also passed as 'model'). Secret-typed
    fields are flagged and their defaults are never included.

    Args:
        cls: A langchain chat model class (pydantic model)

    Returns:
        List of parameter dicts with "name", "alias", "type", "required",
        "default" and "secret" keys.
    """

    from langchain_core.language_models import BaseChatModel

    # Fields every chat model inherits: runnable plumbing, not provider config
    plumbing_fields = set(BaseChatModel.model_fields)

    params = []
    for field_name, field_info in cls.model_fields.items():
        if field_name in plumbing_fields:
            continue

        annotation = str(field_info.annotation)
        # "<class 'float'>" -> "float"; drop common module prefixes
        annotation = annotation.replace("<class '", "").replace("'>", "")
        for prefix in ("pydantic.types.", "typing.", "langchain_core.", "collections.abc."):
            annotation = annotation.replace(prefix, "")

        secret = "Secret" in annotation
        default: Optional[str] = None
        if not field_info.is_required() and not secret:
            raw_default = field_info.default
            if isinstance(raw_default, (str, int, float, bool)):
                default = str(raw_default)

        params.append(
            {
                "name": field_name,
                "alias": field_info.alias,
                "type": annotation,
                "required": field_info.is_required(),
                "default": default,
                "secret": secret,
            }
        )
    return params


def list_llm_providers() -> Dict[str, Any]:
    """
    Enumerate the LLM model providers supported by the installed langchain stack.

    Reads langchain's built-in provider registry (the same registry used by
    init_chat_model) and probes the availability of each provider package
    with importlib, without importing the packages themselves.

    Returns:
        Dictionary with:
        - "langchain_version": version of the installed langchain library
        - "providers": list of {"name", "pip_package", "model_class",
          "installed", "parameters"} dicts, sorted by name. "parameters"
          (the introspected chat model parameters) is only present for
          installed providers whose package could be imported; None
          otherwise.

    Raises:
        ImportError: If langchain is not installed.
        RuntimeError: If the installed langchain version does not expose
            the (private) provider registry.
    """

    import langchain
    from langchain.chat_models import base as chat_models_base

    builtin_providers = getattr(chat_models_base, "_BUILTIN_PROVIDERS", None)
    if not builtin_providers:
        # Private API: langchain may rename or drop it in a future version.
        raise RuntimeError(
            "The installed langchain version does not expose the provider registry "
            "(_BUILTIN_PROVIDERS)"
        )

    providers = []
    for name, provider_spec in sorted(builtin_providers.items()):
        module_path, model_class = provider_spec[0], provider_spec[1]
        # Registry entries may point to a submodule (e.g.
        # "langchain_azure_ai.chat_models"); only the top-level package
        # determines availability and pip name.
        top_level_module = module_path.split(".")[0]
        try:
            installed = importlib.util.find_spec(top_level_module) is not None
        except Exception as e:
            logger.warning("Could not probe availability of '%s': %s", top_level_module, e)
            installed = False

        parameters: Optional[List[Dict[str, Any]]] = None
        if installed:
            try:
                module = importlib.import_module(module_path)
                parameters = _introspect_chat_model_params(getattr(module, model_class))
            except Exception as e:
                # A provider package that probes present but fails to import
                # must not break the whole listing.
                logger.warning("Could not introspect chat model of provider '%s': %s", name, e)

        providers.append(
            {
                "name": name,
                "pip_package": top_level_module.replace("_", "-"),
                "model_class": model_class,
                "installed": installed,
                "parameters": parameters,
            }
        )

    return {"langchain_version": langchain.__version__, "providers": providers}
