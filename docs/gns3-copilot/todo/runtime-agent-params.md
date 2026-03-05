# Runtime Agent Parameters

## Overview

This document describes the design and implementation plan for adding runtime control parameters to the GNS3-Copilot agent. Currently, iteration limits and tool call constraints are hardcoded. This enhancement will allow users to pass temporary parameters at request time to control agent behavior.

## Problem Statement

### Current Limitations

1. **Hard-coded iteration limit**: The maximum number of LLM-tool iterations is fixed at 20 in `agent_service.py`
2. **No tool call limit**: There's no runtime control over the maximum number of tool calls per request
3. **Inflexible for complex tasks**: Long-running automation tasks may require more iterations than the default
4. **No cost control**: Users cannot limit the number of expensive tool calls (e.g., device configuration operations)

### User Impact

```
Scenario: User wants to configure OSPF on 10 routers
- Each router requires ~2-3 tool calls (check config, apply config, verify)
- Total: ~20-30 tool calls needed
- Current: No way to predict or control this
- Desired: User can set max_tool_calls=30 to ensure completion
```

## Current Architecture

### Parameter Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. API Layer (chat.py)                                                  │
│    POST /v3/projects/{project_id}/chat/stream                          │
│    ChatRequest { message, session_id, temperature?, mode }             │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. Agent Service (agent_service.py)                                    │
│    stream_chat(message, session_id, project_id, user_id, jwt, mode)   │
│    → inputs = {                                                        │
│         "messages": [HumanMessage(...)],                               │
│         "llm_calls": 0,                                               │
│         "remaining_steps": 20,  ← HARDCODED                           │
│         "mode": mode                                                  │
│       }                                                               │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. Agent Graph (gns3_copilot.py)                                       │
│    recursion_limit_continue(state):                                    │
│      if state["remaining_steps"] < 4: return END                       │
│                                                                      │
│    tool_node(state):                                                  │
│      → Execute tools without limit check                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Existing Controls

| Parameter | Location | Value | Description |
|-----------|----------|-------|-------------|
| `remaining_steps` | `agent_service.py:281` | 20 (hardcoded) | Total iteration count |
| Recursion threshold | `gns3_copilot.py` | `< 4` | Stop when remaining < 4 |
| `temperature` | `chat.py` | Reserved but not implemented | Runtime temperature override |

## Proposed Solution

### Option A: Simple Extension (Recommended)

**Scope**: API Schema + Agent Service modifications only

#### 1. API Schema Changes

**File**: `gns3server/schemas/controller/chat.py`

```python
class ChatRequest(BaseModel):
    """Chat request model."""

    message: str = Field(..., description="User message content")
    session_id: Optional[str] = Field(None, description="Session ID")
    stream: bool = Field(default=True, description="Enable streaming response")
    mode: Literal["text"] = Field(default="text", description="Interaction mode")

    # New runtime control parameters
    max_iterations: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Maximum number of LLM-tool iterations (default: 20). "
                    "Each iteration = LLM call + optional tool execution."
    )
    max_tool_calls: Optional[int] = Field(
        None,
        ge=1,
        le=50,
        description="Maximum number of tool calls per request (default: unlimited). "
                    "Useful for cost control and preventing runaway automation."
    )
```

#### 2. Agent Service Changes

**File**: `gns3server/agent/gns3_copilot/agent_service.py`

```python
async def stream_chat(
    self,
    message: str,
    session_id: str,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    jwt_token: Optional[str] = None,
    mode: str = "text",
    llm_config: Optional[Dict[str, Any]] = None,
    # New parameters
    max_iterations: Optional[int] = None,
    max_tool_calls: Optional[int] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream chat responses from the agent.

    Args:
        message: User message
        session_id: Session/thread ID for conversation continuity
        project_id: GNS3 project ID (optional, for context)
        user_id: User ID for metadata tracking
        jwt_token: JWT token for API authentication (optional)
        mode: Interaction mode (default: "text")
        llm_config: LLM configuration dict (provider, model, api_key, etc.)
        max_iterations: Maximum LLM-tool iterations (default: 20)
        max_tool_calls: Maximum tool calls per request (default: unlimited)

    Yields:
        Dict containing SSE-compatible response chunks
    """
    log.info(
        "Stream chat started: project_id=%s, user_id=%s, session_id=%s, mode=%s, "
        "max_iterations=%s, max_tool_calls=%s",
        project_id,
        user_id,
        session_id,
        mode,
        max_iterations,
        max_tool_calls,
    )

    # ... existing session setup code ...

    # Build inputs with runtime parameters
    inputs = {
        "messages": [HumanMessage(content=message, id=str(uuid4()))],
        "llm_calls": 0,
        "remaining_steps": max_iterations or 20,  # Use runtime parameter or default
        "max_tool_calls": max_tool_calls or 999,   # New: tool call limit
        "tool_calls_count": 0,                     # New: counter
        "mode": mode,
    }

    # ... rest of existing code ...
```

