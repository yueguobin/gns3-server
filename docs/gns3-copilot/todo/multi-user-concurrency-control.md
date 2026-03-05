# Multi-User Device Concurrency Control

**Status:** TODO
**Priority:** HIGH
**Created:** 2025-03-06
**Author:** GNS3-Copilot Team

---

## Problem Statement

When multiple users simultaneously use the GNS3-Copilot Agent to operate on the same network device node, a race condition occurs because all operations connect through the same telnet console port.

### Current Architecture

```
User A → Agent → Netmiko → telnet console:5000 ─┐
                                            ├──→ R1 (Shared Console)
User B → Agent → Netmiko → telnet console:5000 ─┘
```

### Affected Components

| Tool | Connection Method | File |
|------|------------------|------|
| `execute_multiple_device_config_commands` | Netmiko (netmiko_send_config) | `tools_v2/config_tools_nornir.py` |
| `execute_multiple_device_commands` | Netmiko (netmiko_multiline) | `tools_v2/display_tools_nornir.py` |
| `vpcs_multi_commands` | telnetlib3 | `tools_v2/vpcs_tools_telnetlib3.py` |

### Conflict Scenario Example

```
Timeline:
T1: User A executes "conf t" → Device enters configuration mode
T2: User B executes "show run" → May see config mode prompt
T3: User B executes "interface Gig0/0" → Interrupts User A's configuration
T4: User A's output contains User B's commands (confusion!)
T5: User A executes "ip address 1.1.1.1 255.255.255.255" → Applies to wrong interface
```

**Impact:**
- Configuration applied to wrong interface/context
- Mixed output from different users
- Lost commands or unintended configuration changes
- Unpredictable device state

---

## Proposed Solutions

### Solution 1: Device-Level Mutex Lock (RECOMMENDED)

**Implementation Location:** `gns3server/agent/gns3_copilot/utils/device_lock.py`

Create a device-level lock manager to ensure only one user can operate on a device at a time.

#### Architecture

```python
class DeviceLockManager:
    """Manages exclusive access to network devices"""

    def __init__(self):
        # device_name -> asyncio.Lock
        self._locks: Dict[str, asyncio.Lock] = {}
        self._manager_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire_device(self, device_name: str, user_id: str, timeout: float = 30.0):
        """
        Acquire exclusive lock on a device.

        Args:
            device_name: Name of the device (e.g., "R-1")
            user_id: User ID requesting the lock
            timeout: Maximum time to wait for lock (seconds)

        Raises:
            RuntimeError: If timeout waiting for lock
        """
        lock = self._get_lock(device_name)

        logger.info("User %s requesting lock for device %s...", user_id, device_name)

        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            logger.info("✓ User %s acquired lock for device %s", user_id, device_name)
            yield
        except asyncio.TimeoutError:
            logger.warning("✗ User %s timeout waiting for device %s", user_id, device_name)
            raise RuntimeError(
                f"Device {device_name} is busy with another user's operation. "
                f"Please wait a moment and try again."
            )
        finally:
            lock.release()
            logger.info("User %s released lock for device %s", user_id, device_name)
```

#### Tool Integration

Modify tool `_run()` methods to use locks:

```python
# In config_tools_nornir.py
from gns3server.agent.gns3_copilot.utils.device_lock import _device_lock_manager
from gns3server.agent.gns3_copilot.gns3_client.context_helpers import get_current_llm_config

async def _run(self, tool_input: str, run_manager=None, **kwargs):
    # Get user_id from context
    llm_config = get_current_llm_config()
    user_id = llm_config.get("user_id", "unknown") if llm_config else "unknown"

    device_configs_list, project_id = self._validate_tool_input(tool_input)

    results = []
    for device_config in device_configs_list:
        device_name = device_config["device_name"]

        # Acquire lock before operating on device
        async with _device_lock_manager.acquire_device(device_name, user_id):
            # Execute configuration
            result = await self._execute_config_on_device(device_config, project_id)
            results.append(result)

    return results
```

