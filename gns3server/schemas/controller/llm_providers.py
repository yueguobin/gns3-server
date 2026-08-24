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


from pydantic import BaseModel, Field
from typing import List, Optional


class LLMModel(BaseModel):
    """
    A model available from an LLM provider.
    """

    model_id: str = Field(..., description="Model identifier to store in the model field of an LLM model configuration")
    name: Optional[str] = Field(None, description="Human-readable model name, when the provider reports one")
    owned_by: Optional[str] = Field(None, description="Model owner/vendor, when the provider reports one")
    context_length: Optional[int] = Field(None, description="Model context window in tokens, when the provider reports it")


class LLMModelsRequest(BaseModel):
    """
    Request for listing the models available from an LLM provider.

    Either supply the connection parameters explicitly (e.g. while filling in
    an unsaved configuration form) or leave them out to use the requester's
    default LLM model configuration.
    """

    provider: Optional[str] = Field(None, description="Provider key (as returned by GET /copilot/llm/providers)")
    base_url: Optional[str] = Field(None, description="Provider base URL (defaults to the provider's public endpoint)")
    api_key: Optional[str] = Field(None, description="API key; never returned by any endpoint", repr=False)


class LLMModelList(BaseModel):
    """
    List of models available from an LLM provider.
    """

    provider: str = Field(..., description="Provider key the models were listed for")
    base_url: Optional[str] = Field(None, description="Base URL the models were listed from, when applicable")
    models: List[LLMModel] = Field(..., description="Available models, sorted by model_id")


class LLMProviderParam(BaseModel):
    """
    A configurable parameter of an LLM provider's chat model class.
    """

    name: str = Field(..., description="Parameter name (the pydantic field name of the chat model class)")
    alias: Optional[str] = Field(None, description="Alternative keyword name accepted for this parameter (e.g. 'model' for model_name), when set")
    type: str = Field(..., description="Parameter type annotation (e.g. 'float | None', 'SecretStr')")
    required: bool = Field(..., description="Whether the parameter must be provided")
    default: Optional[str] = Field(None, description="Default value as a string, if the parameter is optional and has a primitive default")
    secret: bool = Field(False, description="Whether the parameter holds a secret (values are never returned)")


class LLMProvider(BaseModel):
    """
    An LLM model provider supported by the installed langchain stack.
    """

    name: str = Field(..., description="Provider key to store in the provider field of an LLM model configuration")
    pip_package: str = Field(..., description="pip package providing this provider (part of the gns3-server[ai-features] extra)")
    model_class: str = Field(..., description="Name of the langchain chat model class implementing this provider")
    installed: bool = Field(..., description="Whether the provider package is installed on this server")
    parameters: Optional[List[LLMProviderParam]] = Field(None, description="Configurable parameters of the chat model class (None when the provider is not installed or could not be imported)")


class LLMProviderList(BaseModel):
    """
    List of LLM model providers supported by the installed langchain stack.
    """

    langchain_version: str = Field(..., description="Version of the installed langchain library")
    providers: List[LLMProvider] = Field(..., description="Supported LLM providers, sorted by name")
