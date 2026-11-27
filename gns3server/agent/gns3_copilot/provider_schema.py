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
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with GNS3-Copilot. If not, see <https://www.gnu.org/licenses/>.
#
# Copyright (C) 2025 Yue Guobin (岳国宾)
# Author: Yue Guobin (岳国宾)
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""
Provider schema registry for LLM model configurations.

Declares, per provider, the configuration fields the web UI should render
and the provider capabilities. Providers differ in more than their API
shape: the current Anthropic API rejects sampling parameters entirely,
base_url semantics vary (bare origin vs. URL with /v1), and only some
chat models accept the OpenAI-style timeout controls.

The endpoint response is the intersection of declared providers and
installed langchain integration packages, so a provider appears only when
its metadata exists AND its package is installed. Saving a configuration
validates the provider against the declared set; legacy configurations
with an unknown provider keep working at runtime but cannot switch to
another unknown provider.

This registry is UI metadata only. Runtime behavior lives in
agent/model_factory.py and is kept consistent with this registry by a
dedicated test (tests/agent/test_provider_schema.py).
"""

import importlib.util
from typing import Any, Optional

# Field types the web UI knows how to render.
FIELD_TYPES = ("string", "int", "float", "bool", "secret", "select")

# Fields shared by every provider. ``temperature`` and ``request_timeout``
# are dropped per provider by capability (see _PROVIDER_CAPABILITY_FILTERS).
_COMMON_FIELDS: list[dict[str, Any]] = [
    {
        "name": "model",
        "type": "string",
        "required": True,
        "label": "Model",
        "help": "Model name as spelled by the provider, e.g. deepseek-flash, claude-opus-5-5",
    },
    {
        "name": "api_key",
        "type": "secret",
        "required": False,
        "label": "API key",
        "help": "API key from the provider console. Required for cloud APIs, may be empty for local endpoints.",
    },
    {
        "name": "base_url",
        "type": "string",
        "required": True,
        "label": "Base URL",
    },
    {
        "name": "context_limit",
        "type": "int",
        "required": True,
        "label": "Context limit (K tokens)",
        "help": "Model context window in K tokens (1000 = 1,000,000 tokens). Check the provider docs for the current value.",
        "default": 1000,
    },
    {
        "name": "context_strategy",
        "type": "select",
        "required": False,
        "label": "Context strategy",
        "help": "How aggressively old messages are trimmed: conservative (60%), balanced (75%), aggressive (85%)",
        "default": "balanced",
        "options": ["conservative", "balanced", "aggressive"],
    },
    {
        "name": "temperature",
        "type": "float",
        "required": False,
        "label": "Temperature",
        "help": "Sampling randomness, 0.0 to 2.0",
        "default": 0.7,
    },
    {
        "name": "max_tokens",
        "type": "int",
        "required": False,
        "label": "Max tokens",
        "advanced": True,
    },
    {
        "name": "copilot_mode",
        "type": "select",
        "required": False,
        "label": "Copilot mode",
        "default": "teaching_assistant",
        "options": ["teaching_assistant", "lab_automation_assistant", "troubleshooting_injection"],
        "advanced": True,
    },
    {
        "name": "max_steps",
        "type": "int",
        "required": False,
        "label": "Max steps per turn",
        "help": "LangGraph super-steps per copilot turn (1 LLM call + 1 tool run = 2 steps)",
        "advanced": True,
    },
    {
        "name": "request_timeout",
        "type": "float",
        "required": False,
        "label": "Request timeout (seconds)",
        "help": "Per-request timeout. Default 120s: a silent connection fails fast instead of waiting for the SDK default of 600s",
        "default": 120,
        "advanced": True,
    },
]

# Fields hidden when the capability is False.
_PROVIDER_CAPABILITY_FILTERS = {
    "temperature": "sampling",
    "request_timeout": "request_controls",
}

# Provider registry. Only providers with tested metadata are declared here;
# add the matching integration package to ai-requirements.txt when adding
# a provider.
PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "deepseek": {
        "display_name": "DeepSeek",
        "integration_module": "langchain_deepseek",
        "capabilities": {
            "sampling": True,
            "request_controls": True,
            "reasoning_toggle": True,
        },
        "placeholders": {
            "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com/v1",
        },
        # Pre-filled values (placeholder is only greyed hint text, never data)
        "defaults": {
            "base_url": "https://api.deepseek.com/v1",
        },
        # Structural per-field patches: the catalog is short and stable
        # enough to enumerate, so the web UI renders it as a dropdown.
        "field_overrides": {
            "model": {
                "type": "select",
                "options": ["deepseek-flash", "deepseek-v4-pro"],
            },
        },
    },
    "anthropic": {
        "display_name": "Anthropic",
        "integration_module": "langchain_anthropic",
        # The Anthropic API (2026-10-21+) rejects sampling parameters on
        # every model, so the UI must not offer a temperature field.
        "capabilities": {
            "sampling": False,
            "request_controls": True,
            "reasoning_toggle": False,
        },
        "placeholders": {
            "model": "claude-opus-5-5",
            "base_url": "https://api.anthropic.com",
        },
        # Pre-filled values (placeholder is only greyed hint text, never data)
        "defaults": {
            "base_url": "https://api.anthropic.com",
        },
        "field_help": {
            # The SDK appends the API path itself; a full endpoint URL
            # produces a doubled path and confusing failures.
            "base_url": "Bare origin only - the SDK appends the API path (e.g. /v1/messages). Do not include it.",
        },
    },
}


def declared_provider_names() -> list[str]:
    """Names of the providers that have declared metadata."""
    return list(PROVIDER_REGISTRY)


def _integration_installed(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def provider_schema(provider: str) -> Optional[dict[str, Any]]:
    """Composed schema view for one provider, or None if not declared."""
    entry = PROVIDER_REGISTRY.get(provider)
    if entry is None:
        return None

    capabilities = entry["capabilities"]
    placeholders = entry.get("placeholders", {})
    field_help = entry.get("field_help", {})
    defaults = entry.get("defaults", {})
    field_overrides = entry.get("field_overrides", {})

    fields: list[dict[str, Any]] = []
    for field in _COMMON_FIELDS:
        if not capabilities.get(_PROVIDER_CAPABILITY_FILTERS.get(field["name"], ""), True):
            continue
        field = dict(field)
        if field["name"] in placeholders:
            field["placeholder"] = placeholders[field["name"]]
        if field["name"] in field_help:
            field["help"] = field_help[field["name"]]
        if field["name"] in defaults:
            field["default"] = defaults[field["name"]]
        if field["name"] in field_overrides:
            field.update(field_overrides[field["name"]])
        fields.append(field)

    return {
        "provider": provider,
        "display_name": entry["display_name"],
        "integration_module": entry["integration_module"],
        "capabilities": dict(capabilities),
        "fields": fields,
    }


def available_provider_schemas(provider: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Schemas the web UI may render: declared providers whose langchain
    integration package is installed on this server.

    :param provider: Optional filter for a single provider.
    """
    names = [provider] if provider else declared_provider_names()
    schemas: list[dict[str, Any]] = []
    for name in names:
        if name not in PROVIDER_REGISTRY:
            continue
        if not _integration_installed(PROVIDER_REGISTRY[name]["integration_module"]):
            continue
        schema = provider_schema(name)
        if schema:
            schemas.append(schema)
    return schemas
