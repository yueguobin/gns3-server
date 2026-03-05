# TODO: Fix Orphan Tool Calls Causing Checkpoint State Inconsistency

## Problem Description

When the LangGraph agent terminates abnormally during execution (such as forced service shutdown, process crash, etc.), it may result in a checkpoint containing an `AIMessage` with `tool_calls` but no corresponding `ToolMessage`. This state inconsistency can cause errors during subsequent conversation recovery.

### Terminology

- **Orphan tool_calls**: `AIMessage` contains `tool_calls` field, but there's no corresponding `ToolMessage` in the message list
- **Checkpoint**: LangGraph's mechanism for persisting conversation state
- **State inconsistency**: Message state in checkpoint doesn't match expected message pairs (AIMessage + ToolMessage)

---

## Trigger Scenarios

### Scenario 1: Process Abnormal Termination (Primary Issue)

```
Execution flow:
User message → llm_call → AIMessage(tool_calls) → [Checkpoint saved]
                                                    ↓
                                            [Process crash/service shutdown]
                                                    ↓
                                            tool_node not executed
                                                    ↓
                                            Checkpoint contains:
                                            - AIMessage (has tool_calls) ✅
                                            - ToolMessage ❌ missing
```

**Trigger conditions:**
- LLM returns a response containing tool_calls
- Checkpoint has saved AIMessage
- Service is shut down before tool_node execution (kill -9, Ctrl+C, crash, etc.)

### Scenario 2: Maximum Call Count Reached (Already Handled)

Current code checks remaining steps after tool_node execution via the `recursion_limit_continue` function:

```python
def recursion_limit_continue(state: MessagesState) -> Literal["llm_call", END]:
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage):
        if state["remaining_steps"] < 4:
            return END
        return "llm_call"
    return END
```

**Execution flow:**
```
remaining_steps = 5
llm_call → AIMessage(tool_calls) → remaining_steps = 4
         ↓
    should_continue → tool_node (because there are tool_calls)
         ↓
    tool_node → ToolMessage → remaining_steps = 3
         ↓
    recursion_limit_continue → remaining_steps < 4 → END ✅
```

**Conclusion:** Scenario 2 won't produce orphan tool_calls because tool_node always executes and generates a ToolMessage.

---

## Fix Solution

### Core Idea

At the start of `stream_chat`, for existing sessions, detect and fix orphan tool_calls.

### Fix Strategy

**Strategy A: Clear tool_calls (Recommended)**

Create a new `AIMessage` with the same content as the original message but without the `tool_calls` field.

**Advantages:**
- Simple and clean
- Won't affect subsequent conversation
- User can ask the question again

**Disadvantages:**
- Loses LLM's original intent (but it already crashed, can't be recovered)

---

## Implementation Code

### 1. Add Fix Method (`agent_service.py`)

```python
async def _fix_orphan_tool_calls(self, graph, config: dict, session_id: str):
    """
    Detect and fix orphan tool_calls (AIMessage has tool_calls but no corresponding ToolMessage).

    Orphan tool_calls occur when the process crashes before tool_node execution.

    Uses LangGraph's aupdate_state API to safely create a new checkpoint version.
    """
    try:
        # 1. Read current state
        state = await graph.aget_state(config)
        if not state or not state.values.get("messages"):
            return

        messages = state.values["messages"]
        last_message = messages[-1]

        # 2. Detect orphan tool_calls
        if not (hasattr(last_message, "tool_calls") and last_message.tool_calls):
            return

        # Check if there's a corresponding ToolMessage
        has_tool_message = any(isinstance(m, ToolMessage) for m in messages)

        if has_tool_message:
            return

        log.warning("Detected orphan tool_calls: session=%s, will clear", session_id)

        # 3. Create fixed message (without tool_calls)
        from langchain.messages import AIMessage
        fixed_message = AIMessage(
            content=last_message.content,
            id=getattr(last_message, "id", None)
        )

        # 4. Use LangGraph API to update state (create new checkpoint)
        await graph.aupdate_state(config, {"messages": [fixed_message]})

        log.info("Orphan tool_calls fixed: session=%s", session_id)

    except Exception as e:
        log.error("Failed to fix orphan tool_calls: %s", e, exc_info=True)
```