#### 3. Agent Graph Changes

**File**: `gns3server/agent/gns3_copilot/agent/gns3_copilot.py`

```python
def tool_node(state: dict, config: RunnableConfig | None = None):
    """
    Performs the tool call with max_tool_calls limit.

    Args:
        state: Current agent state containing messages and tool_calls
        config: Runnable configuration (optional)

    Returns:
        Dict with tool execution results or error message if limit exceeded
    """
    tool_calls = state["messages"][-1].tool_calls
    result = []

    # Check tool call limit
    max_tool_calls = state.get("max_tool_calls", 999)
    current_tool_calls = state.get("tool_calls_count", 0)

    if current_tool_calls + len(tool_calls) > max_tool_calls:
        log.warning(
            "Tool call limit exceeded: current=%d, requested=%d, max=%d",
            current_tool_calls,
            len(tool_calls),
            max_tool_calls
        )
        # Return error message for each tool call
        for tool_call in tool_calls:
            result.append(
                ToolMessage(
                    content=f"Tool call limit reached ({max_tool_calls} calls). "
                           f"Please simplify your request or break it into smaller steps. "
                           f"Current tool call count: {current_tool_calls}/{max_tool_calls}.",
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"]
                )
            )
        return {"messages": result}

    # Execute tools normally
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool = tools_by_name[tool_name]
        try:
            observation = tool.invoke(tool_call["args"])
        except Exception as e:
            log.error("Error executing tool %s: %s", tool_name, e)
            observation = f"Error: {str(e)}"
        result.append(
            ToolMessage(
                content=observation,
                tool_call_id=tool_call["id"],
                name=tool_call["name"]
            )
        )

    # Update tool call counter
    return {
        "messages": result,
        "tool_calls_count": current_tool_calls + len(tool_calls)
    }
```

### State Management

The agent state needs to track the new fields:

```python
# Existing MessagesState already has:
# - messages: Annotated[List[BaseMessage], add_messages]
# - llm_calls: int
# - remaining_steps: int (from RemainingSteps)

# We add:
# - max_tool_calls: int (per-request limit)
# - tool_calls_count: int (running counter)
```

## Implementation Plan

| Step | Task | File(s) | Difficulty | Priority |
|------|------|---------|------------|----------|
| 1 | Extend `ChatRequest` schema | `schemas/controller/chat.py` | ⭐ Low | P0 |
| 2 | Modify `stream_chat` signature | `agent_service.py` | ⭐ Low | P0 |
| 3 | Use `max_iterations` in inputs | `agent_service.py` | ⭐ Low | P0 |
| 4 | Implement `max_tool_calls` logic | `gns3_copilot.py` | ⭐⭐ Medium | P1 |
| 5 | Add tool call counter to state | `gns3_copilot.py` | ⭐ Low | P1 |
| 6 | Update API documentation | `docs/` | ⭐ Low | P1 |
| 7 | Add unit tests | `tests/` | ⭐⭐ Medium | P2 |

## Usage Examples

### Basic Usage

```bash
# Default behavior (no changes needed)
curl -X POST http://localhost:3080/v3/projects/{project_id}/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "配置所有路由器的 OSPF"
  }'
```

### With Custom Iteration Limit

```bash
# Allow more iterations for complex multi-device configuration
curl -X POST http://localhost:3080/v3/projects/{project_id}/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "在10台路由器上配置OSPF、BGP和静态路由，然后验证连通性",
    "max_iterations": 50
  }'
```

### With Tool Call Limit

```bash
# Limit tool calls for cost control
curl -X POST http://localhost:3080/v3/projects/{project_id}/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "检查所有设备的接口状态",
    "max_tool_calls": 15
  }'
```

### Combined Parameters

```bash
# Complex task with both limits
curl -X POST http://localhost:3080/v3/projects/{project_id}/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "配置整个实验室的网络并测试连通性",
    "max_iterations": 40,
    "max_tool_calls": 30
  }'
```

## Security Considerations

### Parameter Limits

| Parameter | Min | Max | Default | Rationale |
|-----------|-----|-----|---------|-----------|
| `max_iterations` | 1 | 100 | 20 | Prevent infinite loops, allow complex tasks |
| `max_tool_calls` | 1 | 50 | unlimited (999) | Prevent tool abuse, control cost |

