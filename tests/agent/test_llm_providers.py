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

"""Offline unit tests for list_provider_models (network mocked at _fetch_json)."""


import pytest

from gns3server.agent.gns3_copilot.utils import llm_providers

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fetch_calls(monkeypatch):
    """
    Replace _fetch_json with a recorder returning a canned payload per test.
    """

    calls = []
    payload = {}

    async def _fake_fetch_json(url, headers):
        calls.append({"url": url, "headers": headers})
        return payload["value"]

    monkeypatch.setattr(llm_providers, "_fetch_json", _fake_fetch_json)
    return calls, payload


class TestListProviderModels:

    async def test_openai_compatible(self, fetch_calls):
        """OpenAI-style /models with default base URL and Bearer auth."""
        calls, payload = fetch_calls
        payload["value"] = {"data": [
            {"id": "gpt-x", "owned_by": "openai"},
            {"id": "gpt-a", "owned_by": "openai", "context_length": 128000},
        ]}

        result = await llm_providers.list_provider_models("openai", api_key="sk-test")

        assert calls[0]["url"] == "https://api.openai.com/v1/models"
        assert calls[0]["headers"] == {"Authorization": "Bearer sk-test"}
        assert result["provider"] == "openai"
        assert result["base_url"] == "https://api.openai.com/v1"
        assert [m["model_id"] for m in result["models"]] == ["gpt-a", "gpt-x"]  # sorted
        assert result["models"][0]["context_length"] == 128000
        assert result["models"][0]["owned_by"] == "openai"

    async def test_openai_compatible_custom_base_url_no_key(self, fetch_calls):
        """Aggregator/self-hosted case: custom base_url, no API key sent."""
        calls, payload = fetch_calls
        payload["value"] = {"data": [{"id": "vendor/llama-3"}]}

        result = await llm_providers.list_provider_models("openai", base_url="https://openrouter.example/api/v1")

        assert calls[0]["url"] == "https://openrouter.example/api/v1/models"
        assert calls[0]["headers"] == {}
        assert result["models"] == [{"model_id": "vendor/llama-3", "name": None, "owned_by": None, "context_length": None}]

    async def test_unknown_provider_requires_base_url(self, fetch_calls):
        """Provider without a known default endpoint and no base_url -> ValueError."""
        with pytest.raises(ValueError, match="base_url is required"):
            await llm_providers.list_provider_models("baseten")

    async def test_unsupported_provider(self, fetch_calls):
        """Deployment-authenticated providers are rejected upfront."""
        for provider in ("bedrock", "azure_openai"):
            with pytest.raises(ValueError, match="not supported"):
                await llm_providers.list_provider_models(provider)

    async def test_ollama(self, fetch_calls):
        """Ollama local /api/tags, no authentication."""
        calls, payload = fetch_calls
        payload["value"] = {"models": [{"name": "llama3:latest", "model": "llama3:latest"}]}

        result = await llm_providers.list_provider_models("ollama")

        assert calls[0]["url"] == "http://localhost:11434/api/tags"
        assert calls[0]["headers"] == {}
        assert result["base_url"] == "http://localhost:11434"
        assert result["models"] == [{"model_id": "llama3:latest", "name": "llama3:latest", "owned_by": None, "context_length": None}]

    async def test_anthropic(self, fetch_calls):
        """Anthropic /v1/models with x-api-key header."""
        calls, payload = fetch_calls
        payload["value"] = {"data": [{"id": "claude-x", "display_name": "Claude X"}]}

        result = await llm_providers.list_provider_models("anthropic", api_key="sk-ant")

        assert calls[0]["url"] == "https://api.anthropic.com/v1/models?limit=1000"
        assert calls[0]["headers"]["x-api-key"] == "sk-ant"
        assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"
        assert result["models"] == [{"model_id": "claude-x", "name": "Claude X", "owned_by": None, "context_length": None}]

    async def test_google_genai(self, fetch_calls):
        """Google GenAI ListModels with the models/ prefix stripped."""
        calls, payload = fetch_calls
        payload["value"] = {"models": [{"name": "models/gemini-x", "displayName": "Gemini X", "inputTokenLimit": 1000000}]}

        result = await llm_providers.list_provider_models("google_genai", api_key="g-key")

        assert calls[0]["url"].startswith("https://generativelanguage.googleapis.com/v1beta/models")
        assert calls[0]["headers"] == {"x-goog-api-key": "g-key"}
        assert result["base_url"] is None
        assert result["models"] == [
            {"model_id": "gemini-x", "name": "Gemini X", "owned_by": None, "context_length": 1000000}
        ]
