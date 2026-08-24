#
# Copyright (C) 2026 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import pytest

from fastapi import FastAPI, status
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestLLMProviderRoutes:

    async def test_providers(self, app: FastAPI, client: AsyncClient) -> None:
        """
        Test listing the LLM providers supported by the installed langchain stack.
        """

        pytest.importorskip("langchain", reason="langchain is not installed")
        import langchain
        from langchain.chat_models import base as chat_models_base

        response = await client.get(app.url_path_for("get_llm_providers"))
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["langchain_version"] == langchain.__version__

        providers = data["providers"]
        assert len(providers) > 0
        assert len(providers) == len(chat_models_base._BUILTIN_PROVIDERS)

        names = [entry["name"] for entry in providers]
        assert names == sorted(names)

        by_name = {entry["name"]: entry for entry in providers}

        # full record check for a representative entry (module -> pip name mapping,
        # class name, guaranteed install)
        assert by_name["openai"]["pip_package"] == "langchain-openai"
        assert by_name["openai"]["model_class"] == "ChatOpenAI"
        assert by_name["openai"]["installed"] is True
        assert isinstance(by_name["openai"]["parameters"], list)
        assert len(by_name["openai"]["parameters"]) > 0

        # dotted module paths resolve to the top-level pip package
        assert by_name["azure_ai"]["pip_package"] == "langchain-azure-ai"
        assert by_name["azure_ai"]["model_class"] == "AzureAIOpenAIApiChatModel"
        assert by_name["deepseek"]["pip_package"] == "langchain-deepseek"
        assert by_name["deepseek"]["model_class"] == "ChatDeepSeek"

        # these providers are guaranteed by the ai-features extra (ai-requirements.txt)
        for guaranteed in ("anthropic", "google_genai", "bedrock", "ollama", "xai"):
            assert by_name[guaranteed]["installed"] is True
            assert len(by_name[guaranteed]["parameters"]) > 0

        # present in the registry but not guaranteed by ai-requirements.txt: only
        # assert the flag is a bool (dev machines may have extra provider packages)
        for present in ("cohere", "google_vertexai", "groq", "azure_openai"):
            assert by_name[present]["installed"] in (True, False)

        # uninstalled providers never carry introspected parameters
        for entry in providers:
            if entry["installed"] is False:
                assert entry["parameters"] is None

        # parameter introspection: field name + alias are both reported
        # (chat model classes enable populate_by_name)
        openai_params = {p["name"]: p for p in by_name["openai"]["parameters"]}
        assert openai_params["model_name"] == {
            "name": "model_name",
            "alias": "model",
            "type": "str",
            "required": False,
            "default": "gpt-3.5-turbo",
            "secret": False,
        }
        assert openai_params["openai_api_base"]["alias"] == "base_url"
        assert openai_params["temperature"]["type"] == "float | None"

        # secret-typed fields are flagged and never carry a default
        assert openai_params["openai_api_key"]["secret"] is True
        assert openai_params["openai_api_key"]["alias"] == "api_key"
        assert openai_params["openai_api_key"]["default"] is None

        # runnable plumbing inherited from BaseChatModel is filtered out
        for plumbing in ("callbacks", "cache", "tags", "metadata", "verbose"):
            assert plumbing not in openai_params

        # anthropic declares the field the other way around (name 'model',
        # alias 'model_name') and requires it
        anthropic_params = {p["name"]: p for p in by_name["anthropic"]["parameters"]}
        assert anthropic_params["model"]["required"] is True
        assert anthropic_params["model"]["alias"] == "model_name"

        # every entry is well-formed
        for entry in providers:
            assert entry["name"] and entry["pip_package"] and entry["model_class"]
            for param in entry["parameters"] or []:
                assert param["name"] and param["type"]
                assert isinstance(param["required"], bool)
                assert isinstance(param["secret"], bool)

    async def test_providers_unavailable(self, app: FastAPI, client: AsyncClient, monkeypatch) -> None:
        """
        Test that a 501 is returned when langchain is not installed.
        """

        from gns3server.api.routes.controller import llm_providers as llm_providers_route

        def _raise_import_error():
            raise ImportError("No module named 'langchain'")

        monkeypatch.setattr(llm_providers_route, "_load_llm_providers", _raise_import_error)
        monkeypatch.setattr(llm_providers_route, "_providers_cache", None)

        response = await client.get(app.url_path_for("get_llm_providers"))
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        # the HTTP exception handler formats errors with a "message" key
        assert "ai-features" in response.json()["message"]

    async def test_providers_registry_missing(self, app: FastAPI, client: AsyncClient, monkeypatch) -> None:
        """
        Test that a 501 is returned when langchain does not expose the provider registry.
        """

        from gns3server.api.routes.controller import llm_providers as llm_providers_route

        def _raise_runtime_error():
            raise RuntimeError("registry gone")

        monkeypatch.setattr(llm_providers_route, "_load_llm_providers", _raise_runtime_error)
        monkeypatch.setattr(llm_providers_route, "_providers_cache", None)

        response = await client.get(app.url_path_for("get_llm_providers"))
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        assert "registry" in response.json()["message"]

    async def test_models_explicit_params(self, app: FastAPI, client: AsyncClient, monkeypatch) -> None:
        """
        Test listing models with explicit connection parameters in the body.
        """

        from gns3server.agent.gns3_copilot.utils import llm_providers as agent_module

        captured = {}

        async def _fake_list_provider_models(provider, base_url=None, api_key=None):
            captured["provider"] = provider
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            return {
                "provider": provider,
                "base_url": base_url,
                "models": [
                    {"model_id": "m-b", "name": "Model B"},
                    {"model_id": "m-a", "name": "Model A", "owned_by": "acme", "context_length": 128000},
                ],
            }

        monkeypatch.setattr(agent_module, "list_provider_models", _fake_list_provider_models)

        response = await client.post(
            app.url_path_for("list_llm_models"),
            json={"provider": "ollama", "base_url": "http://localhost:11434", "api_key": "secret"},
        )
        assert response.status_code == status.HTTP_200_OK

        # the explicit body parameters reach the provider fetcher unchanged
        assert captured == {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "api_key": "secret",
        }

        data = response.json()
        assert data["provider"] == "ollama"
        assert data["base_url"] == "http://localhost:11434"
        models_by_id = {m["model_id"]: m for m in data["models"]}
        assert models_by_id["m-a"]["context_length"] == 128000
        assert models_by_id["m-a"]["owned_by"] == "acme"
        # the API key never appears in the response
        assert "secret" not in response.text

    async def test_models_provider_error(self, app: FastAPI, client: AsyncClient, monkeypatch) -> None:
        """
        Test that an upstream provider failure maps to a 502.
        """

        from gns3server.agent.gns3_copilot.utils import llm_providers as agent_module

        async def _raise_runtime_error(provider, base_url=None, api_key=None):
            raise RuntimeError("upstream boom")

        monkeypatch.setattr(agent_module, "list_provider_models", _raise_runtime_error)

        response = await client.post(app.url_path_for("list_llm_models"), json={"provider": "openai"})
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "upstream boom" in response.json()["message"]

    async def test_models_unsupported_provider(self, app: FastAPI, client: AsyncClient, monkeypatch) -> None:
        """
        Test that an unsupported provider or missing base URL maps to a 400.
        """

        from gns3server.agent.gns3_copilot.utils import llm_providers as agent_module

        async def _raise_value_error(provider, base_url=None, api_key=None):
            raise ValueError("base_url is required")

        monkeypatch.setattr(agent_module, "list_provider_models", _raise_value_error)

        response = await client.post(app.url_path_for("list_llm_models"), json={"provider": "bedrock"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "base_url" in response.json()["message"]

    async def test_models_no_default_config(self, app: FastAPI, client: AsyncClient) -> None:
        """
        Test that omitting the body falls back to the default LLM config (404 when none exists).
        """

        response = await client.post(app.url_path_for("list_llm_models"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "default" in response.json()["message"]

    async def test_models_unauthenticated(self, app: FastAPI, client: AsyncClient) -> None:
        """
        Test that listing models requires authentication.
        """

        response = await client.post(
            app.url_path_for("list_llm_models"),
            json={"provider": "openai"},
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