### Risk Mitigation

1. **Upper bounds enforced**: Pydantic validation prevents excessive values
2. **Graceful degradation**: Agent returns informative error messages when limits are reached
3. **Per-request scope**: Parameters don't persist across sessions
4. **Audit logging**: All parameters are logged for security analysis

### Edge Cases

```
Case 1: max_iterations = 1
  → Only one LLM call, no tool execution
  → Useful for simple Q&A without actions

Case 2: max_tool_calls = 1
  → Agent can only call one tool
  → Forces user to break complex tasks into smaller steps

Case 3: LLM ignores limits
  → Agent enforces limits at execution time
  → Returns error when limit exceeded
```

## Backward Compatibility

✅ **Fully backward compatible**

- All new parameters are `Optional`
- Default values match current behavior
- Existing clients continue to work without changes
- No database migrations required

## Testing Strategy

### Unit Tests

```python
def test_max_iterations_enforced():
    """Test that agent respects max_iterations parameter"""
    # Create request with max_iterations=5
    # Verify agent stops after 5 iterations

def test_max_tool_calls_enforced():
    """Test that agent respects max_tool_calls parameter"""
    # Create request with max_tool_calls=3
    # Trigger 5 tool calls
    # Verify only 3 execute, rest return error

def test_default_behavior_unchanged():
    """Test that omitting parameters uses defaults"""
    # Create request without new parameters
    # Verify behavior matches current implementation
```

### Integration Tests

```python
async def test_complex_multi_device_task():
    """Test complex task with increased limits"""
    # Configure OSPF on 10 routers
    # max_iterations=30, max_tool_calls=25
    # Verify successful completion

async def test_tool_limit_error_message():
    """Test that limit errors are informative"""
    # Set max_tool_calls=2
    # Trigger 3 tool calls
    # Verify third call returns helpful error message
```

## Future Enhancements

### Phase 2 Features

1. **Per-tool limits**:
   ```python
   max_device_config_calls: Optional[int] = None
   max_diagnostic_calls: Optional[int] = None
   ```

2. **Time-based limits**:
   ```python
   max_execution_time_seconds: Optional[int] = None
   ```

3. **Cost estimation**:
   ```python
   estimate_cost_before_execution: bool = False
   ```

4. **Adaptive limits**:
   ```python
   auto_adjust_limits: bool = False  # AI decides optimal limits
   ```

### Advanced Configuration

```python
class AdvancedAgentControls(BaseModel):
    """Advanced runtime controls for power users"""

    # Execution limits
    max_iterations: Optional[int] = None
    max_tool_calls: Optional[int] = None
    max_execution_time_seconds: Optional[int] = None

    # Tool-specific limits
    tool_limits: Dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool call limits, e.g., {'execute_multiple_device_commands': 10}"
    )

    # Retry behavior
    max_retries_per_tool: int = Field(default=1, ge=0, le=5)
    retry_on_tool_error: bool = Field(default=False)

    # Parallel execution
    max_parallel_tools: int = Field(default=5, ge=1, le=20)

    # Fallback behavior
    on_limit_reached: Literal["fail", "warn", "continue"] = "warn"
```

## Related Documentation

- [AI Chat API Design](../ai-chat-api-design.md)
- [HITL Implementation Plan](./hitl-implementation-plan.md)
- [Tool Response Format Standard](./tool-response-format-standard.md)

## References

- LangGraph State Management: https://langchain-ai.github.io/langgraph/concepts/low_level/#state
- Pydantic Field Validation: https://docs.pydantic.dev/latest/concepts/fields/
- GNS3 Controller API: https://api.gns3.com/

## Discussion Points

### Open Questions

1. **Should limits be per-message or per-session?**
   - Current: Per-message (per request)
   - Alternative: Per-session (accumulate across conversation)

2. **Should we expose `remaining_steps` in the response?**
   - Pro: User knows how many iterations left
   - Con: Exposes internal implementation details

3. **Should we allow dynamic limit adjustment during execution?**
   - Requires streaming parameter updates
   - More complex but more flexible

4. **What about `temperature` override?**
   - Already reserved in schema but not implemented
   - Should we implement it in the same change?

### Decision Required

- [ ] Confirm parameter ranges (min/max values)
- [ ] Decide on error handling strategy (fail vs warn)
- [ ] Approve implementation plan
- [ ] Set target release version

---

**Status**: Design Draft - Ready for Review

**Author**: GNS3 Copilot Team

**Last Updated**: 2025-03-06

**Target Version**: TBD
