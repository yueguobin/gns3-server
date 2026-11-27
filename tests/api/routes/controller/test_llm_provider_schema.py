"""
Tests for the LLM provider schema endpoint and provider validation on save.

GET /v3/access/llm-model-configs/provider-schema returns field descriptors
for declared AND installed providers. Saving a configuration rejects
providers without declared metadata; legacy configs keep an unknown
provider as long as it is not switched.
"""

import os

import pytest
import pytest_asyncio

from gns3server.config import Config
from gns3server.services.authentication import DEFAULT_JWT_SECRET_KEY

pytestmark = pytest.mark.asyncio


def _config_payload(provider: str) -> dict:
    return {
        "name": f"cfg-{provider}",
        "model_type": "text",
        "provider": provider,
        "base_url": "https://api.deepseek.com/v1" if provider == "deepseek" else "https://api.example.com",
        "model": "deepseek-flash",
        "api_key": "test-key",
        "context_limit": 128,
    }


class TestProviderSchemaEndpoint:
    async def test_lists_declared_and_installed_providers(self, client, app) -> None:
        response = await client.get(app.url_path_for("get_llm_provider_schemas"))

        assert response.status_code == 200
        data = response.json()
        providers = {p["provider"]: p for p in data["providers"]}
        assert data["total"] == len(data["providers"])
        assert "deepseek" in providers
        assert "anthropic" in providers
        # Not declared in the registry: never offered, installed or not
        assert "ollama" not in providers
        assert "aws" not in providers

    async def test_anthropic_schema_hides_temperature(self, client, app) -> None:
        response = await client.get(app.url_path_for("get_llm_provider_schemas") + "?provider=anthropic")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        field_names = [f["name"] for f in data["providers"][0]["fields"]]
        assert "temperature" not in field_names

    async def test_unknown_provider_filter_is_empty(self, client, app) -> None:
        response = await client.get(app.url_path_for("get_llm_provider_schemas") + "?provider=bogus")

        assert response.status_code == 200
        assert response.json() == {"providers": [], "total": 0}

    async def test_base_url_and_context_limit_carry_defaults(self, client, app) -> None:
        """The web UI pre-fills from field.default; placeholder is hint text only."""
        response = await client.get(app.url_path_for("get_llm_provider_schemas"))

        assert response.status_code == 200
        for provider in response.json()["providers"]:
            fields = {f["name"]: f for f in provider["fields"]}
            assert fields["base_url"]["default"]
            assert fields["context_limit"]["default"] == 1000

    async def test_deepseek_model_is_enumerated_dropdown(self, client, app) -> None:
        response = await client.get(app.url_path_for("get_llm_provider_schemas") + "?provider=deepseek")

        assert response.status_code == 200
        fields = {f["name"]: f for f in response.json()["providers"][0]["fields"]}
        assert fields["model"]["type"] == "select"
        assert fields["model"]["options"] == ["deepseek-flash", "deepseek-v4-pro"]


class TestProviderValidationOnSave:
    # The table allows one config row per user (UNIQUE constraint), so the
    # tests in this class share a single created row.
    @pytest_asyncio.fixture(loop_scope="class", scope="class")
    @classmethod
    async def deepseek_config(cls, client, app, test_user) -> dict:
        # A freshly created app generates its own JWT secret file; pin it
        # to the default key so the class-scoped bearer token is accepted
        # even when this class runs first (stable_jwt_secret pattern).
        path = os.path.join(os.path.dirname(Config.instance()._main_config_file), "gns3_jwt_secret_key")
        with open(path, "w") as f:
            f.write(DEFAULT_JWT_SECRET_KEY)

        url = app.url_path_for("create_user_llm_model_config", user_id=str(test_user.user_id))
        response = await client.post(url, json=_config_payload("deepseek"))
        assert response.status_code == 201, response.text
        return response.json()

    async def _current_version(self, client, app, test_user) -> int:
        """Update tests mutate the shared row, so always PUT against the
        version that is current on the server."""
        url = app.url_path_for("get_user_own_llm_model_configs", user_id=str(test_user.user_id))
        response = await client.get(url)
        assert response.status_code == 200, response.text
        return response.json()[0]["version"]

    async def test_create_rejects_undeclared_provider(self, client, app, test_user) -> None:
        url = app.url_path_for("create_user_llm_model_config", user_id=str(test_user.user_id))
        response = await client.post(url, json=_config_payload("ollama"))

        assert response.status_code == 400
        assert "Unsupported LLM provider" in response.json()["message"]

    async def test_created_config_has_declared_provider(self, deepseek_config) -> None:
        assert deepseek_config["config"]["provider"] == "deepseek"

    async def test_update_rejects_switching_to_undeclared_provider(
        self, client, app, test_user, deepseek_config
    ) -> None:
        version = await self._current_version(client, app, test_user)
        url = app.url_path_for(
            "update_user_llm_model_config", user_id=str(test_user.user_id), config_id=deepseek_config["config_id"]
        )
        response = await client.put(
            url,
            json={"provider": "mistral", "expected_version": version},
        )

        assert response.status_code == 400
        assert "Unsupported LLM provider" in response.json()["message"]

    async def test_update_allows_unchanged_provider(self, client, app, test_user, deepseek_config) -> None:
        version = await self._current_version(client, app, test_user)
        url = app.url_path_for(
            "update_user_llm_model_config", user_id=str(test_user.user_id), config_id=deepseek_config["config_id"]
        )
        response = await client.put(
            url,
            json={"provider": "deepseek", "expected_version": version},
        )

        assert response.status_code == 200
        assert response.json()["config"]["provider"] == "deepseek"

    async def test_update_normalizes_null_string_numbers(self, client, app, test_user, deepseek_config) -> None:
        """The web UI serializes empty form fields as the string 'null'."""
        version = await self._current_version(client, app, test_user)
        url = app.url_path_for(
            "update_user_llm_model_config", user_id=str(test_user.user_id), config_id=deepseek_config["config_id"]
        )
        response = await client.put(
            url,
            json={
                "provider": "deepseek",
                "max_steps": "null",
                "request_timeout": "null",
                "expected_version": version,
            },
        )

        assert response.status_code == 200, response.text
