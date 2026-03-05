# GNS3 Copilot HITL Feature Implementation Plan

## Overview

This document details the complete implementation plan for the Human-in-the-Loop (HITL) feature in GNS3 Copilot. The HITL feature allows requiring user confirmation before executing sensitive operations (such as device configuration), improving system security.

## Goals

- Require user confirmation before executing configuration tools
- Support single and batch tool confirmation
- Provide clear tool execution preview
- Maintain complete compatibility with existing functionality

## Core Design

### Flow Chart

```
User Message → LLM → Tool Call Decision
                      ↓
              Check if confirmation needed
              ↙              ↘
         Need HITL        Direct Execution
              ↓                ↓
         Pause, wait for frontend    Execute Tool
              ↓                ↓
         User Confirm/Reject      Return Result
              ↓
         Execute Confirmed Tools
              ↓
         Return Result
```

### Architecture Layers

```
┌─────────────────────────────────────────┐
│         Frontend (Web UI)                │
│  - Display confirmation dialog           │
│  - List pending tools                    │
│  - Handle user confirm/reject actions    │
└─────────────────────────────────────────┘
                  ↕ SSE/HTTP
┌─────────────────────────────────────────┐
│         API Layer (FastAPI)              │
│  - /hitl/status: Get pending tools       │
│  - /hitl/confirm: Confirm execution      │
│  - /hitl/reject: Reject execution        │
└─────────────────────────────────────────┘
                  ↕
┌─────────────────────────────────────────┐
│      AgentService (State Management)      │
│  - Manage HITL state                     │
│  - Handle confirm/reject logic           │
│  - checkpoint persistence                │
└─────────────────────────────────────────┘
                  ↕
┌─────────────────────────────────────────┐
│      LangGraph Agent (Workflow)          │
│  - llm_call: LLM invocation              │
│  - check_hitl: Check if confirmation needed │
│  - hitl_confirmation: Wait for confirmation │
│  - conditional_execution: Conditional execution │
└─────────────────────────────────────────┘
```

## Implementation Changes

### 1. LangGraph Agent Layer

#### File: `gns3server/agent/gns3_copilot/agent/gns3_copilot.py`

##### Change 1.1: Extend MessagesState

**Location**: Lines 98-124

```python
# Extend state definition, add HITL-related fields
class MessagesState(TypedDict):
    """GNS3-Copilot Conversation State Management Class"""

    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int
    remaining_steps: RemainingSteps
    conversation_title: str | None
    topology_info: dict | None

    # New: HITL-related fields
    pending_tool_calls: list[dict]      # List of tool calls awaiting confirmation
    hitl_confirmation_required: bool     # Whether user confirmation is needed
    hitl_session_id: str | None          # HITL session unique identifier
    confirmed_tool_calls: list[dict]     # User-confirmed tool calls
    rejected_tool_calls: list[dict]      # User-rejected tool calls
```

**Change Impact**:
- 5 new fields in checkpoint database
- Existing state reading code needs to be compatible with new fields

##### Change 1.2: Add HITL Detection Node

**Location**: Add after `generate_title` function (around line 310)

```python
# List of tools requiring confirmation
HITL_TOOLS = {
    "execute_multiple_device_config_commands",
    # Can be added as needed:
    # "delete_node",
    # "start_gns3_node",
}

DANGEROUS_PATTERNS = [
    "reload", "reboot", "write erase", "erase startup-config",
    "factory reset", "format", "delete", "no ip routing"
]


def _is_dangerous_config(tool_name: str, tool_args: dict) -> bool:
    """Check if configuration contains dangerous commands"""
    if tool_name == "execute_multiple_device_config_commands":
        device_configs = tool_args.get("device_configs", [])
        for device in device_configs:
            commands = device.get("config_commands", [])
            for cmd in commands:
                cmd_lower = cmd.lower()
                if any(pattern in cmd_lower for pattern in DANGEROUS_PATTERNS):
                    return True
    return False


def check_hitl_requirement(state: MessagesState) -> dict:
    """
    Check if tool calls require user confirmation (HITL)

    Returns:
        dict: State update containing pending_tool_calls and hitl_confirmation_required
    """
    last_message = state["messages"][-1]

    # If last message has no tool calls, return directly
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"hitl_confirmation_required": False}

    pending_tools = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        # Only process tools that need HITL
        if tool_name in HITL_TOOLS:
            # Check if it's a dangerous operation
            is_dangerous = _is_dangerous_config(tool_name, tool_args)

            tool_info = {
                "tool_call_id": tool_call["id"],
                "tool_name": tool_name,
                "tool_args": tool_args,
                "danger_level": "high" if is_dangerous else "medium"
            }

            # Add description information
            if tool_name == "execute_multiple_device_config_commands":
                device_count = len(tool_args.get("device_configs", []))
                tool_info["description"] = f"Configure {device_count} device(s)"

            pending_tools.append(tool_info)
            logger.info("HITL: Tool '%s' requires confirmation (danger_level=%s)",
                       tool_name, tool_info["danger_level"])

    if pending_tools:
        logger.info("HITL: %d tools require confirmation", len(pending_tools))
        return {
            "pending_tool_calls": pending_tools,
            "hitl_confirmation_required": True,
            "hitl_session_id": str(uuid4())
        }

    return {"hitl_confirmation_required": False}
```

