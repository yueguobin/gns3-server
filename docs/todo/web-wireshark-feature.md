# Web Wireshark Integration

## Overview

Integrate Wireshark packet capture functionality into GNS3 Web UI, allowing users to view real-time capture data directly in the browser via noVNC.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser                                  │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │  GNS3 Web UI                                             │  │
│   │  - "Start Capture" on a link                            │  │
│   │  - "View in Wireshark" opens noVNC iframe                │  │
│   │  - Receives "ready" event via WebSocket                 │  │
│   └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket (ws://gns3-server:3080)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       GNS3 Server (Port 3080)                     │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  WiresharkSessionManager                                  │   │
│  │  - DisplayManager: tracks allocated displays (:10-:109)  │   │
│  │  - Session state: pending → starting → ready → error     │   │
│  │  - AnsibleRunner: triggers playbooks asynchronously       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │ WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Wireshark Container (Persistent)                    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  xpra + noVNC Server (port 10000)                        │   │
│  │  - No local authentication (trust GNS3 Server gateway)   │   │
│  │  - Session dir: /tmp/sessions/link-{uuid}/              │   │
│  │    - token: JWT token for capture/stream API            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Linux User Isolation (one user per link_id)            │   │
│  │                                                           │   │
│  │  link-{uuid-1} ──▶ Xvfb :10 ──▶ wireshark              │   │
│  │  link-{uuid-2} ──▶ Xvfb :11 ──▶ wireshark              │   │
│  │  link-{uuid-3} ──▶ Xvfb :12 ──▶ wireshark              │   │
│  │                                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  cgroups Resource Limits (per user)                     │   │
│  │  - Memory: 2GB  |  Processes: 50  |  CPU Shares: 10%    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP (token via file, not CLI)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        GNS3 Server                               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Capture File Storage                                     │   │
│  │  /path/to/projects/{project_id}/captures/{link_id}.pcap  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│              GET /v3/links/{link_id}/capture/stream             │
│              (Authorization: Bearer {user_jwt})                  │
└─────────────────────────────────────────────────────────────────┘
```

## Design Principles

- **No independent wireshark API** - Reuse existing capture API endpoints
- **Ansible-driven session management** - Wireshark session creation/cleanup handled by Ansible playbooks
- **Browser only connects to GNS3 Server** - WebSocket proxy handles forwarding to Wireshark container
- **HTTP-based data delivery** - Wireshark fetches pcap stream via HTTP using token file (not CLI args)
- **State-driven session lifecycle** - Frontend receives real-time session state via WebSocket
- **Secure token handling** - JWT token stored in session file, not process arguments
- **Unified authentication** - GNS3 Server's JWT is the only auth mechanism; xpra trusts the proxy gateway

## Session Lifecycle

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           Session State Machine                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  [idle] ──▶ [pending] ──▶ [starting] ──▶ [ready] ──▶ [closing] ──▶ [idle]
│                │                │                │                │
│                │                │                │                │
│                ▼                ▼                ▼                ▼
│            User clicks     Ansible runs     User views      Stop capture
│            Start Capture   (5-10s)          Wireshark       or timeout
│                                                                          │
│  [idle] ──▶ [error]  (if Ansible fails)                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

State Persistence:
- Session state is ephemeral (lost on GNS3 Server restart)
- On restart, user must restart capture to recover
- Wireshark container sessions are independent
```

## Data Flow

### 1. Start Capture

```
User clicks "Start Capture" in GNS3 Web UI (with Wireshark enabled)
   │
   └─▶ POST /v3/links/{link_id}/capture/start
       Header: Authorization: Bearer {user_jwt}
       Body: { "wireshark": true }
       │
       ▼
   GNS3 Server:
   a. Starts packet capture (existing behavior)
   b. WiresharkSessionManager:
      - Allocates display :10 (via DisplayManager)
      - Creates session state: pending
      - Triggers Ansible playbook (async) to create wireshark session
       │
       ▼
   Response (immediate):
   {
     "link_id": "xxx",
     "capturing": true,
     "wireshark_ws": "ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark",
     "display": ":10"            // allocated display number
   }
       │
       ▼
2. Ansible executes in background (5-10 seconds):
   - Creates Linux user link-{uuid}
   - Creates session dir /tmp/sessions/link-{uuid}/
   - Writes JWT token to /tmp/sessions/link-{uuid}/token (mode 0600)
   - Starts xpra session WITHOUT local authentication
   - Starts wireshark consuming capture/stream API (token read from file)
   - Updates session state to: ready
```

### 2. Frontend WebSocket Connection

```
Frontend connects to WebSocket AFTER receiving API response:
   ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark
   Header: Authorization: Bearer {user_jwt}

   │
   ├─▶ GNS3 Server validates JWT token
   │
   ├─▶ Check session state:
   │      - [pending/starting]: send {"type": "waiting", "message": "Starting..."}
   │      - [ready]: send {"type": "ready", "display": ":10", "xpra_ws": "..."}
   │      - [error]: send {"type": "error", "message": "..."}
   │
   └─▶ If session is [ready]:
       - Proxy WebSocket to Wireshark Container xpra :10000
       - No xpra authentication required (GNS3 Server is trusted gateway)
       - noVNC iframe connects to xpra WebSocket via proxy
```

### 3. Stop Capture

```
User clicks "Stop Capture"
   │
   └─▶ POST /v3/links/{link_id}/capture/stop
       Body: { "wireshark": true }
       │
       ▼
   GNS3 Server:
   a. Stops packet capture (existing behavior)
   b. WiresharkSessionManager:
      - Triggers Ansible playbook (async) to cleanup session
      - Releases display back to DisplayManager
      - Sets session state: closing → idle
```

### 4. Abnormal Disconnect

```
User closes browser (noVNC WebSocket disconnects)
   │
   ▼
WebSocket handler detects disconnect (finally block)
   │
   ├─▶ If link.capturing == true:
   │      - Session stays alive (capture continues)
   │      - Display remains allocated
   │      - User can reconnect via new WebSocket connection
   │
   └─▶ If link.capturing == false:
          - Trigger cleanup immediately
          - Release display

Heartbeat mechanism:
   - WebSocket proxy sends ping every 10 seconds
   - If no pong within 30 seconds, treat as disconnected
   - On timeout: cleanup if not capturing, otherwise keep session
```

## DisplayManager

Manages X display allocation to avoid conflicts.

```python
# gns3server/compute/display_manager.py

import asyncio
import logging

log = logging.getLogger(__name__)


class DisplayManager:
    """
    Manages X display number allocation for Wireshark sessions.

    Displays are allocated from a configurable range (default: :10 to :109)
    and must be released when the session ends.
    """

    def __init__(self, start: int = 10, max_displays: int = 100):
        self._start = start
        self._max = start + max_displays
        self._allocated: dict[int, str] = {}  # display -> link_id
        self._lock = asyncio.Lock()

    async def allocate(self, link_id: str) -> str:
        """
        Allocate a display number for a link.

        :param link_id: The link ID requesting a display
        :returns: Display string (e.g., ":10")
        :raises RuntimeError: If no displays available
        """
        async with self._lock:
            # Find first available display
            for display in range(self._start, self._max):
                if display not in self._allocated:
                    self._allocated[display] = link_id
                    display_str = f":{display}"
                    log.info(f"Allocated display {display_str} for link {link_id}")
                    return display_str

            raise RuntimeError(f"No available displays in range :{self._start}-:{self._max - 1}")

    async def release(self, display: str) -> None:
        """
        Release a display number.

        :param display: Display string (e.g., ":10")
        """
        if not display or len(display) < 2:
            return

        display_num = int(display[1:])
        async with self._lock:
            if display_num in self._allocated:
                link_id = self._allocated.pop(display_num)
                log.info(f"Released display {display} from link {link_id}")

    async def get_display_link_id(self, display: str) -> str | None:
        """
        Get the link ID using a specific display.

        :param display: Display string (e.g., ":10")
        :returns: Link ID or None if not found
        """
        if not display or len(display) < 2:
            return None
        display_num = int(display[1:])
        async with self._lock:
            return self._allocated.get(display_num)

    def get_allocated_count(self) -> int:
        """Return the number of currently allocated displays."""
        return len(self._allocated)
```

## WiresharkSessionManager

Manages Wireshark session lifecycle on the GNS3 Server side.

```python
# gns3server/compute/wireshark_session_manager.py

import asyncio
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)


class SessionState(Enum):
    IDLE = "idle"
    PENDING = "pending"
    STARTING = "starting"
    READY = "ready"
    CLOSING = "closing"
    ERROR = "error"


@dataclass
class WiresharkSession:
    """Represents a Wireshark viewing session for a link."""

    link_id: str
    display: str
    state: SessionState = SessionState.PENDING
    error_message: str = ""
    ansible_task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=asyncio.get_event_loop().time)


class WiresharkSessionManager:
    """
    Manages Wireshark sessions for packet capture links.

    Responsibilities:
    - Allocate displays via DisplayManager
    - Trigger Ansible playbooks for session create/cleanup
    - Track session state
    - Provide WebSocket handler with session info
    """

    def __init__(self, container_host: str = "wireshark-container"):
        self._sessions: dict[str, WiresharkSession] = {}
        self._display_manager = DisplayManager(start=10, max_displays=100)
        self._container_host = container_host
        self._lock = asyncio.Lock()
        self._ansible_inventory = "/etc/ansible/hosts"
        self._ansible_playbooks_dir = "/etc/ansible/playbooks"

    async def create_session(self, link_id: str, user_token: str) -> WiresharkSession:
        """
        Create a new Wireshark session.

        :param link_id: The link ID to create session for
        :param user_token: JWT token for capture/stream access
        :returns: WiresharkSession object
        """
        async with self._lock:
            # Check if session already exists
            if link_id in self._sessions:
                session = self._sessions[link_id]
                if session.state in (SessionState.PENDING, SessionState.STARTING):
                    # Already creating, return existing
                    return session
                elif session.state == SessionState.READY:
                    # Already ready, return existing
                    return session

            # Allocate display
            display = await self._display_manager.allocate(link_id)

            # Create session
            session = WiresharkSession(
                link_id=link_id,
                display=display,
                state=SessionState.PENDING,
            )
            self._sessions[link_id] = session

            # Start Ansible playbook asynchronously
            session.ansible_task = asyncio.create_task(
                self._run_create_playbook(link_id, user_token, display)
            )

            # Also trigger status polling to update state
            asyncio.create_task(self._poll_session_ready(link_id))

            return session

    async def _run_create_playbook(
        self, link_id: str, user_token: str, display: str
    ) -> None:
        """Run Ansible playbook to create Wireshark session (async)."""
        try:
            session = self._sessions.get(link_id)
            if not session:
                return

            session.state = SessionState.STARTING

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "ansible-playbook",
                        f"{self._ansible_playbooks_dir}/wireshark_create.yml",
                        "-e", json.dumps({
                            "link_id": link_id,
                            "user_token": user_token,
                            "display": display,
                        }),
                        "-i", self._ansible_inventory,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                ),
            )

            if result.returncode != 0:
                log.error(f"Ansible create failed: {result.stderr}")
                if link_id in self._sessions:
                    self._sessions[link_id].state = SessionState.ERROR
                    self._sessions[link_id].error_message = f"Create failed: {result.stderr}"
            else:
                log.info(f"Wireshark session created for link {link_id}")

        except asyncio.TimeoutError:
            log.error(f"Ansible playbook timed out for link {link_id}")
            if link_id in self._sessions:
                self._sessions[link_id].state = SessionState.ERROR
                self._sessions[link_id].error_message = "Create timed out"
        except Exception as e:
            log.error(f"Error running Ansible playbook: {e}")
            if link_id in self._sessions:
                self._sessions[link_id].state = SessionState.ERROR
                self._sessions[link_id].error_message = str(e)

    async def _poll_session_ready(self, link_id: str, timeout: float = 30) -> None:
        """Poll for session ready state."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if link_id not in self._sessions:
                return

            session = self._sessions[link_id]
            if session.state == SessionState.READY or session.state == SessionState.ERROR:
                return

            # Check if Ansible task is done (for STARTING state)
            if session.state == SessionState.STARTING and session.ansible_task:
                if session.ansible_task.done():
                    # Ansible finished but didn't set ready (likely failed)
                    if session.state != SessionState.ERROR:
                        # Check if xpra is actually running
                        if await self._check_xpra_running(link_id, session.display):
                            session.state = SessionState.READY
                        else:
                            session.state = SessionState.ERROR
                            session.error_message = "Session creation failed"
                    return

            await asyncio.sleep(0.5)

        # Timeout
        if link_id in self._sessions:
            self._sessions[link_id].state = SessionState.ERROR
            self._sessions[link_id].error_message = "Session creation timed out"

    async def _check_xpra_running(self, link_id: str, display: str) -> bool:
        """Check if xpra session is running via Ansible status playbook."""
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "ansible-playbook",
                        f"{self._ansible_playbooks_dir}/wireshark_status.yml",
                        "-e", json.dumps({"link_id": link_id, "display": display}),
                        "-i", self._ansible_inventory,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )
            if result.returncode == 0:
                # Parse output to check status
                return "status: running" in result.stdout
        except Exception:
            pass
        return False

    async def close_session(self, link_id: str) -> None:
        """Close a Wireshark session."""
        async with self._lock:
            if link_id not in self._sessions:
                return

            session = self._sessions[link_id]
            session.state = SessionState.CLOSING

        # Run cleanup playbook
        asyncio.create_task(
            self._run_cleanup_playbook(link_id, session.display)
        )

    async def _run_cleanup_playbook(self, link_id: str, display: str) -> None:
        """Run Ansible playbook to cleanup Wireshark session (async)."""
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "ansible-playbook",
                        f"{self._ansible_playbooks_dir}/wireshark_cleanup.yml",
                        "-e", json.dumps({"link_id": link_id, "display": display}),
                        "-i", self._ansible_inventory,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                ),
            )

            if result.returncode != 0:
                log.warning(f"Ansible cleanup failed for {link_id}: {result.stderr}")

        except Exception as e:
            log.error(f"Error running cleanup playbook: {e}")
        finally:
            # Release display
            await self._display_manager.release(display)

            # Remove session
            async with self._lock:
                if link_id in self._sessions:
                    del self._sessions[link_id]

    async def get_session(self, link_id: str) -> Optional[WiresharkSession]:
        """Get session by link ID."""
        return self._sessions.get(link_id)

    async def get_session_state(self, link_id: str) -> SessionState:
        """Get session state for a link."""
        session = self._sessions.get(link_id)
        return session.state if session else SessionState.IDLE

    def get_xpra_ws_url(self, session: WiresharkSession) -> str:
        """Get the xpra WebSocket URL for a session."""
        return f"ws://{self._container_host}:10000"
```

## WebSocket Handler

Handles browser WebSocket connections with state-based messaging.

```python
# gns3server/api/routes/controller/links.py (additions)

import asyncio
import json
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from uuid import UUID

# Wireshark session manager instance
wireshark_session_manager = WiresharkSessionManager()


@router.websocket("/v3/links/{link_id}/capture/wireshark")
async def wireshark_websocket(websocket: WebSocket, link_id: UUID):
    """
    WebSocket endpoint for Wireshark viewing.

    Protocol:
    1. Client connects with JWT token in header
    2. Server validates token and link ownership
    3. Server sends state message:
       - {"type": "waiting", "message": "Starting Wireshark..."}
       - {"type": "ready", "display": ":10", "xpra_ws": "ws://..."}
       - {"type": "error", "message": "..."}
    4. Once ready, bidirectional proxy to xpra WebSocket
    5. Heartbeat: ping every 10s, disconnect if no pong in 30s
    """
    # 1. Validate JWT token
    token = websocket.headers.get("Authorization", "").replace("Bearer ", "")
    if not await validate_jwt_token(token, str(link_id)):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # 2. Get session
    session = await wireshark_session_manager.get_session(str(link_id))
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    # 3. Send current state
    if session.state == SessionState.PENDING or session.state == SessionState.STARTING:
        await websocket.send_json({
            "type": "waiting",
            "message": "Starting Wireshark, please wait..."
        })
    elif session.state == SessionState.ERROR:
        await websocket.send_json({
            "type": "error",
            "message": session.error_message
        })
        await websocket.close(code=4002, reason=session.error_message)
        return

    # 4. Wait for ready (if not already)
    if session.state != SessionState.READY:
        # Wait up to 15 seconds
        for _ in range(30):  # 30 * 0.5s = 15s
            await asyncio.sleep(0.5)
            session = await wireshark_session_manager.get_session(str(link_id))
            if not session:
                await websocket.close(code=4004, reason="Session not found")
                return
            if session.state == SessionState.READY:
                break
            elif session.state == SessionState.ERROR:
                await websocket.send_json({
                    "type": "error",
                    "message": session.error_message
                })
                await websocket.close(code=4002, reason=session.error_message)
                return
        else:
            await websocket.close(code=4003, reason="Session ready timeout")
            return

    # 5. Send ready message
    await websocket.send_json({
        "type": "ready",
        "display": session.display,
        "xpra_ws": wireshark_session_manager.get_xpra_ws_url(session)
    })

    # 6. Start heartbeat
    heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

    # 7. Proxy to xpra
    try:
        xpra_ws_url = wireshark_session_manager.get_xpra_ws_url(session)
        async with websockets.connect(xpra_ws_url) as xpra_ws:
            # Bidirectional proxy with cancellation support
            proxy_task = asyncio.create_task(_proxy_loop(websocket, xpra_ws))

            # Wait for either to finish
            done, pending = await asyncio.wait(
                [proxy_task, heartbeat_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except websockets.WebSocketException as e:
        log.error(f"xpra WebSocket error: {e}")
    finally:
        # Check if link is still capturing
        link = await get_link_by_id(str(link_id))
        if link and not link.capturing:
            # Stop capture, cleanup session
            await wireshark_session_manager.close_session(str(link_id))
        # If still capturing, session stays alive for reconnection


async def _heartbeat_loop(websocket: WebSocket, interval: float = 10, timeout: float = 30):
    """Send pings and disconnect if no pong."""
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await websocket.ping()
                # Wait for pong
                await asyncio.wait_for(websocket.wait_for_pong(), timeout=timeout)
            except asyncio.TimeoutError:
                log.warning("WebSocket heartbeat timeout")
                break
            except Exception:
                break
    except asyncio.CancelledError:
        pass


async def _proxy_loop(browser_ws: WebSocket, xpra_ws, buffer_size: int = 8192):
    """Bidirectional proxy between browser and xpra."""
    async def forward_from_browser():
        try:
            while True:
                data = await browser_ws.receive_bytes()
                await xpra_ws.send(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def forward_to_browser():
        try:
            while True:
                data = await xpra_ws.recv()
                if isinstance(data, str):
                    await browser_ws.send_text(data)
                else:
                    await browser_ws.send_bytes(data)
        except websockets.WebSocketException:
            pass
        except Exception:
            pass

    await asyncio.gather(
        forward_from_browser(),
        forward_to_browser(),
    )
```

## Capture Stream Consumption

Wireshark fetches pcap data from GNS3 Server's stream API using token from file (not CLI).

```bash
# Inside Wireshark container, executed as link-{uuid} user
# Token is read from file, not passed as command line argument

su - link-${LINK_ID} -c 'DISPLAY=${DISPLAY} wireshark \
  -i <(curl -N -H "Authorization: Bearer $(cat /tmp/sessions/link-${LINK_ID}/token)" \
    http://gns3-server:3080/v3/links/${LINK_ID}/capture/stream) &'
```

**Security improvement over original design:**

| Aspect | Original (Insecure) | Updated (Secure) |
|--------|---------------------|------------------|
| Token location | CLI argument | Session file `/tmp/sessions/link-{uuid}/token` |
| Token visibility | `ps aux` shows token | Token only readable by user process |
| Shell history | Token in history | No token in history |
| Cleanup | May leave traces | File deleted on session cleanup |

## API (Extended Existing Capture API)

### Start Capture with Wireshark

```http
POST /v3/links/{link_id}/capture/start

Request:
{
  "wireshark": true   // Optional, enable wireshark view
}

Response (Link object + new fields):
{
  "link_id": "xxx",
  "capturing": true,
  "wireshark_ws": "ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark",
  "display": ":10"
}
```

### Stop Capture

```http
POST /v3/links/{link_id}/capture/stop

Request:
{
  "wireshark": true   // Optional, cleanup wireshark session
}

Response: 204 No Content
```

### Wireshark WebSocket Protocol

```http
ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark
Authorization: Bearer {jwt_token}
```

**Server-to-Client Messages:**

```json
// Waiting for session ready
{"type": "waiting", "message": "Starting Wireshark, please wait..."}

// Session is ready
{"type": "ready", "display": ":10", "xpra_ws": "ws://wireshark-container:10000"}

// Session creation failed
{"type": "error", "message": "Failed to start Wireshark: Ansible error"}
```

**Client Usage (JavaScript):**

```javascript
const ws = new WebSocket(
  `ws://gns3-server:3080/v3/links/${linkId}/capture/wireshark`,
  [],
  { headers: { Authorization: `Bearer ${jwtToken}` } }
);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === 'waiting') {
    showWaitingUI(msg.message);
  } else if (msg.type === 'ready') {
    // Connect noVNC to xpra via GNS3 Server proxy (no password needed)
    connectNoVNC(msg.xpra_ws);
  } else if (msg.type === 'error') {
    showErrorUI(msg.message);
    ws.close();
  }
};

