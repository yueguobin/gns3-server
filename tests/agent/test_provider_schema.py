"""
Tests for the provider schema registry.

The registry is UI metadata: per-provider field descriptors and
capabilities. A consistency test locks the capabilities to the runtime
behavior constants in model_factory so the two cannot drift apart.
"""

from typing import Any

from gns3server.agent.gns3_copilot import provider_schema
from gns3server.agent.gns3_copilot.agent import model_factory


def test_anthropic_hides_sampling_and_hints_bare_origin() -> None:
    schema = provider_schema.provider_schema("anthropic")

    assert schema is not None
    field_names = [f["name"] for f in schema["fields"]]
    # The Anthropic API rejects sampling parameters on every model
    assert "temperature" not in field_names
    assert "request_timeout" in field_names

    base_url = next(f for f in schema["fields"] if f["name"] == "base_url")
    assert base_url["placeholder"] == "https://api.anthropic.com"
    assert "Bare origin only" in (base_url["help"] or "")


def test_deepseek_keeps_temperature_and_documents_v1() -> None:
    schema = provider_schema.provider_schema("deepseek")

    assert schema is not None
    field_names = [f["name"] for f in schema["fields"]]
    assert "temperature" in field_names
    base_url = next(f for f in schema["fields"] if f["name"] == "base_url")
    assert base_url["placeholder"] == "https://api.deepseek.com/v1"


def test_unknown_provider_has_no_schema() -> None:
    assert provider_schema.provider_schema("ollama") is None
    assert provider_schema.provider_schema("mistral") is None


def test_available_schemas_is_declared_intersect_installed(monkeypatch) -> None:
    installed = {"langchain_deepseek": True, "langchain_anthropic": False}

    def fake_find_spec(module_name: str) -> object:
        return object() if installed.get(module_name, False) else None

    monkeypatch.setattr(provider_schema.importlib.util, "find_spec", fake_find_spec)
    schemas: list[dict[str, Any]] = provider_schema.available_provider_schemas()

    assert [s["provider"] for s in schemas] == ["deepseek"]


def test_available_schemas_provider_filter() -> None:
    schemas = provider_schema.available_provider_schemas("anthropic")

    assert len(schemas) == 1
    assert schemas[0]["provider"] == "anthropic"


def test_available_schemas_ignores_unknown_provider() -> None:
    assert provider_schema.available_provider_schemas("bogus") == []


def test_registry_capabilities_match_model_factory() -> None:
    """Single-source-of-truth guard: registry capabilities and the runtime
    provider constants in model_factory must never drift apart."""
    for provider, entry in provider_schema.PROVIDER_REGISTRY.items():
        capabilities = entry["capabilities"]
        if capabilities["sampling"]:
            assert provider not in model_factory._NO_SAMPLING_PARAMS_PROVIDERS
        else:
            assert provider in model_factory._NO_SAMPLING_PARAMS_PROVIDERS
        if capabilities["request_controls"]:
            assert provider in model_factory._REQUEST_CONTROL_PROVIDERS