##### Change 1.3: Modify should_continue Route

**Location**: Lines 337-370

```python
def should_continue(
    state: MessagesState,
) -> Literal["conditional_tool_execution", "hitl_confirmation", "title_generator_node", END]:
    """
    Routing decision after LLM response

    Returns:
        Literal: Route to next node
    """
    last_message = state["messages"][-1]
    current_title = state.get("conversation_title")

    # LLM requests tool call
    if last_message.tool_calls:
        # Check if HITL confirmation is needed
        if state.get("hitl_confirmation_required"):
            logger.info("Routing to hitl_confirmation node")
            return "hitl_confirmation"

        logger.info("Routing to conditional_tool_execution node")
        return "conditional_tool_execution"

    # First interaction completed, generate title
    if current_title in [None, "New Conversation"]:
        return "title_generator_node"

    return END
```

**Key Changes**:
- Original route `"tool_node"` changed to `"conditional_tool_execution"`
- New `"hitl_confirmation"` route added
- Route name changed, all references need to be updated synchronously

##### Change 1.4: Add HITL Confirmation Wait Node

**Location**: Add after `should_continue` function

```python
def hitl_confirmation_node(state: MessagesState) -> dict:
    """
    HITL confirmation node - Pause execution, wait for user confirmation

    This is a special node that performs no operations, only maintains state.
    Actual confirmation flow is handled by the API layer.

    Working principle:
    1. When node is called, state contains pending_tool_calls
    2. LangGraph saves state to checkpoint
    3. Execution flow pauses, waits for external state update
    4. After user confirms via API, state is updated
    5. Resume execution from checkpoint

    Returns:
        dict: Empty dictionary, maintains state unchanged
    """
    logger.info("HITL: Pausing for user confirmation (session_id=%s)",
               state.get("hitl_session_id"))

    # Return empty dictionary, keep state unchanged
    # State will be updated via API after user confirmation
    return {}
```

##### Change 1.5: Add Conditional Execution Node

**Location**: Add after `hitl_confirmation_node` function

```python
def conditional_tool_execution(state: MessagesState) -> dict:
    """
    Conditional tool execution node - Decide whether to execute tools based on user confirmation

    This node replaces the original tool_node, adding:
    1. Only execute user-confirmed tools
    2. Handle user-rejected tools
    3. Update HITL state

    Returns:
        dict: Contains execution results and state updates
    """
    confirmed_calls = state.get("confirmed_tool_calls", [])
    rejected_calls = state.get("rejected_tool_calls", [])

    logger.info("HITL: Executing %d confirmed tools, %d rejected",
               len(confirmed_calls), len(rejected_calls))

    # Handle user-rejected tools
    if rejected_calls:
        rejected_names = [c["tool_name"] for c in rejected_calls]
        rejection_msg = (
            f"User rejected the following operations: {', '.join(rejected_names)}.\n"
            f"Please provide an alternative solution or explain why these operations should not be performed."
        )

        # Add system message to notify LLM
        return {
            "messages": [SystemMessage(content=rejection_msg)],
            "pending_tool_calls": [],
            "hitl_confirmation_required": False,
            "confirmed_tool_calls": [],
            "rejected_tool_calls": []
        }

    # Execute confirmed tools
    if not confirmed_calls:
        logger.warning("HITL: No confirmed tools to execute")
        return {
            "pending_tool_calls": [],
            "hitl_confirmation_required": False
        }

    results = []
    for tool_call_dict in confirmed_calls:
        tool_call_id = tool_call_dict["tool_call_id"]
        tool_name = tool_call_dict["tool_name"]
        tool_args = tool_call_dict["tool_args"]

        logger.info("Executing confirmed tool: %s", tool_name)

        tool = tools_by_name[tool_name]
        try:
            observation = tool.invoke(tool_args)
            results.append(ToolMessage(
                content=observation,
                tool_call_id=tool_call_id,
                name=tool_name
            ))
            logger.debug("Tool %s completed successfully", tool_name)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e, exc_info=True)
            results.append(ToolMessage(
                content=f"Error: {str(e)}",
                tool_call_id=tool_call_id,
                name=tool_name
            ))

    # Clean up HITL state
    return {
        "messages": results,
        "pending_tool_calls": [],
        "hitl_confirmation_required": False,
        "confirmed_tool_calls": [],
        "rejected_tool_calls": []
    }
```