### 2. Call in `stream_chat` (`agent_service.py`)

Add fix logic after getting the graph and before starting the stream:

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
) -> AsyncGenerator[Dict[str, Any], None]:
    # ... existing code ...

    # Get or create chat session
    repo = ChatSessionsRepository(self._checkpointer_conn)
    session = await repo.get_session_by_thread(session_id)
    is_new_session = session is None

    if is_new_session:
        # Create new session
        session = await repo.create_session(...)
        log.debug("Created new chat session: thread_id=%s", session_id)

    # ... set context variables ...

    # Build config
    config = {
        "configurable": {
            "thread_id": session_id,
            "project_id": project_id,
        },
        "metadata": {
            "user_id": user_id,
        },
    }

    # Build inputs
    inputs = {
        "messages": [HumanMessage(content=message, id=str(uuid4()))],
        "llm_calls": 0,
        "remaining_steps": 20,
        "mode": mode,
    }

    # Get the compiled graph
    graph = await self._get_graph()

    # 🔧 Fix state: for existing sessions, check and fix orphan tool_calls
    if not is_new_session:
        await self._fix_orphan_tool_calls(graph, config, session_id)

    log.debug("LangGraph graph obtained, starting stream")

    # ... continue existing code ...
```

### 3. Required Imports

Ensure `agent_service.py` has the following import:

```python
from langchain.messages import ToolMessage  # For detecting ToolMessage type
```

---

## Impact on Checkpoint Database

### LangGraph Checkpoint Mechanism

LangGraph checkpoints are **versioned** - each state update creates a new record:

```
checkpoints table structure:
- thread_id
- checkpoint_id (incrementing version number)
- checkpoint (serialized state data)
- metadata
- ...
```

### Security Analysis

| Aspect | Impact | Description |
|--------|--------|-------------|
| **Original data** | Preserved unchanged | `aupdate_state` creates new version, doesn't overwrite history |
| **Database structure** | Fully compatible | Uses LangGraph native API, won't break structure |
| **Concurrency safety** | Built-in protection | LangGraph has locking mechanism for concurrent access |
| **Storage overhead** | Minimal | Only adds one checkpoint record (about a few KB) |
| **Revertibility** | Supported | Can roll back to any version before fix |

### Not Direct Database Manipulation

**❌ Dangerous approach:**
```python
# Direct database modification - destructive
await conn.execute(
    "UPDATE checkpoints SET checkpoint = ? WHERE ...",
    [modified_json]
)
```

**Problems:**
- May break serialization format
- Doesn't create new version, overwrites history
- May cause database locking or corruption
- Violates LangGraph design principles

**✅ Safe approach:**
```python
# Use LangGraph's aupdate_state
await graph.aupdate_state(config, {"messages": [fixed_message]})
```

---

## Testing Methods

### Method 1: Simulated Crash Test (Recommended)

Simulate crash scenarios by forcibly shutting down the service:

```
Steps:
1. Start GNS3 service
2. Send a message that triggers tool_calls (e.g., query topology)
3. Observe logs, wait for AIMessage return (with tool_calls)
4. Force shutdown service before tool_node completes:
   - Method 1: kill -9 <pid>
   - Method 2: Ctrl+C (if supported)
5. Restart GNS3 service
6. Continue conversation using same session_id
7. Observe logs, should see:
   - "Detected orphan tool_calls: session=xxx, will clear"
   - "Orphan tool_calls fixed: session=xxx"
8. Verify conversation can proceed normally
```

### Method 2: Unit Tests

Directly construct orphan tool_calls state to test fix logic:

```python
# tests/test_agent_service.py

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage

