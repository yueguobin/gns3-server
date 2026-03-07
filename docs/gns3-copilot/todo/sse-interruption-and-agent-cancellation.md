# SSE Connection Interruption and Agent Cancellation Design

## Overview

This document describes the behavior when SSE connection is interrupted during agent execution, how statistics are handled, and strategies for graceful agent cancellation.

## Current Behavior Analysis

### What Happens When SSE Connection Drops

| Component | Behavior | Persists After Disconnect |
|-----------|----------|---------------------------|
| LangGraph Checkpoint | Auto-saved after each node completes | ✅ Yes |
| Messages in conversation | Saved to checkpoint | ✅ Yes |
| Session statistics (message_count, tokens, etc.) | Not updated | ❌ Lost |
| Auto-generated title | Not synced | ❌ Lost |

### LangGraph Checkpoint Mechanism

LangGraph automatically saves checkpoint after each node completes:

```
llm_call (AI generates response)
    ↓ checkpoint saved
should_continue (decides if tools needed)
    ↓ checkpoint saved
tool_node (executes tools)
    ↓ checkpoint saved
llm_call (processes tool results)
    ...
```

**Important**: Checkpoint is saved at node boundaries, not during node execution.

## Statistics Tracking Issue

### Current Implementation

```python
message_count = 1  # User message
llm_calls_count = 0

async for event in graph.astream_events(...):
    if event_type == "on_chat_model_start":
        llm_calls_count += 1
    elif event_type == "on_chat_model_end":
        message_count += 1
    elif event_type == "on_tool_end":
        message_count += 1
```

Statistics are calculated during streaming and only persisted after successful completion:

```python
try:
    async for event in graph.astream_events(...):
        yield chunk
except Exception as e:
    yield {"type": "error", ...}
# Statistics update - only runs on successful completion!
await repo.update_session(message_count=message_count, ...)
```

### Problem

When connection drops mid-stream:
- Statistics are calculated in-memory but never persisted
- Values may be incomplete/inaccurate (e.g., 2 LLM calls made but only 1 counted)

## Graceful Shutdown Strategy

### Recommended: try/finally Approach

Add `try/finally` to ensure statistics are updated even on disconnection:

```python
async def stream_chat(...):
    try:
        async for event in graph.astream_events(inputs, config=config, version="v2"):
            try:
                yield chunk  # May raise exception on client disconnect
            except Exception:
                log.info("Client disconnected, stopping stream")
                break
    except Exception as e:
        yield {"type": "error", "error": str(e)}
    finally:
        # Always update statistics, even on disconnect
        await repo.update_session(
            thread_id=session_id,
            message_count=message_count,
            llm_calls_count=llm_calls_count,
            ...
        )
```

### Benefits

- Statistics are recorded even on disconnection
- Title sync attempt on every request
- Minimal performance overhead (single DB write)

### Trade-offs

- Statistics may be inaccurate if disconnection happens mid-processing
- If LLM call fails, partial statistics still recorded

## Agent Cancellation Analysis

### Scenarios and Impact

| Cancellation Timing | State | Issue |
|---------------------|-------|-------|
| Before llm_call | User message sent | No response, no issue |
| After llm_call, has tool_call | AI requested tool execution | ⚠️ Has tool_call, no tool_result |
| During tool_node | Tool executing | May partially execute |
| After tool_node | Tool result returned | Clean state |

### Key Concern: Orphan tool_calls

The most dangerous scenario: AI generates `tool_call` but execution hasn't started:

```json
// Incomplete message:
{
  "role": "assistant",
  "tool_calls": [{"name": "execute_command", "arguments": "..."}]
  // No corresponding ToolMessage!
}
```

### LangGraph Cancellation Handling

LangGraph handles cancellation automatically:

1. **Checkpoint at node boundaries**: Messages are saved after each node completes
2. **Cancellation preserves state**: When cancelled, checkpoint is saved automatically
3. **Message consistency**: Either complete (tool_call + ToolMessage) or no tool_call

```python
# When cancellation happens:
async def stream_chat(...):
    try:
        async for event in graph.astream_events(...):
            yield chunk
    except CancelledError:
        # LangGraph auto-saves checkpoint before raising
        log.info("Request cancelled, checkpoint saved")
    finally:
        await repo.update_session(...)
```

### Handling Incomplete Messages

When reconnecting, check for incomplete messages:

```python
async def get_history(session_id):
    state = await graph.aget_state(config)
    messages = state.values["messages"]

    # Check for orphan tool_calls
    last_msg = messages[-1] if messages else None
    if last_msg and last_msg.tool_calls and not has_tool_result(messages):
        # Handle incomplete message
        # Option 1: Show as "interrupted"
        # Option 2: Auto-resume tool execution
        # Option 3: Ask user to retry
```

## Frontend Integration

### Handling Disconnection

```javascript
// On connection close:
window.addEventListener('beforeunload', () => {
  // Connection will close, server will handle cleanup
});

// On reconnect - fetch history:
const history = await fetch(`/chat/sessions/${sessionId}/history`);
const data = await history.json();

// Check for incomplete messages
if (data.messages.length > 0) {
  const lastMsg = data.messages[data.messages.length - 1];
  if (lastMsg.tool_calls && !lastMsg.content) {
    // Message was interrupted - handle appropriately
    showWarning("Previous response was interrupted");
  }
}
```

## Future Enhancements

### Optional: Cancel Endpoint

For explicit cancellation (not just disconnection):

```python
# Request management
request_manager = RequestManager()

@router.post("/stream/{request_id}/cancel")
async def cancel_stream(request_id: str):
    request_manager.cancel(request_id)

# In stream_chat:
async def stream_chat(request_id: str, ...):
    request_manager.register(request_id)
    try:
        async for event in graph.astream_events(...):
            if request_manager.is_cancelled(request_id):
                break
            yield chunk
    finally:
        request_manager.unregister(request_id)
```

**Complexity**: Requires request ID tracking, state management, and coordination.

**Current recommendation**: Not necessary - disconnection naturally stops the stream.

## Summary

| Aspect | Current Behavior | Recommended Fix |
|--------|-----------------|-----------------|
| Messages | Auto-saved to checkpoint | Already correct |
| Statistics | Lost on disconnect | Add try/finally |
| Title sync | Lost on disconnect | Add try/finally |
| Cancellation | Handled by LangGraph | Already correct |
| Incomplete messages | Handled on reconnect | Document frontend handling |

## Action Items

1. [ ] Add try/finally to ensure statistics update
2. [ ] Add client disconnect detection in yield loop
3. [ ] Document frontend handling for incomplete messages
4. [ ] Test reconnection scenario with tool_call interruption