**Key Changes**:
- Replaces original `tool_node` function
- Adds confirmation logic handling
- Supports partial confirmation, partial rejection

##### Change 1.6: Update LangGraph Build Process

**Location**: Lines 393-427

```python
# Build workflow
agent_builder = StateGraph(MessagesState)

# Add nodes
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("hitl_confirmation", hitl_confirmation_node)
agent_builder.add_node("conditional_tool_execution", conditional_tool_execution)
agent_builder.add_node("title_generator_node", generate_title)

# Add edges: START → llm_call
agent_builder.add_edge(START, "llm_call")

# Add edges: conditional routing after LLM
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "hitl_confirmation": "hitl_confirmation",          # Needs HITL confirmation
        "conditional_tool_execution": "conditional_tool_execution",  # Direct execution
        "title_generator_node": "title_generator_node",   # Generate title
        END: END                                         # End conversation
    },
)

# HITL confirmation node is special, needs to wait for external state update
# State is updated after checkpoint saved, next round of invocation resumes from checkpoint
# This cycle is completed by API triggering new graph.ainvoke() call

# Add edges: continue LLM call after conditional execution
agent_builder.add_conditional_edges(
    "conditional_tool_execution",
    recursion_limit_continue,
    {
        "llm_call": "llm_call",
        END: END
    },
)

# Add edges: end after title generation
agent_builder.add_edge("title_generator_node", END)
```

**Workflow Diagram**:
```
START → llm_call → should_continue
                     ↓
        ┌────────────┼────────────┐
        ↓            ↓            ↓
hitl_confirmation  conditional  title_generator
(wait for API)      _execution         ↓
        └────────────┴────────────→ END
```

#### File: `gns3server/agent/gns3_copilot/agent_service.py`

##### Change 2.1: Add HITL Event Handling

**Location**: `_convert_event_to_chunk` function at lines 333-376

```python
def _convert_event_to_chunk(self, event: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    """
    Convert LangGraph events to API response chunks

    Supports HITL event types
    """
    event_type = event.get("event", "")
    data = event.get("data", {})

    if event_type == "on_chat_model_stream":
        chunk = data.get("chunk", {})
        content = getattr(chunk, "content", "")
        if content:
            return {"type": "content", "content": content}

    elif event_type == "on_tool_start":
        return {
            "type": "tool_start",
            "tool_name": event.get("name", ""),
            "session_id": session_id
        }

    elif event_type == "on_tool_end":
        output = data.get("output", "")
        if not isinstance(output, str):
            output = str(output)
        return {
            "type": "tool_end",
            "tool_name": event.get("name", ""),
            "tool_output": output,
            "session_id": session_id
        }

    # New: HITL confirmation required event
    elif event_type == "hitl_required":
        return {
            "type": "hitl_required",
            "pending_tools": data.get("pending_tool_calls", []),
            "hitl_session_id": data.get("hitl_session_id"),
            "timeout": 300,  # 5 minute timeout
            "session_id": session_id
        }

    return None
```

**Note**: In actual implementation, HITL events are not triggered via LangGraph's `astream_events`, but achieved through state queries. Therefore, this function is mainly used to handle tool execution events.

---

### 2. API Layer

#### File: `gns3server/api/routes/controller/chat.py`

##### Change 2.1: Add HITL Endpoints

**Location**: Add at end of file (after line 325)