function connectNoVNC(xpraWsUrl) {
  // xpra HTML client connects via GNS3 Server WebSocket proxy
  // GNS3 Server has already authenticated the user via JWT
  const rfb = new RFB(document.getElementById('vnc-canvas'), xpraWsUrl);
}
```

## Ansible Playbooks

### Playbook 1: Create Wireshark Session

**File:** `wireshark_create.yml`

**Variables passed to Ansible:**

| Variable | Description |
|----------|-------------|
| `link_id` | Link UUID |
| `user_token` | User's JWT token for capture/stream access |
| `display` | Assigned X display number (e.g., :10) |

```yaml
---
- name: Create Wireshark Session
  hosts: wireshark_container
  gather_facts: no
  vars:
    gns3_server: "{{ gns3_server_url | default('http://gns3-server:3080') }}"
    session_dir: "/tmp/sessions/link-{{ link_id }}"
  tasks:
    - name: Create session directory
      file:
        path: "{{ session_dir }}"
        state: directory
        mode: '0700'

    - name: Write JWT token to file (secure, not CLI)
      copy:
        dest: "{{ session_dir }}/token"
        content: "{{ user_token }}"
        mode: '0600'

    - name: Create Linux user for link
      user:
        name: "link-{{ link_id }}"
        shell: /usr/sbin/nologin
        create_home: no
        state: present

    - name: Create cgroup for resource limits
      shell: |
        mkdir -p /sys/fs/cgroup/memory/link-{{ link_id }}
        mkdir -p /sys/fs/cgroup/pids/link-{{ link_id }}
        echo 2147483648 > /sys/fs/cgroup/memory/link-{{ link_id }}/memory.limit_in_bytes
        echo 50 > /sys/fs/cgroup/pids/link-{{ link_id }}/pids.max

    - name: Start xpra session (no local auth - GNS3 Server is trusted gateway)
      shell: |
        su - link-{{ link_id }} -c "DISPLAY={{ display }} xpra start {{ display }}
          --html=on
          --bind-tcp=0.0.0.0:10000
          --auth=allow
          --socket-permissions=0700
          --dpi=96"

    - name: Wait for xpra to be ready
      wait_for:
        port: 10000
        timeout: 10

    - name: Start wireshark (token read from file, not CLI)
      shell: |
        su - link-{{ link_id }} -c "DISPLAY={{ display }} bash -c '
          TOKEN_FILE=/tmp/sessions/link-{{ link_id }}/token
          while [ ! -f \$TOKEN_FILE ]; do sleep 0.5; done
          wireshark -i <(curl -N -H \"Authorization: Bearer \$(cat \$TOKEN_FILE)\" \
            {{ gns3_server }}/v3/links/{{ link_id }}/capture/stream) &
        '"
```

### Playbook 2: Cleanup Wireshark Session

**File:** `wireshark_cleanup.yml`

```yaml
---
- name: Cleanup Wireshark Session
  hosts: wireshark_container
  gather_facts: no
  vars:
    session_dir: "/tmp/sessions/link-{{ link_id }}"
  tasks:
    - name: Stop wireshark process
      shell: pkill -9 -u "link-{{ link_id }}" wireshark || true

    - name: Stop xpra session
      shell: |
        su - link-{{ link_id }} -c "DISPLAY={{ display }} xpra stop {{ display }}" || true

    - name: Cleanup cgroups
      shell: |
        rmdir /sys/fs/cgroup/memory/link-{{ link_id }} 2>/dev/null || true
        rmdir /sys/fs/cgroup/pids/link-{{ link_id }} 2>/dev/null || true

    - name: Remove Linux user
      user:
        name: "link-{{ link_id }}"
        state: absent

    - name: Remove session directory (includes token file)
      file:
        path: "{{ session_dir }}"
        state: absent
```

### Playbook 3: Check Session Status

**File:** `wireshark_status.yml`

```yaml
---
- name: Check Wireshark Session Status
  hosts: wireshark_container
  gather_facts: no
  vars:
    session_dir: "/tmp/sessions/link-{{ link_id }}"
  tasks:
    - name: Check if user exists
      shell: id "link-{{ link_id }}" 2>/dev/null && echo "exists" || echo "not_found"
      register: user_check

    - name: Check if xpra session is running
      shell: ps aux | grep -v grep | grep "xpra.*{{ display }}" | grep "link-{{ link_id }}" || true
      register: xpra_check

    - name: Check if wireshark is running
      shell: ps aux | grep -v grep | grep "wireshark" | grep "link-{{ link_id }}" || true
      register: wireshark_check

    - name: Check if session directory exists
      stat:
        path: "{{ session_dir }}"
      register: session_dir_check

    - name: Set session status
      set_fact:
        session_status:
          link_id: "{{ link_id }}"
          display: "{{ display }}"
          user_exists: "{{ 'exists' in user_check.stdout }}"
          xpra_running: "{{ xpra_check.stdout != '' }}"
          wireshark_running: "{{ wireshark_check.stdout != '' }}"
          session_dir_exists: "{{ session_dir_check.stat.exists }}"
          status: "{{ 'running' if (user_check.stdout.find('exists') != -1 and wireshark_check.stdout != '') else 'stopped' }}"
```

### Inventory Example

```ini
[wireshark_container]
wireshark-01 ansible_host=192.168.1.100 ansible_user=root

[wireshark_container:vars]
gns3_server_url=http://192.168.1.50:3080
```

### Execution Examples

```bash
# Create session
ansible-playbook wireshark_create.yml \
  -e "link_id=76ead2b0-fd00-407c-b5db-abc83445886e" \
  -e "user_token=eyJhbGc..." \
  -e "display=:10"

# Cleanup session
ansible-playbook wireshark_cleanup.yml \
  -e "link_id=76ead2b0-fd00-407c-b5db-abc83445886e" \
  -e "display=:10"

# Check status
ansible-playbook wireshark_status.yml \
  -e "link_id=76ead2b0-fd00-407c-b5db-abc83445886e" \
  -e "display=:10"
```

## Component Responsibilities

| Component | Role |
|-----------|------|
| GNS3 Server | Capture data provider, WebSocket proxy, session manager |
| DisplayManager | Tracks and allocates X display numbers (:10-:109) |
| WiresharkSessionManager | Orchestrates session lifecycle, Ansible triggering |
| `capture/stream` API | Streams pcap data via HTTP to authorized consumers |
| WebSocket Proxy | Forwards browser connection to Wireshark container |
| Ansible | Handles wireshark session create/cleanup on container |
| Wireshark Container | Hosts multiple Wireshark instances via xpra |
| xpra | Manages multiple X sessions, provides WebSocket/VNC with password auth |
| noVNC | Bridges xpra X session to browser (via proxy) |
| Linux User (per link_id) | Isolates processes, files, resources per session |
| cgroups | Enforces resource limits per user |
| Session Files | Stores JWT token and xpra password securely (not in CLI) |

## Security

| Concern | Mitigation |
|---------|------------|
| JWT token in CLI | Token stored in session file, mode 0600, read by Wireshark process |
| Token in shell history | Token written to file instead of using shell history |
| Token visible in `ps aux` | Token file only readable by `link-{uuid}` user |
| Browser directly accessing container | All access via GNS3 Server WebSocket proxy |
| Unauthorized WebSocket connection | JWT validation + link ownership check |
| Resource abuse by Wireshark | cgroups limit memory (2GB) and processes (50) per user |
| xpra unauthorized access | `--auth=allow` trusts connections from GNS3 Server (network isolated) |
| Token expiration | Token passed at session create time; Wireshark uses it until session ends |

### Trust Model

```
┌─────────────────────────────────────────────────────────────────┐
│                        Trust Boundary                           │
│                                                                  │
│  ┌─────────────┐     JWT validated      ┌──────────────────┐  │
│  │   Browser   │ ──────────────────────► │   GNS3 Server    │  │
│  │             │      at this point      │  (WebSocket)     │  │
│  └─────────────┘                         └────────┬─────────┘  │
│                                                     │            │
│  Browser has NO direct access to container.        │ GNS3 Server│
│  All traffic flows through GNS3 Server proxy.      │ is trusted │
│                                                     │            │
│                                                     ▼            │
│                                          ┌──────────────────┐   │
│                                          │   Container      │   │
│                                          │  (xpra + Xvfb)  │   │
│                                          └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

xpra uses --auth=allow, meaning:
- GNS3 Server is the only entity that can reach xpra port
- GNS3 Server has already authenticated the user via JWT
- Container network should be firewalled to only allow GNS3 Server
```

## Session Lifecycle Detail

| Event | Action | State Transition |
|-------|--------|------------------|
| Start capture with wireshark | Allocate display, trigger Ansible create | idle → pending |
| Ansible starts running | xpra and wireshark processes starting | pending → starting |
| Ansible completes successfully | Session ready for viewing | starting → ready |
| Ansible fails | Session error | starting → error |
| User connects noVNC | WebSocket proxy to xpra | (no state change) |
| User disconnects noVNC | Session keeps running if still capturing | (no state change) |
| User clicks Stop Capture | Trigger Ansible cleanup | any → closing |
| Cleanup completes | Release display, remove session | closing → idle |
| GNS3 Server restarts | Sessions lost, user must restart | any → (lost) |
| Container restart | Sessions lost on container | any → (lost) |

## Capture Storage

- GNS3 Server saves capture to persistent storage (existing behavior)
- Wireshark consumes real-time stream from `capture/stream` API
- Users can download full capture file anytime via existing download API
- Wireshark container does NOT persist capture data (stateless viewer)

## Wireshark Container

### Dockerfile

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    wireshark \
    xpra \
    xvfb \
    curl \
    openssh-server \
    python3 \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# SSH configuration for Ansible access
RUN mkdir /var/run/sshd

# Create sessions directory
RUN mkdir -p /tmp/sessions && chmod 1777 /tmp/sessions

# Expose ports
EXPOSE 10000 22

CMD service ssh start && \
    /usr/bin/xpra start --html=on --bind-tcp=0.0.0.0:10000 --daemonize
```

### Container Components

| Component | Purpose |
|-----------|---------|
| wireshark | GUI rendering of pcap stream from GNS3 Server |
| xpra | Multi-user X session management, WebSocket support, password auth |
| xvfb | Virtual framebuffer for headless X |
| curl | HTTP client to fetch pcap stream |
| openssh-server | Ansible remote execution |

### Running the Container

```bash
docker run -d \
  --name wireshark-server \
  --privileged \
  --memory=8g \
  -p 10000:10000 \
  -p 2222:22 \
  wireshark-server
```

> **Note:** `--privileged` is required for cgroups and user creation.

### Container Internal Structure

```
/
├── tmp/
│   └── sessions/
│       └── link-{uuid}/
│           └── token          # JWT token for capture/stream API (0600)
├── sys/fs/cgroup/             # cgroups mounts
└── usr/bin/
    ├── wireshark
    ├── xpra
    └── xvfb-run
```

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| DisplayManager | TODO | Simple counter-based allocator |
| WiresharkSessionManager | TODO | Session state machine + Ansible runner |
| WebSocket Handler | TODO | FastAPI WebSocket with state protocol |
| Ansible Playbooks | DONE | Create, cleanup, status playbooks |
| Dockerfile | DONE | Container image definition |
| Link API modifications | TODO | Add wireshark=true to start/stop |
| Frontend integration | TODO | Connect to WebSocket, show noVNC |

## Troubleshooting

| Issue | Diagnosis | Solution |
|-------|-----------|----------|
| WebSocket closes with 4001 | JWT token invalid | Refresh token, check link ownership |
| WebSocket closes with 4004 | Session not found | Start capture with wireshark first |
| Message type is "waiting" forever | Ansible not completing | Check Ansible logs on container |
| Message type is "error" | Session creation failed | Check error message, verify container reachable |
| noVNC connects but shows black screen | Wireshark not started | Check wireshark process via status playbook |
| xpra connection refused | Wrong port or password | Verify xpra is running, password matches |
| Capture not showing in Wireshark | Token expired or API issue | Token validity tied to session lifetime |

## Future Enhancements

1. **AWX/Tower Integration** - Replace subprocess calls with AWX API for better orchestration
2. **Session Recovery** - Persist session state to survive GNS3 Server restarts
3. **Multiple Viewers** - Allow multiple browsers to view same Wireshark session (read-only mode)
4. **Session Recording** - Save Wireshark interaction for playback
