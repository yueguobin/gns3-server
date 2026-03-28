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
│  │  xpra + noVNC Server (port 10000)                       │   │
│  │  Multi-user X session management                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Linux User Isolation (one user per link_id)            │   │
│  │                                                           │   │
│  │  link-{uuid-1} ──▶ Xvfb :10 ──▶ wireshark               │   │
│  │  link-{uuid-2} ──▶ Xvfb :11 ──▶ wireshark               │   │
│  │  link-{uuid-3} ──▶ Xvfb :12 ──▶ wireshark               │   │
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

## Data Flow

```
1. User clicks "Start Capture" in GNS3 Web UI
   │
   └─▶ POST /v3/links/{link_id}/capture
       Header: Authorization: Bearer {user_jwt}
       │
       ▼
   GNS3 Server starts packet capture
   Capture data written to:
   /path/to/projects/{project_id}/captures/{link_id}.pcap
       │
       ▼
2. User clicks "View in Wireshark"
   │
   └─▶ POST /v3/wireshark/sessions
       Body: { "link_id": "uuid-xxx", "user_token": "{user_jwt}" }
       │
       ▼
   GNS3 Server creates Linux user (if not exists):
   useradd -M link-{uuid}
       │
       ▼
   Server starts Wireshark in container as link-{uuid}:
   su - link-{uuid} -c "wireshark -i <(curl -N \
     -H 'Authorization: Bearer {user_token}' \
     {gns3_server}/v3/links/{link_id}/capture/stream)"
       │
       ▼
   Wireshark connects to GNS3 Server's stream API as the user,
   consumes pcap data in real-time, renders GUI
       │
       ▼
3. Server returns noVNC access info:
   {
     "session_id": "uuid-xxx",
     "wireshark_url": "http://wireshark-container:10000/#session=uuid-xxx",
     "display": ":10"
   }
       │
       ▼
4. Frontend opens noVNC iframe with Wireshark GUI
```

## Capture Storage

- GNS3 Server saves capture to persistent storage (existing behavior)
- Wireshark consumes real-time stream from `capture/stream` API
- Users can download full capture file anytime via existing download API
- Wireshark container does NOT persist capture data (stateless viewer)

## API

### Create Wireshark Session

```http
POST /v3/wireshark/sessions

Request:
{
  "link_id": "string",
  "user_token": "string"  // User's JWT token for capture/stream access
}

Response:
{
  "session_id": "string",
  "wireshark_url": "string",
  "display": ":10"
}
```

### Delete Wireshark Session

```http
DELETE /v3/wireshark/sessions/{session_id}

Response:
204 No Content
```

### Get Session Status

```http
GET /v3/wireshark/sessions/{session_id}

Response:
{
  "session_id": "string",
  "link_id": "string",
  "status": "running|stopped",
  "display": ":10"
}
```

## Component Responsibilities

| Component | Role |
|-----------|------|
| GNS3 Server | Capture data provider, saves pcap to disk |
| `capture/stream` API | Streams pcap data to authorized consumers |
| Wireshark Container | Hosts multiple Wireshark instances via xpra |
| xpra | Manages multiple X sessions, provides WebSocket/VNC |
| noVNC | Bridges xpra X session to browser |
| Linux User (per link_id) | Isolates processes, files, resources per session |
| cgroups | Enforces resource limits per user |

## Session Lifecycle

| Event | Action |
|-------|--------|
| Create session | Create Linux user, start xpra + wireshark |
| User disconnects noVNC | Session keeps running, wireshark continues capture |
| Delete session | Kill wireshark, cleanup user processes |
| Inactivity timeout | Auto-terminate after configurable idle period |
| Container restart | Sessions lost, users can restart from UI |

## Security

- User JWT token is passed to Wireshark container for `capture/stream` access
- Each link_id has isolated Linux user with no shell access
- cgroups prevent resource abuse
- xpra uses password-based authentication per session
- Sessions should auto-expire after inactivity (e.g., 1 hour)
