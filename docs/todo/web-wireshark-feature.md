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
│   └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket (ws://gns3-server:3080)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       GNS3 Server (Port 3080)                     │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  WebSocket Proxy                                          │   │
│  │  ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark │
│  └──────────────────────────────────────────────────────────┘   │
│                              │ WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Wireshark Container (Persistent)                    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  xpra + noVNC Server (port 10000)                        │   │
│  │  Multi-user X session management                         │   │
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
│  │  cgroups Resource Limits (per user)                      │   │
│  │  - Memory: 2GB  |  Processes: 50  |  CPU Shares: 10%     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP + JWT
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
- **HTTP-based data delivery** - Wireshark fetches pcap stream via HTTP using user's JWT token

## Data Flow

```
1. User clicks "Start Capture" in GNS3 Web UI (with Wireshark enabled)
   │
   └─▶ POST /v3/links/{link_id}/capture/start
       Header: Authorization: Bearer {user_jwt}
       Body: { "wireshark": true }
       │
       ▼
   GNS3 Server:
   a. Starts packet capture (existing behavior)
   b. Triggers Ansible playbook to create wireshark session:
      - Create Linux user link-{uuid}
      - Start xpra session :{display}
      - Start wireshark consuming capture/stream API with user_token
       │
       ▼
   Response (immediate):
   {
     "link_id": "xxx",
     "capturing": true,
     "wireshark_ws": "ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark",
     "display": ":10"
   }
       │
       ▼
2. Ansible executes in background (5-10 seconds)
   - Creates user, starts xpra, launches wireshark
   - Wireshark connects to capture/stream API using user's JWT token

3. Frontend receives response, waits for ready, then connects:
   ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark
   │
   └─▶ GNS3 Server WebSocket proxy ──▶ Wireshark Container xpra :10000

4. User clicks "Stop Capture"
   │
   └─▶ POST /v3/links/{link_id}/capture/stop
       Body: { "wireshark": true }
       │
       ▼
   GNS3 Server:
   a. Stops packet capture (existing behavior)
   b. Triggers Ansible playbook to cleanup wireshark session:
      - Kill wireshark process
      - Stop xpra session
      - Remove Linux user link-{uuid}
```

## Capture Stream Consumption

Wireshark fetches pcap data directly from GNS3 Server's stream API using the user's JWT token:

```bash
# Inside Wireshark container, executed as link-{uuid} user
su - link-{uuid} -c "wireshark -i <(curl -N \
  -H 'Authorization: Bearer {user_token}' \
  http://gns3-server:3080/v3/links/{link_id}/capture/stream)"
```

**How it works:**

```
curl -N ................................► capture/stream API
    │                                     │
    │   (real-time streaming pcap data)   │
    │◄────────────────────────────────────┘
    │
    ▼
wireshark -i /dev/fd/xx   ◄─── process substitution <(...) as input
    │
    ▼
Wireshark GUI renders packets
```

| Component | Description |
|-----------|-------------|
| `curl -N` | `--no-buffer` for real-time streaming |
| `<(...)` | Process substitution, creates FIFO fd for wireshark `-i` |
| `Authorization` | User JWT token passed to Ansible for wireshark access |
| `capture/stream` API | Must return streaming response |

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
  "link_id": "string",
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

### Wireshark WebSocket

```http
ws://gns3-server:3080/v3/links/{link_id}/capture/wireshark

- Server validates JWT token
- Server proxies WebSocket to Wireshark container xpra :10000
```

### WebSocket Proxy Implementation

GNS3 Server acts as a proxy, forwarding browser WebSocket to Wireshark container:

```
Browser                              GNS3 Server                        Wireshark Container
   │                                    │                                    │
   │ ws://.../v3/links/{id}/wireshark  │                                    │
   │───────────────────────────────────▶│                                    │
   │                                    │                                    │
   │         JWT validated              │                                    │
   │         Session found              │                                    │
   │                                    │ ws://container:10000               │
   │                                    │───────────────────────────────────▶│
   │                                    │                                    │
   │◀════════════ Proxy Forward ════════│◀═════════════════════════════════│
```

**Proxy Logic:**

```python
class WiresharkWebSocketProxy:

    _sessions = {}  # {link_id: {"display": ":10", "container_url": "ws://container:10000"}}

    async def handle_websocket(self, link_id, websocket):
        # 1. Validate JWT token
        token = websocket.headers.get("Authorization", "").replace("Bearer ", "")
        if not self._validate_token(token, link_id):
            await websocket.close(4001, "Unauthorized")
            return

        # 2. Get session info
        session = self._get_session(link_id)
        if not session:
            await websocket.close(4004, "Session not found")
            return

        # 3. Connect to Wireshark container
        container_url = f"ws://{CONTAINER_HOST}:10000"
        async with websockets.connect(container_url) as container_ws:
            # 4. Bidirectional proxy
            await asyncio.gather(
                self._forward(websocket, container_ws),
                self._forward(container_ws, websocket)
            )

    def _validate_token(self, token, link_id):
        # JWT validation + link_id ownership check
        pass
```

**FastAPI Route Registration:**

```python
@router.websocket("/v3/links/{link_id}/capture/wireshark")
async def wireshark_ws(websocket, link_id: str):
    await proxy.handle_websocket(link_id, websocket)
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
    gns3_server: "http://gns3-server:3080"
  tasks:
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

    - name: Start xpra session
      shell: >
        su - link-{{ link_id }} -c "DISPLAY={{ display }} xpra start {{ display }}
          --html=on --bind-tcp=0.0.0.0:10000 --dpi=96"

    - name: Wait for xpra to be ready
      wait_for:
        port: 10000
        timeout: 10

    - name: Start wireshark (consuming capture stream with user JWT)
      shell: >
        su - link-{{ link_id }} -c "DISPLAY={{ display }} wireshark
          -i <(curl -N -H 'Authorization: Bearer {{ user_token }}'
            {{ gns3_server }}/v3/links/{{ link_id }}/capture/stream) &"
```

### Playbook 2: Cleanup Wireshark Session

**File:** `wireshark_cleanup.yml`

```yaml
---
- name: Cleanup Wireshark Session
  hosts: wireshark_container
  gather_facts: no
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
```

### Playbook 3: Check Session Status

**File:** `wireshark_status.yml`

```yaml
---
- name: Check Wireshark Session Status
  hosts: wireshark_container
  gather_facts: no
  tasks:
    - name: Check if user exists
      shell: id "link-{{ link_id }}" 2>/dev/null && echo "exists" || echo "not_found"
      register: user_check

    - name: Check if wireshark is running
      shell: ps aux | grep -v grep | grep "wireshark" | grep "link-{{ link_id }}" || true
      register: wireshark_check

    - name: Set session status
      set_fact:
        session_status:
          link_id: "{{ link_id }}"
          display: "{{ display }}"
          user_exists: "{{ 'exists' in user_check.stdout }}"
          wireshark_running: "{{ wireshark_check.stdout != '' }}"
          status: "{{ 'running' if (user_check.stdout.find('exists') != -1 and wireshark_check.stdout != '') else 'stopped' }}"
```

### Inventory Example

```ini
[wireshark_container]
wireshark-01 ansible_host=192.168.1.100 ansible_user=root

[wireshark_container:vars]
gns3_server=http://192.168.1.50:3080
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

## Session Lifecycle

| Event | Action |
|-------|--------|
| Start capture with wireshark | Ansible creates user, starts xpra + wireshark |
| Ansible completes (5-10s later) | Wireshark ready, frontend can connect WebSocket |
| User connects noVNC | WebSocket proxy forwards to container xpra |
| User disconnects noVNC | Session keeps running, capture continues |
| Stop capture | Ansible kills wireshark, stops xpra, removes user |
| Container restart | Sessions lost, user must restart capture |

## Component Responsibilities

| Component | Role |
|-----------|------|
| GNS3 Server | Capture data provider, WebSocket proxy |
| `capture/stream` API | Streams pcap data via HTTP to authorized consumers |
| WebSocket Proxy | Forwards browser connection to Wireshark container |
| Ansible | Handles wireshark session create/cleanup on container |
| Wireshark Container | Hosts multiple Wireshark instances via xpra |
| xpra | Manages multiple X sessions, provides WebSocket/VNC |
| noVNC | Bridges xpra X session to browser (via proxy) |
| Linux User (per link_id) | Isolates processes, files, resources per session |
| cgroups | Enforces resource limits per user |

## Security

- User JWT token is passed to Ansible for wireshark to access `capture/stream`
- Each link_id has isolated Linux user with `nologin` shell
- Browser only connects to GNS3 Server WebSocket, never directly to container
- cgroups prevent resource abuse
- xpra uses session-based authentication

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

# Expose ports
EXPOSE 10000 22

CMD service ssh start && \
    /usr/bin/xpra start --html=on --bind-tcp=0.0.0.0:10000 --daemonize
```

### Container Components

| Component | Purpose |
|-----------|---------|
| wireshark | GUI rendering of pcap stream from GNS3 Server |
| xpra | Multi-user X session management, WebSocket support |
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
├── home/
│   └── link-{uuid}/          # Per-session home dirs (created by Ansible)
├── sys/fs/cgroup/             # cgroups mounts
└── usr/bin/
    ├── wireshark
    ├── xpra
    └── xvfb-run
```