**Pros:**
- Simple implementation
- Clear ownership (user knows who has the lock)
- Automatic timeout prevents deadlocks

**Cons:**
- Single-process only (no cross-server locking)
- Users must wait if device is busy

---

### Solution 2: Transactional Operations with Mode Cleanup

Ensure device state consistency before and after operations.

```python
async def _safe_execute_config(self, connection, config_commands):
    """Safely execute config with guaranteed state cleanup"""

    # 1. Ensure privileged mode (not config mode)
    try:
        connection.exit_config_mode()
        connection.find_prompt()
    except:
        pass

    try:
        # 2. Execute configuration
        result = connection.send_config_set(config_commands)
        return result
    finally:
        # 3. Always cleanup: exit config mode
        try:
            connection.exit_config_mode()
        except:
            pass
```

**Pros:**
- Reduces chance of leaving device in bad state
- Works as safety layer alongside locks

**Cons:**
- Doesn't prevent concurrent access (needs Solution 1)
- Adds overhead to each operation

---

### Solution 3: Frontend User Notification

Display device lock status in the UI to inform users.

#### Backend Events

```python
# In AgentService.stream_chat()
async with _device_lock_manager.acquire_device(device_name, user_id):
    # Emit lock acquired event
    yield {
        "type": "device_lock_acquired",
        "device_name": device_name,
        "user_id": user_id,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        # Execute operations
        result = await self._execute(...)
        yield {"type": "tool_end", "output": result}
    finally:
        # Emit lock released event
        yield {
            "type": "device_lock_released",
            "device_name": device_name,
            "timestamp": datetime.utcnow().isoformat(),
        }
```

#### Frontend Handling

```javascript
// WebSocket event listeners
socket.on('device_lock_acquired', (data) => {
  showNotification(
    `Device ${data.device} is locked by user ${data.user}`,
    'warning'
  );
  disableDeviceControls(data.device);
});

socket.on('device_lock_released', (data) => {
  hideNotification(data.device);
  enableDeviceControls(data.device);
});

socket.on('device_lock_timeout', (data) => {
  showError(
    `Could not acquire lock on ${data.device}. ` +
    `Another user is operating on it. Please wait.`
  );
});
```