```python
from gns3server import schemas
from typing import List


# =============================================================================
# HITL (Human-in-the-Loop) Endpoints
# =============================================================================

@router.get(
    "/sessions/{session_id}/hitl-status",
    response_model=schemas.HITLStatusResponse,
    summary="Get HITL status",
    description="Get list of pending tools in current session"
)
async def get_hitl_status(
    session_id: str,
    project: Project = Depends(dep_project),
    current_user: schemas.User = Depends(get_current_active_user),
) -> schemas.HITLStatusResponse:
    """
    Get HITL status

    Returns the list of tool calls waiting for user confirmation in the current session.
    Frontend should poll this endpoint periodically to check for new pending tools.
    """
    if project.status != "opened":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project must be opened. Current status: {project.status}"
        )

    agent_manager = await get_project_agent_manager()
    agent_service = await agent_manager.get_agent(str(project.id), project.path)

    # Get state from checkpoint
    config = {"configurable": {"thread_id": session_id}}
    state = await agent_service._graph.aget_state(config)

    if not state or not state.values:
        return schemas.HITLStatusResponse(
            status="idle",
            pending_tools=[],
            hitl_session_id=None,
            session_id=session_id
        )

    values = state.values
    pending_tools = values.get("pending_tool_calls", [])
    hitl_session_id = values.get("hitl_session_id")

    # Convert to Schema format
    pending_tool_schemas = []
    for tool in pending_tools:
        pending_tool_schemas.append(schemas.PendingTool(
            tool_call_id=tool["tool_call_id"],
            tool_name=tool["tool_name"],
            tool_args=tool["tool_args"],
            danger_level=tool.get("danger_level", "medium"),
            description=tool.get("description", "")
        ))

    return schemas.HITLStatusResponse(
        status="waiting" if pending_tool_schemas else "idle",
        pending_tools=pending_tool_schemas,
        hitl_session_id=hitl_session_id,
        session_id=session_id
    )


@router.post(
    "/sessions/{session_id}/hitl/confirm",
    response_model=schemas.HITLConfirmationResponse,
    summary="Confirm tool execution",
    description="User confirms to execute one or more pending tools"
)
async def confirm_tool_execution(
    session_id: str,
    request: schemas.HITLConfirmationRequest,
    project: Project = Depends(dep_project),
    current_user: schemas.User = Depends(get_current_active_user),
) -> schemas.HITLConfirmationResponse:
    """
    Confirm tool execution

    User can choose:
    - confirm_all=true: Confirm all pending tools
    - tool_call_ids=[...]: Confirm specified tools

    After confirmation, tools will be executed and results returned via SSE stream.
    """
    if project.status != "opened":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project must be opened. Current status: {project.status}"
        )

    agent_manager = await get_project_agent_manager()
    agent_service = await agent_manager.get_agent(str(project.id), project.path)

    config = {"configurable": {"thread_id": session_id}}
    state = await agent_service._graph.aget_state(config)

    if not state or not state.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found"
        )

    values = state.values
    pending_tools = values.get("pending_tool_calls", [])

    if not pending_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending tools to confirm"
        )

    # Select tools to confirm based on request
    confirmed_tools = []
    if request.confirm_all:
        confirmed_tools = pending_tools
    elif request.tool_call_ids:
        confirmed_tools = [t for t in pending_tools if t["tool_call_id"] in request.tool_call_ids]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify either confirm_all=true or tool_call_ids"
        )

    if not confirmed_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tools matched the confirmation criteria"
        )

    # Update state: mark as confirmed
    await agent_service._graph.aupdate_state(
        config,
        {
            "confirmed_tool_calls": confirmed_tools,
            "pending_tool_calls": [],
            "hitl_confirmation_required": False
        }
    )

    # Continue execution flow
    try:
        new_state = await agent_service._graph.ainvoke(None, config)
    except Exception as e:
        logger.error("Error continuing graph execution: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing tools: {str(e)}"
        )

    return schemas.HITLConfirmationResponse(
        status="confirmed",
        confirmed_count=len(confirmed_tools),
        message=f"Confirmed {len(confirmed_tools)} tool(s) for execution"
    )


@router.post(
    "/sessions/{session_id}/hitl/reject",
    response_model=schemas.HITLConfirmationResponse,
    summary="Reject tool execution",
    description="User rejects to execute one or more pending tools"
)
async def reject_tool_execution(
    session_id: str,
    request: schemas.HITLRejectionRequest,
    project: Project = Depends(dep_project),
    current_user: schemas.User = Depends(get_current_active_user),
) -> schemas.HITLConfirmationResponse:
    """
    Reject tool execution

    User can choose:
    - reject_all=true: Reject all pending tools
    - tool_call_ids=[...]: Reject specified tools
    - reason: Rejection reason (will be fed back to LLM)

    After rejection, LLM will be notified and can provide alternative solution.
    """
    if project.status != "opened":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project must be opened. Current status: {project.status}"
        )

    agent_manager = await get_project_agent_manager()
    agent_service = await agent_manager.get_agent(str(project.id), project.path)

    config = {"configurable": {"thread_id": session_id}}

    rejected_tools = []
    if request.reject_all:
        state = await agent_service._graph.aget_state(config)
        if state and state.values:
            rejected_tools = state.values.get("pending_tool_calls", [])
    elif request.tool_call_ids:
        state = await agent_service._graph.aget_state(config)
        if state and state.values:
            pending = state.values.get("pending_tool_calls", [])
            rejected_tools = [t for t in pending if t["tool_call_id"] in request.tool_call_ids]

    if not rejected_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending tools to reject"
        )

    # Update state: mark as rejected
    await agent_service._graph.aupdate_state(
        config,
        {
            "rejected_tool_calls": rejected_tools,
            "pending_tool_calls": [],
            "hitl_confirmation_required": False
        }
    )

    # Continue execution flow, LLM will receive rejection notification
    try:
        new_state = await agent_service._graph.ainvoke(None, config)
    except Exception as e:
        logger.error("Error continuing graph execution: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing rejection: {str(e)}"
        )

    rejected_names = [t["tool_name"] for t in rejected_tools]
    return schemas.HITLConfirmationResponse(
        status="rejected",
        confirmed_count=0,
        message=f"Rejected {len(rejected_tools)} tool(s): {', '.join(rejected_names)}"
    )
```

