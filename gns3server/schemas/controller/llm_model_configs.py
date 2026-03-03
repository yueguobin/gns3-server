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

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID

from .base import DateTimeModelMixin


# Core model config schema (stored in config JSONB field)
class LLMModelConfigData(BaseModel):
    """
    LLM model configuration data.
    All fields are stored in the config JSONB column.
    """

    name: str = Field(..., min_length=1, max_length=100, description="Configuration name")
    provider: str = Field(..., description="LLM provider (e.g., 'openai', 'anthropic', 'ollama')")
    base_url: str = Field(..., description="API base URL")
    model: str = Field(..., description="Model name")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperature parameter")
    api_key: Optional[str] = Field(None, description="API key (will be encrypted)")
    max_tokens: Optional[int] = Field(None, gt=0, description="Max tokens for generation")

    # Allow extra fields for extensibility
    model_config = ConfigDict(extra="allow")


# Request schemas
class LLMModelConfigCreate(LLMModelConfigData):
    """Request to create a new LLM model configuration."""

    is_default: Optional[bool] = Field(False, description="Set as default configuration")


class LLMModelConfigUpdate(BaseModel):
    """Request to update an existing LLM model configuration."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    api_key: Optional[str] = None
    max_tokens: Optional[int] = Field(None, gt=0)
    is_default: Optional[bool] = None

    # Allow extra fields for extensibility
    model_config = ConfigDict(extra="allow")


# Response schemas
class LLMModelConfigResponse(DateTimeModelMixin):
    """LLM model configuration response."""

    config_id: UUID
    config: LLMModelConfigData
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    is_default: bool

    model_config = ConfigDict(from_attributes=True)


class LLMModelConfigListResponse(BaseModel):
    """Response containing list of LLM model configurations."""

    configs: list[LLMModelConfigData]
    default_config_id: Optional[UUID] = None
    total: int


# Inheritance response (user configs + inherited group configs)
class LLMModelConfigWithSource(LLMModelConfigData):
    """Model configuration with source information."""

    config_id: UUID
    source: str = Field(..., description="Source: 'user' or 'group'")
    group_name: Optional[str] = Field(None, description="Group name if source is 'group'")
    is_default: bool


class LLMModelConfigInheritedResponse(BaseModel):
    """Response containing user's effective configs (own + inherited from groups)."""

    configs: list[LLMModelConfigWithSource]
    default_config: Optional[LLMModelConfigWithSource] = None
    total: int