**Pros:**
- Better UX (users know why they're waiting)
- Transparency about device usage

**Cons:**
- Requires frontend changes
- More complex WebSocket protocol

---

### Solution 4: Distributed Lock (Multi-Server Deployment)

For production deployments with multiple GNS3 Server instances.

#### Redis-based Lock Manager

```python
# Requires: pip install aioredis
import aioredis

class RedisDeviceLockManager:
    """Distributed device lock using Redis"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = aioredis.from_url(redis_url)

    @asynccontextmanager
    async def acquire_device(self, device_name: str, user_id: str):
        key = f"gns3:device_lock:{device_name}"
        lock = self.redis.lock(
            key,
            timeout=60,           # Auto-release after 60s
            blocking_timeout=30   # Wait max 30s
        )

        try:
            await lock.acquire()
            # Store metadata
            await self.redis.hset(
                f"{key}:meta",
                mapping={
                    "user_id": user_id,
                    "acquired_at": datetime.utcnow().isoformat(),
                }
            )
            yield
        finally:
            await self.redis.delete(f"{key}:meta")
            await lock.release()
```

**Pros:**
- Works across multiple server instances
- Centralized lock management
- Persistent lock state

**Cons:**
- Requires Redis infrastructure
- More complex deployment

---

## Implementation Plan

### Phase 1: Core Lock Implementation (Priority: HIGH)

**Tasks:**

1. **Create Device Lock Manager**
   - [ ] Create `gns3server/agent/gns3_copilot/utils/device_lock.py`
   - [ ] Implement `DeviceLockManager` class with asyncio locks
   - [ ] Add comprehensive logging for lock acquisition/release
   - [ ] Add unit tests for lock behavior

2. **Integrate with Config Tools**
   - [ ] Modify `config_tools_nornir.py::ExecuteMultipleDeviceConfigCommands._run()`
   - [ ] Extract user_id from request context
   - [ ] Wrap device operations in lock context manager
   - [ ] Handle timeout exceptions gracefully

3. **Integrate with Display Tools**
   - [ ] Modify `display_tools_nornir.py::ExecuteMultipleDeviceCommands._run()`
   - [ ] Add same lock protection for read operations
   - [ ] Consider allowing concurrent reads (readers-writer lock?)

4. **Integrate with VPCS Tools**
   - [ ] Modify `vpcs_tools_telnetlib3.py::VPCSMultiCommands._run()`
   - [ ] Add lock protection

5. **Add Mode Cleanup**
   - [ ] Implement `_safe_execute_config()` helper
   - [ ] Ensure all operations exit config mode after completion

**Estimated Effort:** 2-3 days

**Testing Checklist:**
- [ ] Single user operation (baseline)
- [ ] Two users configuring same device simultaneously
- [ ] Two users reading same device simultaneously
- [ ] One user configuring, one user reading same device
- [ ] Lock timeout behavior
- [ ] Lock release on exception
- [ ] Concurrent operations on different devices (should not block)

---

### Phase 2: User Experience Enhancements (Priority: MEDIUM)

**Tasks:**

1. **Backend Events**
   - [ ] Emit `device_lock_acquired` events
   - [ ] Emit `device_lock_released` events
   - [ ] Emit `device_lock_timeout` events
   - [ ] Include device_name, user_id, timestamp in events

2. **Frontend Integration**
   - [ ] Add WebSocket listeners for lock events
   - [ ] Display lock status badges on device cards
   - [ ] Show toast notifications for lock state changes
   - [ ] Disable controls while locked
   - [ ] Add "Waiting for lock..." indicator

3. **Error Messages**
   - [ ] Localize timeout messages
   - [ ] Add helpful hints (e.g., "Wait 30 seconds and retry")
   - [ ] Include which user has the lock

**Estimated Effort:** 3-4 days

---

### Phase 3: Production Readiness (Priority: LOW)

**Tasks:**

1. **Distributed Lock**
   - [ ] Add Redis dependency to `requirements.txt`
   - [ ] Implement `RedisDeviceLockManager`
   - [ ] Add configuration option (memory vs redis)
   - [ ] Document Redis setup

2. **Monitoring**
   - [ ] Add metrics: lock wait time, lock hold time
   - [ ] Add Prometheus exporters
   - [ ] Dashboard for lock statistics

3. **Advanced Features**
   - [ ] Lock queue (FIFO waitlist)
   - [ ] Lock priority (admin vs regular user)
   - [ ] Forced lock release (admin override)
   - [ ] Lock expiration handling

**Estimated Effort:** 5-7 days

---

## Design Considerations

### Lock Granularity

**Options:**

| Granularity | Description | Pros | Cons |
|-------------|-------------|------|------|
| Per-device | Lock on each device | Fine-grained, good concurrency | More complex |
| Per-project | Lock entire project | Simple | Blocks unrelated operations |
| Per-user | One lock per user | Fair | Low concurrency |

**Recommendation:** Start with per-device locks for optimal balance.

### Concurrent Reads

Consider allowing multiple concurrent read operations (show commands) while blocking writes:

```python
class ReadersWriterDeviceLock:
    """Allows multiple concurrent readers, exclusive writer"""

    def __init__(self):
        self._readers = 0
        self._writer_lock = asyncio.Lock()
        self._reader_lock = asyncio.Lock()

    async def acquire_read(self):
        """Acquire read lock (shared)"""
        async with self._reader_lock:
            self._readers += 1
            if self._readers == 1:
                await self._writer_lock.acquire()

    async def release_read(self):
        """Release read lock"""
        async with self._reader_lock:
            self._readers -= 1
            if self._readers == 0:
                self._writer_lock.release()

    async def acquire_write(self):
        """Acquire write lock (exclusive)"""
        await self._writer_lock.acquire()

    async def release_write(self):
        """Release write lock"""
        self._writer_lock.release()
```

### Timeout Strategy

**Recommended timeouts:**

| Operation | Timeout | Rationale |
|-----------|---------|-----------|
| Lock acquisition | 30s | User patience limit |
| Lock auto-release | 120s | Prevent stale locks |
| Read operation | 60s | show commands are fast |
| Config operation | 90s | Configuration takes longer |

---

## Testing Strategy

### Unit Tests

```python
# tests/test_device_lock.py
import pytest
from utils.device_lock import DeviceLockManager

@pytest.mark.asyncio
async def test_single_lock_acquisition():
    manager = DeviceLockManager()

    async with manager.acquire_device("R-1", "user_a"):
        assert True  # Should not raise

@pytest.mark.asyncio
async def test_concurrent_lock_rejection():
    manager = DeviceLockManager()
    lock_a_acquired = False

    async def user_a():
        nonlocal lock_a_acquired
        async with manager.acquire_device("R-1", "user_a"):
            lock_a_acquired = True
            await asyncio.sleep(0.5)

    async def user_b():
        await asyncio.sleep(0.1)  # Let A acquire first
        with pytest.raises(RuntimeError):
            async with manager.acquire_device("R-1", "user_b", timeout=0.3):
                pass

    await asyncio.gather(user_a(), user_b())
    assert lock_a_acquired
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_concurrent_config_operations():
    """Simulate two users configuring same device"""
    service = AgentService(project_path)

    async def user_a_config():
        return await service.stream_chat(
            "Configure loopback on R-1",
            session_id="user_a",
            user_id="user_a"
        )

    async def user_b_config():
        await asyncio.sleep(0.2)  # Slight delay
        return await service.stream_chat(
            "Configure loopback on R-1",  # Same device!
            session_id="user_b",
            user_id="user_b"
        )

    results = await asyncio.gather(
        user_a_config(),
        user_b_config(),
        return_exceptions=True
    )

    # One should succeed, one should timeout
    assert any(isinstance(r, RuntimeError) for r in results)
```

---

## Rollout Plan

1. **Feature Flag**
   ```python
   # config.py
   ENABLE_DEVICE_LOCKS = os.getenv("GNS3_COPILOT_DEVICE_LOCKS", "true").lower() == "true"
   ```

2. **Gradual Enablement**
   - Week 1: Enable in development environment
   - Week 2: Enable in staging with monitoring
   - Week 3: Enable for 10% of production users
   - Week 4: Full rollout

3. **Monitoring**
   - Track lock acquisition rate
   - Monitor timeout frequency
   - Measure user wait times

---

## Open Questions

1. **Should read operations be concurrent?**
   - Pros: Better user experience for diagnostic tasks
   - Cons: More complex implementation, risk of read-during-write

2. **What about bulk operations?**
   - If user operates on 10 devices, should we acquire all locks first?
   - Risk: Deadlock if two users request overlapping device sets

3. **Lock priority?**
   - Should instructors/admins have priority over students?
   - How to signal this in the UI?

4. **Graceful degradation?**
   - If lock service fails, should we:
     - a) Block all operations (safe but disruptive)
     - b) Allow operations with warning (risky)

---

## References

- [Python asyncio.Lock documentation](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Lock)
- [Redlock algorithm (Redis distributed locks)](https://redis.io/topics/distlock)
- [Netmiko connection management](https://github.com/ktbyers/netmiko)

---

## Changelog

| Date | Change |
|------|--------|
| 2025-03-06 | Initial document creation |