---

### 3. Schema Layer

#### File: `gns3server/schemas/controller/chat.py`

##### Change 3.1: Add HITL-related Pydantic Models

**Location**: Add at end of file (after line 112)

```python
class PendingTool(BaseModel):
    """Information about pending tool"""
    tool_call_id: str = Field(..., description="Unique ID of the tool call")
    tool_name: str = Field(..., description="Tool name")
    tool_args: Dict[str, Any] = Field(..., description="Tool parameters")
    danger_level: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Danger level"
    )
    description: Optional[str] = Field(None, description="Tool execution description")


class HITLStatusResponse(BaseModel):
    """HITL status response"""
    status: Literal["idle", "waiting", "confirmed", "rejected"] = Field(
        ...,
        description="Current status"
    )
    pending_tools: List[PendingTool] = Field(
        default_factory=list,
        description="List of pending tools"
    )
    hitl_session_id: Optional[str] = Field(
        None,
        description="HITL session ID"
    )
    session_id: str = Field(..., description="Chat session ID")


class HITLConfirmationRequest(BaseModel):
    """HITL confirmation request"""
    confirm_all: bool = Field(
        default=False,
        description="Whether to confirm all pending tools"
    )
    tool_call_ids: Optional[List[str]] = Field(
        None,
        description="List of tool call IDs to confirm"
    )


class HITLRejectionRequest(BaseModel):
    """HITL rejection request"""
    reject_all: bool = Field(
        default=False,
        description="Whether to reject all pending tools"
    )
    tool_call_ids: Optional[List[str]] = Field(
        None,
        description="List of tool call IDs to reject"
    )
    reason: Optional[str] = Field(
        None,
        description="Rejection reason (will be fed back to LLM)"
    )


class HITLConfirmationResponse(BaseModel):
    """HITL confirmation response"""
    status: Literal["confirmed", "rejected"] = Field(
        ...,
        description="Operation status"
    )
    confirmed_count: int = Field(
        ...,
        description="Number of confirmed tools"
    )
    message: str = Field(..., description="Response message")
```

**Also update `__init__.py` exports**:

```python
# File: gns3server/schemas/__init__.py

# Add to import list
from .controller.chat import (
    # ... existing imports ...
    PendingTool,
    HITLStatusResponse,
    HITLConfirmationRequest,
    HITLRejectionRequest,
    HITLConfirmationResponse,
)
```

---

### 4. File Changes Summary

| File Path | Change Type | Line Changes | Risk Level |
|-----------|-------------|--------------|------------|
| `gns3_copilot.py` | Modify/Add | +200 lines | 🟡 Medium |
| `agent_service.py` | Modify | +10 lines | 🟢 Low |
| `chat.py` (API) | Add | +150 lines | 🟢 Low |
| `chat.py` (Schema) | Add | +50 lines | 🟢 Low |
| **Total** | - | **+410 lines** | - |

---

## Database Changes

### Checkpoint Table Structure

**Table Name**: `checkpoints` (managed by LangGraph)

**New Fields** (automatically added via MessagesState extension):

| Field Name | Type | Description |
|------------|------|-------------|
| `pending_tool_calls` | TEXT (JSON) | List of pending tool calls |
| `hitl_confirmation_required` | BOOLEAN | Whether HITL confirmation is needed |
| `hitl_session_id` | TEXT | HITL session ID |
| `confirmed_tool_calls` | TEXT (JSON) | Confirmed tool calls |
| `rejected_tool_calls` | TEXT (JSON) | Rejected tool calls |

**Migration Notes**:
- LangGraph automatically handles new state fields
- No manual database migration required
- Existing checkpoints are backward compatible

---

## API Specification

### 1. Get HITL Status

**Endpoint**: `GET /v3/projects/{project_id}/chat/sessions/{session_id}/hitl-status`

