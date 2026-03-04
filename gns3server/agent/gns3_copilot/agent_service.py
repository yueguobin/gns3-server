"""
GNS3 Copilot Agent Service

Provides project-level Agent instances with SQLite checkpoint management.
Each project has its own AgentService with a dedicated checkpoint database
in the project directory.
"""

import asyncio
import logging
import os
from typing import AsyncGenerator, Dict, Any, Optional
from uuid import uuid4

import aiosqlite
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from gns3_copilot.agent.gns3_copilot import agent_builder

log = logging.getLogger(__name__)


class AgentService:
    """
    Project-level Agent Service with async checkpoint management.

    Manages a LangGraph agent instance with SQLite-based state persistence
    for a single GNS3 project.
    """

    def __init__(self, project_path: str):
        """
        Initialize AgentService for a project.

        Args:
            project_path: Path to the GNS3 project directory
        """
        self.project_path = project_path
        self._checkpointer: Optional[AsyncSqliteSaver] = None
        self._checkpointer_conn: Optional[aiosqlite.Connection] = None
        self._checkpointer_path: Optional[str] = None
        self._graph = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    def _get_checkpoint_dir(self) -> str:
        """Get or create the checkpoint directory for this project."""
        checkpoint_dir = os.path.join(self.project_path, ".gns3-copilot")
        os.makedirs(checkpoint_dir, exist_ok=True)
        return checkpoint_dir

    async def _get_checkpointer(self) -> AsyncSqliteSaver:
        """
        Get or create the SQLite checkpointer for this project.

        Returns:
            AsyncSqliteSaver instance
        """
        async with self._init_lock:
            if self._checkpointer is not None:
                return self._checkpointer

            checkpoint_dir = self._get_checkpoint_dir()
            checkpointer_path = os.path.join(checkpoint_dir, "copilot_checkpoints.db")

            log.debug("Creating checkpointer at: %s", checkpointer_path)

            # Close existing connection if switching projects
            if self._checkpointer_conn:
                try:
                    await self._checkpointer_conn.close()
                    log.debug("Closed previous checkpointer connection")
                except Exception as e:
                    log.warning("Error closing old checkpointer connection: %s", e)

            # Create new connection
            conn = await aiosqlite.connect(checkpointer_path)
            # Enable WAL mode for better concurrent performance
            await conn.execute("PRAGMA journal_mode=WAL;")
            self._checkpointer_conn = conn  # Save connection reference to prevent GC
            self._checkpointer = AsyncSqliteSaver(conn)

            # CRITICAL: Initialize database schema
            await self._checkpointer.setup()

            self._checkpointer_path = checkpointer_path
            self._initialized = True

            log.info("Project checkpointer created at: %s", checkpointer_path)
            return self._checkpointer

    async def _get_graph(self):
        """Get or compile the LangGraph agent."""
        if self._graph is None:
            checkpointer = await self._get_checkpointer()
            self._graph = agent_builder.compile(checkpointer=checkpointer)
            log.info("LangGraph agent compiled for project: %s", self.project_path)
        return self._graph

    async def stream_chat(
        self,
        message: str,
        session_id: str,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        jwt_token: Optional[str] = None,
        mode: str = "text"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream chat responses from the agent.

        Args:
            message: User message
            session_id: Session/thread ID for conversation continuity
            project_id: GNS3 project ID (optional, for context)
            user_id: User ID for LLM config lookup (optional)
            jwt_token: JWT token for API authentication (optional)
            mode: Interaction mode (default: "text")

        Yields:
            Dict containing SSE-compatible response chunks
        """
        # Build config with user authentication info
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_id": user_id,
                "jwt_token": jwt_token,
            }
        }

        # Build inputs
        inputs = {
            "messages": [HumanMessage(content=message)],
            "llm_calls": 0,
            "remaining_steps": 20,
            "mode": mode,
        }

        # Get the compiled graph
        graph = await self._get_graph()

        # Stream events
        try:
            async for event in graph.astream_events(inputs, config=config, version="v2"):
                chunk = self._convert_event_to_chunk(event, session_id)
                if chunk:
                    yield chunk

            yield {"type": "done", "session_id": session_id}

        except Exception as e:
            log.error("Error in stream_chat: %s", e, exc_info=True)
            yield {"type": "error", "error": str(e), "session_id": session_id}

    def _convert_event_to_chunk(self, event: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
        """
        Convert LangGraph event to API response chunk.

        Args:
            event: LangGraph event from astream_events
            session_id: Session ID for the response

        Returns:
            Dict for SSE response or None if event should be filtered
        """
        event_type = event.get("event", "")
        data = event.get("data", {})

        if event_type == "on_chat_model_stream":
            # Streaming text content from LLM
            chunk = data.get("chunk", {})
            content = chunk.get("content", "")
            if content:
                return {"type": "content", "content": content}

        elif event_type == "on_tool_start":
            # Tool execution started
            return {
                "type": "tool_start",
                "tool_name": event.get("name", ""),
                "session_id": session_id
            }

        elif event_type == "on_tool_end":
            # Tool execution completed
            output = data.get("output", "")
            # Convert output to string if it's not already
            if not isinstance(output, str):
                output = str(output)
            return {
                "type": "tool_end",
                "tool_name": event.get("name", ""),
                "tool_output": output,
                "session_id": session_id
            }

        return None

    async def get_history(self, session_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        Get conversation history for a session.

        Args:
            session_id: Session/thread ID
            limit: Maximum number of messages to retrieve

        Returns:
            Dict containing thread_id, title, and messages
        """
        config = {"configurable": {"thread_id": session_id}}

        try:
            graph = await self._get_graph()
            state = await graph.aget_state(config)

            if state and "messages" in state.values:
                messages = []
                for msg in state.values["messages"][-limit:]:
                    messages.append(self._convert_message_to_dict(msg))

                title = state.values.get("conversation_title", "New Conversation")

                return {
                    "thread_id": session_id,
                    "title": title,
                    "messages": messages
                }
        except Exception as e:
            log.error("Error getting history: %s", e, exc_info=True)

        return {
            "thread_id": session_id,
            "title": "New Conversation",
            "messages": []
        }

    def _convert_message_to_dict(self, msg) -> Dict[str, Any]:
        """Convert a LangChain message to dict format."""
        from datetime import datetime

        msg_type = type(msg).__name__

        result = {
            "id": getattr(msg, "id", str(uuid4())),
            "role": "user",
            "content": getattr(msg, "content", str(msg)),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

        if msg_type == "HumanMessage":
            result["role"] = "user"
        elif msg_type == "AIMessage":
            result["role"] = "assistant"
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                result["tool_calls"] = msg.tool_calls
        elif msg_type == "ToolMessage":
            result["role"] = "tool"
            result["tool_call_id"] = getattr(msg, "tool_call_id", None)
            result["name"] = getattr(msg, "name", None)
        elif msg_type == "SystemMessage":
            result["role"] = "system"

        return result

    async def close(self):
        """
        Close the checkpointer connection and cleanup resources.
        """
        async with self._init_lock:
            if self._checkpointer_conn:
                try:
                    await self._checkpointer_conn.close()
                    log.debug("Checkpointer connection closed for: %s", self.project_path)
                except Exception as e:
                    log.warning("Error closing checkpointer connection: %s", e)
                finally:
                    self._checkpointer_conn = None
                    self._checkpointer = None
                    self._graph = None
                    self._initialized = False
