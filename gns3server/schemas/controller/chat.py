#
# Copyright (C) 2025 GNS3 Technologies Inc.
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
Chat API schemas for GNS3 Copilot integration.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal


class OpenAIToolCall(BaseModel):
    """Tool call information (OpenAI compatible format)."""

    id: str = Field(..., description="Tool call ID")
    type: Literal["function"] = Field(default="function", description="Tool call type")
    function: Dict[str, Any] = Field(..., description="Function name and arguments")


class ChatRequest(BaseModel):
    """Chat request model."""

    message: str = Field(..., description="User message content")
    session_id: Optional[str] = Field(None, description="Session ID (auto-generated if not provided)")
    project_id: str = Field(..., description="GNS3 project ID")
    stream: bool = Field(default=True, description="Enable streaming response")
    temperature: Optional[float] = Field(None, description="LLM temperature parameter")
    mode: Literal["text"] = Field(default="text", description="Interaction mode")


class ChatResponse(BaseModel):
    """Chat streaming response model."""

    type: Literal[
        "content",      # AI text content
        "tool_call",    # Tool call request
        "tool_start",   # Tool execution started
        "tool_end",     # Tool execution completed
        "error",        # Error message
        "done",         # Stream ended
        "heartbeat"     # Keep-alive signal
    ] = Field(..., description="Response message type")
    content: Optional[str] = Field(None, description="Text content (for type=content)")
    message_id: Optional[str] = Field(None, description="Message ID")
    tool_call: Optional[OpenAIToolCall] = Field(None, description="Tool call (for type=tool_call)")
    tool_name: Optional[str] = Field(None, description="Tool name (for type=tool_start/end)")
    tool_output: Optional[str] = Field(None, description="Tool output (for type=tool_end)")
    error: Optional[str] = Field(None, description="Error message (for type=error)")
    session_id: Optional[str] = Field(None, description="Session ID (for type=heartbeat/done)")


class OpenAIMessage(BaseModel):
    """Message model for conversation history."""

    id: str = Field(..., description="Message ID")
    role: Literal["user", "assistant", "system", "tool"] = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Tool message name")
    tool_call_id: Optional[str] = Field(None, description="Associated tool call ID (for tool messages)")
    tool_calls: Optional[List[OpenAIToolCall]] = Field(None, description="Tool calls (for assistant messages)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Message metadata")
    created_at: str = Field(..., description="Message timestamp (ISO 8601)")


class ConversationHistory(BaseModel):
    """Conversation history model."""

    thread_id: str = Field(..., description="Thread/session ID")
    title: str = Field(..., description="Conversation title")
    messages: List[OpenAIMessage] = Field(default_factory=list, description="Conversation messages")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    llm_calls: int = Field(default=0, description="Total LLM calls in this conversation")


class ChatSession(BaseModel):
    """Chat session model."""

    session_id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    project_id: Optional[str] = Field(None, description="Associated GNS3 project ID")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