**Response Example**:
```json
{
    "status": "waiting",
    "pending_tools": [
        {
            "tool_call_id": "call_abc123",
            "tool_name": "execute_multiple_device_config_commands",
            "tool_args": {
                "project_id": "xxx",
                "device_configs": [
                    {
                        "device_name": "R1",
                        "config_commands": ["interface gig0/0", "ip address 10.0.0.1/24"]
                    }
                ]
            },
            "danger_level": "medium",
            "description": "Configure 1 device"
        }
    ],
    "hitl_session_id": "hitl_12345",
    "session_id": "chat_session_id"
}
```

### 2. Confirm Execution

**Endpoint**: `POST /v3/projects/{project_id}/chat/sessions/{session_id}/hitl/confirm`

**Request Body**:
```json
{
    "confirm_all": true,
    "tool_call_ids": null
}
```

**Or specify tools**:
```json
{
    "confirm_all": false,
    "tool_call_ids": ["call_abc123", "call_def456"]
}
```

**Response Example**:
```json
{
    "status": "confirmed",
    "confirmed_count": 2,
    "message": "Confirmed 2 tool(s) for execution"
}
```

### 3. Reject Execution

**Endpoint**: `POST /v3/projects/{project_id}/chat/sessions/{session_id}/hitl/reject`

**Request Body**:
```json
{
    "reject_all": true,
    "reason": "Configuration has errors, needs re-planning"
}
```

**Response Example**:
```json
{
    "status": "rejected",
    "confirmed_count": 0,
    "message": "Rejected 1 tool(s): execute_multiple_device_config_commands"
}
```

---

## Frontend Integration Guide

### 1. Detect HITL Status

```javascript
// Periodically poll HITL status
async function pollHITLStatus(sessionId) {
    const response = await fetch(
        `/api/v3/projects/${projectId}/chat/sessions/${sessionId}/hitl-status`
    );
    const status = await response.json();

    if (status.status === 'waiting' && status.pending_tools.length > 0) {
        showConfirmationDialog(status);
    }
}

// Poll every 2 seconds
setInterval(() => pollHITLStatus(sessionId), 2000);
```

### 2. Show Confirmation Dialog

```javascript
function showConfirmationDialog(hitlStatus) {
    const { pending_tools, hitl_session_id } = hitlStatus;

    const dialog = document.createElement('div');
    dialog.className = 'hitl-confirmation-dialog';

    let html = `
        <h3>⚠️ Please Confirm the Following Operations</h3>
        <div class="pending-tools">
    `;

    pending_tools.forEach(tool => {
        const icon = tool.danger_level === 'high' ? '🔴' : '🟡';
        html += `
            <div class="tool-item">
                <span class="danger-icon">${icon}</span>
                <span class="tool-name">${tool.tool_name}</span>
                <span class="tool-description">${tool.description}</span>
            </div>
        `;
    });

    html += `
        </div>
        <div class="actions">
            <button onclick="confirmAll('${hitl_session_id}')">Confirm All</button>
            <button onclick="rejectAll('${hitl_session_id}')">Reject All</button>
        </div>
    `;

    dialog.innerHTML = html;
    document.body.appendChild(dialog);
}

async function confirmAll(sessionId) {
    const response = await fetch(
        `/api/v3/projects/${projectId}/chat/sessions/${sessionId}/hitl/confirm`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_all: true })
        }
    );

    if (response.ok) {
        closeDialog();
        // Continue listening to SSE stream to get execution results
    }
}

async function rejectAll(sessionId) {
    const response = await fetch(
        `/api/v3/projects/${projectId}/chat/sessions/${sessionId}/hitl/reject`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reject_all: true, reason: 'User cancelled operation' })
        }
    );

    if (response.ok) {
        closeDialog();
    }
}
```

---

## Test Plan

### Unit Tests

```python
import pytest
from gns3server.agent.gns3_copilot.agent.gns3_copilot import (
    check_hitl_requirement,
    _is_dangerous_config
)

def test_dangerous_config_detection():
    """Test dangerous command detection"""
    tool_args = {
        "device_configs": [{
            "config_commands": ["reload", "write erase"]
        }]
    }

    assert _is_dangerous_config("execute_multiple_device_config_commands", tool_args) == True

def test_safe_config_detection():
    """Test safe command detection"""
    tool_args = {
        "device_configs": [{
            "config_commands": ["interface gig0/0", "ip address 10.0.0.1/24"]
        }]
    }

    assert _is_dangerous_config("execute_multiple_device_config_commands", tool_args) == False

def test_hitl_requirement_check():
    """Test HITL requirement check"""
    state = {
        "messages": [
            HumanMessage(content="Configure router"),
            AIMessage(
                content="",
                tool_calls=[{
                    "id": "call_123",
                    "name": "execute_multiple_device_config_commands",
                    "args": {"project_id": "test"}
                }]
            )
        ]
    }

    result = check_hitl_requirement(state)

    assert result["hitl_confirmation_required"] == True
    assert len(result["pending_tool_calls"]) == 1
```

