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
    assert base_url["default"] == "https://api.anthropic.com"
    assert "Bare origin only" in (base_url["help"] or "")

    context_limit = next(f for f in schema["fields"] if f["name"] == "context_limit")
    assert context_limit["default"] == 1000

    # Anthropic's catalog is larger, so model stays free text
    model = next(f for f in schema["fields"] if f["name"] == "model")
    assert model["type"] == "string"
    assert "options" not in model


def test_deepseek_keeps_temperature_and_documents_v1() -> None:
    schema = provider_schema.provider_schema("deepseek")

    assert schema is not None
    field_names = [f["name"] for f in schema["fields"]]
    assert "temperature" in field_names
    base_url = next(f for f in schema["fields"] if f["name"] == "base_url")
    assert base_url["placeholder"] == "https://api.deepseek.com/v1"
    assert base_url["default"] == "https://api.deepseek.com/v1"

    # Model names are never hardcoded; the catalog comes live from the
    # provider's models API, so the field stays free text as a fallback
    model = next(f for f in schema["fields"] if f["name"] == "model")
    assert model["type"] == "string"
    assert "options" not in model

    context_limit = next(f for f in schema["fields"] if f["name"] == "context_limit")
    assert context_limit["default"] == 1000


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


def test_build_models_request_anthropic_uses_x_api_key() -> None:
    built = provider_schema.build_models_request("anthropic", "sk-test")

    assert built is not None
    url, headers = built
    assert url == "https://api.anthropic.com/v1/models"
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"]
    assert "Authorization" not in headers


def test_build_models_request_deepseek_uses_bearer() -> None:
    built = provider_schema.build_models_request("deepseek", "sk-test")

    assert built is not None
    url, headers = built
    assert url == "https://api.deepseek.com/v1/models"
    assert headers["Authorization"] == "Bearer sk-test"


def test_build_models_request_form_base_url_wins() -> None:
    built = provider_schema.build_models_request("anthropic", "sk-test", "https://proxy.corp/api/")

    assert built is not None
    url, _ = built
    assert url == "https://proxy.corp/api/v1/models"


def test_build_models_request_unknown_provider_is_none() -> None:
    assert provider_schema.build_models_request("ollama", "sk-test") is None


def test_normalize_models_payload_handles_both_shapes() -> None:
    anthropic_payload = {
        "data": [
            {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "max_input_tokens": 1000000},
            {"id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5", "max_input_tokens": 1000000},
        ]
    }
    models = provider_schema.normalize_models_payload(anthropic_payload)
    assert models[0] == {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "max_input_tokens": 1000000}

    openai_payload = {"data": [{"id": "deepseek-flash", "object": "model"}, {"id": "deepseek-v4-pro"}]}
    models = provider_schema.normalize_models_payload(openai_payload)
    assert models == [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]


def test_normalize_models_payload_skips_garbage_entries() -> None:
    assert provider_schema.normalize_models_payload({}) == []
    assert provider_schema.normalize_models_payload({"data": [None, {"id": ""}, "junk"]}) == []
