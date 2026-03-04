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
API routes for GNS3 Copilot Chat integration.
"""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from uuid import UUID

from gns3server import schemas
from gns3server.controller import Controller
from gns3server.controller.controller_error import ControllerNotFoundError
from gns3server.agent.gns3_copilot.project_agent_manager import get_project_agent_manager

from .dependencies.authentication import get_current_active_user

log = logging.getLogger(__name__)

responses = {404: {"model": schemas.ErrorMessage, "description": "Resource not found"}}

router = APIRouter(responses=responses)


async def dep_project(project_id: UUID):
    """
    Dependency to retrieve a project.
    """
    controller = Controller.instance()
    project = controller.get_project(str(project_id))
    if not project:
        raise ControllerNotFoundError(f"Project '{project_id}' not found")
    return project


@router.post(
    "/stream",
    response_model=None,
    summary="Stream chat responses from GNS3 Copilot",
    description="Send a message to GNS3 Copilot and stream the response via Server-Sent Events (SSE)."
)
async def stream_chat(
    request: schemas.ChatRequest,
    http_request: Request,
    current_user: schemas.User = Depends(get_current_active_user),
) -> StreamingResponse:
    """
    Stream chat endpoint for GNS3 Copilot.

    This endpoint uses Server-Sent Events (SSE) to stream responses from
    the AI agent. Each message is a JSON object with a `type` field indicating
    the message kind (content, tool_call, tool_start, tool_end, error, done, heartbeat).
    """

    # Validate project exists and get path
    try:
        controller = Controller.instance()
        project = controller.get_project(str(request.project_id))
        if not project:
            raise ControllerNotFoundError(f"Project '{request.project_id}' not found")
        project_path = project.path
    except ControllerNotFoundError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project: {e}"
        )

    # Get user authentication info
    user_id = str(current_user.user_id)

    # Get JWT token from Authorization header
    auth_header = http_request.headers.get("Authorization", "")
    jwt_token = auth_header.replace("Bearer ", "") if auth_header else None

    # Get or create AgentService for this project
    agent_manager = await get_project_agent_manager()
    agent_service = await agent_manager.get_agent(str(request.project_id), project_path)

    # Generate session_id if not provided
    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        """Generator for SSE streaming."""
        try:
            async for chunk in agent_service.stream_chat(
                message=request.message,
                session_id=session_id,
                project_id=str(request.project_id),
                user_id=user_id,
                jwt_token=jwt_token,
                mode=request.mode
            ):
                try:
                    # Validate and serialize chunk
                    validated = schemas.ChatResponse(**chunk)
                    yield f"data: {json.dumps(validated.model_dump(exclude_none=True), ensure_ascii=False)}\n\n"
                except Exception as e:
                    log.warning("Error serializing chunk: %s", e)
                    # Skip invalid chunks but continue streaming
                    continue

            # Final done message
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        except Exception as e:
            log.error("Error in stream_chat: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@router.get(
    "/history/{session_id}",
    response_model=schemas.ConversationHistory,
    summary="Get conversation history",
    description="Retrieve the conversation history for a specific session/thread."
)
async def get_history(
    session_id: str,
    project_id: UUID,
    limit: int = 100,
    current_user: schemas.User = Depends(get_current_active_user),
) -> schemas.ConversationHistory:
    """
    Get conversation history for a session.
    """

    # Validate project exists
    try:
        controller = Controller.instance()
        project = controller.get_project(str(project_id))
        if not project:
            raise ControllerNotFoundError(f"Project '{project_id}' not found")
        project_path = project.path
    except ControllerNotFoundError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project: {e}"
        )

    # Get AgentService for this project
    agent_manager = await get_project_agent_manager()
    agent_service = await agent_manager.get_agent(str(project_id), project_path)

    # Get history
    history = await agent_service.get_history(session_id, limit)

    return schemas.ConversationHistory(**history)


@router.get(
    "/sessions",
    response_model=List[schemas.ChatSession],
    summary="List chat sessions",
    description="List all chat sessions for a project (not yet implemented)."
)
async def list_sessions(
    project_id: UUID,
    current_user: schemas.User = Depends(get_current_active_user),
) -> list[schemas.ChatSession]:
    """
    List chat sessions for a project.

    Note: This endpoint is a placeholder. Full session listing functionality
    requires checkpoint metadata inspection which is not yet implemented.
    """
    # TODO: Implement session listing from checkpoint metadata
    return []


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a chat session",
    description="Delete a specific chat session (not yet implemented)."
)
async def delete_session(
    session_id: str,
    project_id: UUID,
    current_user: schemas.User = Depends(get_current_active_user),
):
    """
    Delete a chat session.

    Note: This endpoint is a placeholder. Full session deletion functionality
    requires checkpoint manipulation which is not yet implemented.
    """
    # TODO: Implement session deletion from checkpoint
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Session deletion not yet implemented"
    )