### Integration Tests

```python
import pytest
from fastapi.testclient import TestClient

def test_hitl_flow():
    """Test complete HITL flow"""
    client = TestClient(app)

    # 1. Start chat
    response = client.post(
        f"/v3/projects/{project_id}/chat/stream",
        json={"message": "Configure all routers"}
    )

    # 2. Check HITL status
    status = client.get(f"/v3/projects/{project_id}/chat/sessions/{session_id}/hitl-status")
    assert status.json()["status"] == "waiting"
    assert len(status.json()["pending_tools"]) > 0

    # 3. Confirm execution
    confirm = client.post(
        f"/v3/projects/{project_id}/chat/sessions/{session_id}/hitl/confirm",
        json={"confirm_all": True}
    )
    assert confirm.json()["status"] == "confirmed"
```

---

## Deployment Steps

### Phase 1: Basic Infrastructure (1-2 days)

1. ✅ Extend MessagesState
2. ✅ Implement check_hitl_requirement node
3. ✅ Implement hitl_confirmation_node and conditional_tool_execution
4. ✅ Update LangGraph workflow
5. ✅ Unit tests

**Verification**: Existing functionality unaffected

### Phase 2: API Endpoints (1 day)

1. ✅ Add HITL status query endpoint
2. ✅ Add confirm/reject endpoints
3. ✅ Add Schema definitions
4. ✅ API tests

**Verification**: API can be called normally

### Phase 3: Frontend Integration (2-3 days)

1. ✅ Implement polling logic
2. ✅ Show confirmation dialog
3. ✅ Handle confirm/reject operations
4. ✅ Display execution results

**Verification**: End-to-end flow available

### Phase 4: Optimization and Enhancement (1-2 days)

1. ✅ Add dangerous command classification
2. ✅ Implement timeout handling
3. ✅ Add operation logging
4. ✅ Performance optimization

**Verification**: Production ready

---

## Parameter Modification Feature (Extension)

### Feature Overview

In addition to "Confirm/Reject", HITL also supports users modifying command parameters about to be executed, then feeding the modifications back to the LLM, which understands and executes with the new parameters.

### Complete Flow

```
LLM generates command A
       ↓
  HITL confirmation pause
       ↓
   Display to user
       ↓
┌─────────┼─────────┐
│         │         │
Direct Confirm   Reject    Modify to B
│         │         │
Execute A    Feedback LLM  Feedback (A→B) to LLM
                  ↓
              LLM understands modification
                  ↓
              Generate new tool call
                  ↓
              Execute B
```

### Conversation Example

```
User: Configure R1's gig0/0 interface to 10.0.0.1/24

LLM: I will configure R1's interface for you.

HITL: ⚠️ Please confirm the following operations
     Tool: execute_multiple_device_config_commands
     Parameters: {
       "device_configs": [{
         "device_name": "R1",
         "config_commands": [
           "interface gig0/0",
           "ip address 10.0.0.1 255.255.255.0"
         ]
       }]
     }

User: [Modify parameters]
     ip address 10.0.0.1 255.255.255.0
     → ip address 192.168.1.1 255.255.255.0
     [Save and Execute]

System feedback to LLM:
     User modified the command parameters about to be executed:
     Tool: execute_multiple_device_config_commands
     R1:
       Original commands: ['interface gig0/0', 'ip address 10.0.0.1 255.255.255.0']
       Modified to: ['interface gig0/0', 'ip address 192.168.1.1 255.255.255.0']
     Please execute according to the modified parameters.

LLM: Understood, I will use the modified IP address 192.168.1.1/24 to configure R1's gig0/0 interface.

[Tool execution execute_multiple_device_config_commands with modified args]

LLM: Configuration completed, R1's gig0/0 interface configured to 192.168.1.1/24.
```

### Implementation Points

#### 1. State Extension

Add to `MessagesState`:

```python
# User-modified fields
user_modified_args: dict | None  # Structure:
# {
#     "tool_call_id": str,
#     "original_args": dict,
#     "modified_args": dict
# }
```

#### 2. API Extension

New endpoint: `POST /v3/projects/{project_id}/chat/sessions/{session_id}/hitl/modify`

**Request Body**:
```python
{
    "tool_call_id": "call_abc123",
    "modified_args": {
        # Modified complete parameters
    }
}
```