@pytest.mark.asyncio
async def test_fix_orphan_tool_calls():
    """Test orphan tool_calls fix logic"""
    from gns3server.agent.gns3_copilot.agent_service import AgentService

    # Create test agent service
    service = AgentService("/tmp/test_project")
    await service._get_checkpointer()

    graph = await service._get_graph()
    config = {"configurable": {"thread_id": "test_session"}}

    # Construct orphan state: add normal messages first
    await graph.aupdate_state(
        config,
        {
            "messages": [
                HumanMessage(content="Test message", id="msg_1"),
                AIMessage(
                    content="Let me check for you",
                    id="msg_2",
                    tool_calls=[{
                        "id": "call_123",
                        "name": "get_topology",
                        "args": {"project_id": "test"}
                    }]
                )
                # Note: No corresponding ToolMessage
            ],
            "llm_calls": 1,
            "remaining_steps": 20
        }
    )

    # Call fix logic
    await service._fix_orphan_tool_calls(graph, config, "test_session")

    # Verify fix result
    state = await graph.aget_state(config)
    last_message = state.values["messages"][-1]

    # Should no longer have tool_calls
    assert not hasattr(last_message, "tool_calls") or not last_message.tool_calls
    assert last_message.content == "Let me check for you"

    # Cleanup
    await service.close()

@pytest.mark.asyncio
async def test_no_fix_when_normal():
    """Test that normal state isn't incorrectly fixed"""
    from gns3server.agent.gns3_copilot.agent_service import AgentService

    service = AgentService("/tmp/test_project")
    await service._get_checkpointer()

    graph = await service._get_graph()
    config = {"configurable": {"thread_id": "test_session_2"}}

    # Construct normal state: complete AIMessage + ToolMessage pair
    await graph.aupdate_state(
        config,
        {
            "messages": [
                HumanMessage(content="Test message", id="msg_1"),
                AIMessage(
                    content="Let me check for you",
                    id="msg_2",
                    tool_calls=[{
                        "id": "call_123",
                        "name": "get_topology",
                        "args": {"project_id": "test"}
                    }]
                ),
                ToolMessage(
                    content="Topology info: ...",
                    tool_call_id="call_123",
                    name="get_topology",
                    id="msg_3"
                )
            ],
            "llm_calls": 1,
            "remaining_steps": 20
        }
    )

    # Record original message count
    state_before = await graph.aget_state(config)
    msg_count_before = len(state_before.values["messages"])

    # Call fix logic
    await service._fix_orphan_tool_calls(graph, config, "test_session_2")

    # Verify state unchanged
    state_after = await graph.aget_state(config)
    msg_count_after = len(state_after.values["messages"])

    assert msg_count_before == msg_count_after  # Should not add new messages
    last_message = state_after.values["messages"][-1]
    assert isinstance(last_message, ToolMessage)  # Last is still ToolMessage

    # Cleanup
    await service.close()
```

### Method 3: Enhanced Logging and Monitoring

Even without active triggering, you can verify fix logic works in production:

```python
# Add detailed logging in _fix_orphan_tool_calls
log.warning("Detected orphan tool_calls: session=%s", session_id)
log.info("Original message: tool_calls=%d, content=%s",
         len(last_message.tool_calls),
         last_message.content[:100])
log.info("After fix: tool_calls=%d",
         len(fixed_message.tool_calls) if hasattr(fixed_message, "tool_calls") else 0)
```

---

## File Modification Checklist

### Files to Modify

1. **`gns3server/agent/gns3_copilot/agent_service.py`**
   - Add `_fix_orphan_tool_calls` method
   - Call fix logic in `stream_chat` method

### Test Files to Add (Optional)

2. **`tests/test_agent_service.py`** (create new or add to existing test file)
   - `test_fix_orphan_tool_calls()` - Test orphan tool_calls fix
   - `test_no_fix_when_normal()` - Test normal state isn't incorrectly fixed

---

## Implementation Steps

1. ✅ Create TODO document (current document)
2. ⬜ Add `_fix_orphan_tool_calls` method in `agent_service.py`
3. ⬜ Call fix logic in `stream_chat`
4. ⬜ Test fix effect using simulated crash method
5. ⬜ Add unit tests (optional)
6. ⬜ Update related documentation (if necessary)

---

## Related Code Files

- **Main modification file**: `gns3server/agent/gns3_copilot/agent_service.py`
- **Related file**: `gns3server/agent/gns3_copilot/agent/gns3_copilot.py`
- **Test file**: `tests/test_agent_service.py` (to be created)

---

## Reference Documentation

- [LangGraph Checkpointer Documentation](https://langchain-ai.github.io/langgraph/concepts/low_level/#checkpointer)
- [LangGraph State Management](https://langchain-ai.github.io/langgraph/concepts/low_level/#state)
- [GNS3-Copilot AI Chat API Design](../ai-chat-api-design.md)
