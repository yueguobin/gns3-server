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
                              │ HTTPS / WebSocket
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
                              │ HTTPS + JWT
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
- **HTTP-based data delivery** - Wireshark fetches pcap stream via HTTP, no shared filesystem required

## Data Flow

```
1. User clicks "Start Capture" in GNS3 Web UI (with Wireshark enabled)
   │
   └─▶ POST /v3/links/{link_id}/capture
       Header: Authorization: Bearer {user_jwt}
       Body: { "wireshark": true }
       │
       ▼
   GNS3 Server:
   a. Starts packet capture (existing behavior)
   b. Triggers Ansible playbook to create wireshark session:
      - Create Linux user link-{uuid}
      - Start xpra session :{display}
      - Start wireshark consuming capture/stream API
       │
       ▼
   Response:
   {
     "link_id": "xxx",
     "wireshark_url": "http://wireshark-container:10000/#session=xxx",
     "display": ":10"
   }
       │
       ▼
2. Frontend opens noVNC iframe with Wireshark GUI

3. User clicks "Stop Capture" in GNS3 Web UI
   │
   └─▶ DELETE /v3/links/{link_id}/capture
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

Wireshark fetches pcap data directly from GNS3 Server's stream API:

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
| `Authorization` | User JWT token for authentication |
| `capture/stream` API | Must return streaming response |

## API (Extended Existing Capture API)

### Start Capture with Wireshark

```http
POST /v3/links/{link_id}/capture

Request:
{
  "wireshark": true   // Optional, enable wireshark view
}

Response (existing fields + new):
{
  "link_id": "string",
  "capturing": true,
  "wireshark_url": "http://wireshark-container:10000/#session=xxx",  // NEW
  "display": ":10"                                                       // NEW
}
```

### Stop Capture

```http
DELETE /v3/links/{link_id}/capture

Response: 204 No Content
```

### Get Wireshark Access Info

```http
GET /v3/links/{link_id}/wireshark

Response:
{
  "wireshark_url": "http://wireshark-container:10000/#session=xxx",
  "display": ":10",
  "session_id": "xxx"
}
```

## Ansible Playbook Overview

### Create Wireshark Session Playbook

**Trigger:** `POST /v3/links/{link_id}/capture` with `wireshark: true`

**Actions:**

```yaml
- name: Create Linux user for link
  user:
    name: "link-{{ link_id }}"
    shell: /usr/sbin/nologin
    create_home: no
    state: present

- name: Generate xpra password
  shell: xpra passwd link-{{ link_id }} <<< "password"

- name: Start xpra session
  shell: su - link-{{ link_id }} -c "DISPLAY=:{{ display }} xpra start :{{ display }} --html=on --bind-tcp=0.0.0.0:10000"

- name: Start wireshark (consuming capture stream)
  shell: >
    su - link-{{ link_id }} -c "DISPLAY=:{{ display }} wireshark
      -i <(curl -N -H 'Authorization: Bearer {{ user_token }}'
        http://gns3-server:3080/v3/links/{{ link_id }}/capture/stream)"

- name: Apply cgroups limits
  shell: |
    echo 2147483648 > /sys/fs/cgroup/memory/link-{{ link_id }}/memory.limit_in_bytes
    echo 50 > /sys/fs/cgroup/pids/link-{{ link_id }}/pids.max
```

### Cleanup Wireshark Session Playbook

**Trigger:** `DELETE /v3/links/{link_id}/capture`

**Actions:**

```yaml
- name: Stop wireshark process
  shell: pkill -u link-{{ link_id }} wireshark

- name: Stop xpra session
  shell: su - link-{{ link_id }} -c "DISPLAY=:{{ display }} xpra stop :{{ display }}"

- name: Remove Linux user
  user:
    name: "link-{{ link_id }}"
    state: absent
```

## Session Lifecycle

| Event | Action |
|-------|--------|
| Start capture with wireshark | Ansible creates user, starts xpra + wireshark |
| User disconnects noVNC | Session keeps running, capture continues |
| Stop capture | Ansible kills wireshark, stops xpra, removes user |
| Container restart | Sessions lost, user must restart capture |

## Component Responsibilities

| Component | Role |
|-----------|------|
| GNS3 Server | Capture data provider, saves pcap to disk |
| `capture/stream` API | Streams pcap data via HTTP to authorized consumers |
| Ansible | Handles wireshark session create/cleanup on container |
| Wireshark Container | Hosts multiple Wireshark instances via xpra |
| xpra | Manages multiple X sessions, provides WebSocket/VNC |
| noVNC | Bridges xpra X session to browser |
| Linux User (per link_id) | Isolates processes, files, resources per session |
| cgroups | Enforces resource limits per user |

## Security

- User JWT token is used by Wireshark container to access `capture/stream`
- Each link_id has isolated Linux user with `nologin` shell
- cgroups prevent resource abuse
- xpra uses password-based authentication per session

## Capture Storage

- GNS3 Server saves capture to persistent storage (existing behavior)
- Wireshark consumes real-time stream from `capture/stream` API
- Users can download full capture file anytime via existing download API
- Wireshark container does NOT persist capture data (stateless viewer)