**Response**:
```python
{
    "status": "modified",
    "modification_summary": "Show parameter differences",
    "message": "Feedback sent to AI"
}
```

#### 3. Backend Processing Flow

1. Receive modified parameters
2. Generate parameter difference summary
3. Add HumanMessage to conversation, explaining user's modification
4. Clear `pending_tool_calls` and `hitl_confirmation_required`
5. Set `user_modified_args` (used to trigger LLM regeneration)
6. Continue execution, LLM sees user's modification and generates new tool call
7. Execute new tool call

#### 4. Frontend Implementation Points

**UI Components**:
- Display original parameters and editing area
- Provide parameter difference highlighting (original vs new values)
- Support JSON format validation
- Save modification and execute button

**Interaction Flow**:
1. User clicks "Modify Parameters" button
2. Expand parameter editing area, display original JSON
3. User edits JSON in text box
4. Real-time JSON format validation
5. Click "Save and Execute" to submit modification
6. System shows modification summary and continues execution

**User Experience**:
- For configuration tools, can provide more friendly command-line interface instead of pure JSON
- Highlight modified parts (red strikethrough, green addition)
- Provide parameter preset templates
- Show before/after comparison view

### Key Code Locations

**File**: `gns3_copilot.py`

Enhance `conditional_tool_execution` function to detect `user_modified_args`:

```python
def conditional_tool_execution(state: MessagesState) -> dict:
    """Conditional tool execution node (supports user modification)"""

    # Handle user modification case
    if state.get("user_modified_args"):
        # LLM already received user modification via HumanMessage
        # Clear marker, let LLM regenerate tool call
        return {
            "user_modified_args": None,
            "pending_tool_calls": [],
            "hitl_confirmation_required": False
        }

    # ... other processing logic
```

**Parameter Difference Generation**:

```python
def _generate_modification_summary(tool_name: str, original: dict, modified: dict) -> str:
    """Generate parameter modification summary"""

    if tool_name == "execute_multiple_device_config_commands":
        # Special handling for configuration tools, compare command by command
        orig_devices = original.get("device_configs", [])
        mod_devices = modified.get("device_configs", [])

        summary = []
        for orig, mod in zip(orig_devices, mod_devices):
            device = orig.get("device_name", "")
            orig_cmds = orig.get("config_commands", [])
            mod_cmds = mod.get("config_commands", [])

            if orig_cmds != mod_cmds:
                summary.append(f"\n{device}:")
                for oc, mc in zip(orig_cmds, mod_cmds):
                    if oc != mc:
                        summary.append(f"  - {oc}")
                        summary.append(f"  + {mc}")

        return "\n".join(summary) if summary else "No modifications"

    # Other tools' generic handling
    # ...
```

### Security Considerations

#### Parameter Validation

- Validate modified parameter structure is complete
- Check required fields exist
- Validate parameter values are within legal range

#### Dangerous Command Secondary Confirmation

Even after modification, certain commands still require secondary confirmation:
- `erase startup-config`
- `reload`
- `format flash:`

### Test Cases

**Scenario**: User modifies configuration command

1. LLM generates configuration command: `ip address 10.0.0.1 255.255.255.0`
2. User modifies to: `ip address 192.168.1.1 255.255.255.0`
3. System shows modification summary
4. LLM understands and confirms using new IP
5. Execute tool with modified parameters
6. Verify configuration result

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation Measures |
|------|-------------|--------|---------------------|
| Breaking existing functionality | Low | High | Complete regression testing |
| State inconsistency | Medium | Medium | Checkpoint validation |
| Performance impact | Low | Low | Asynchronous processing |
| Frontend integration issues | Medium | Medium | Detailed frontend documentation |

---

## Rollback Plan

If rollback is needed:

1. Remove HITL-related nodes
2. Restore original `should_continue` and `tool_node`
3. Delete new API endpoints
4. New fields in checkpoint are automatically ignored

**Rollback Time**: Approximately 30 minutes

---

## Future Enhancements

1. **Batch operation optimization**: Support selective confirmation of some tools
2. **Operation history**: Record all HITL operations
3. **Automatic approval**: Set automatic approval rules for low-risk operations
4. **Multi-user collaboration**: Support multi-person approval process
5. **Template management**: Save commonly used configurations as templates

---

## Reference Documentation

- [LangGraph Interrupts](https://langchain-ai.github.io/langgraph/concepts/low_level/#interruption)
- [GNS3 Copilot Architecture](./ai-chat-api-design.md)
- [Tool Response Format Standard](./tool-response-format-standard.md)

---

**Document Version**: v1.0
**Created Date**: 2026-03-04
**Author**: GNS3 Development Team
