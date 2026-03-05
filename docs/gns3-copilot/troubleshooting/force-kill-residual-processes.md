# Force Kill (kill -9) Causing Residual Processes Issue

## Problem Description

When using `kill -9` to forcibly close the gns3server process, restarting gns3server results in the following errors:

### 1. Dynamips VM Creation Failure
```
ERROR gns3server.api.routes.compute:133 Compute node error: Dynamips error when running command 'vm create "R1" 1 c7200
': unable to create VM instance 'R1'
```

### 2. Validation Error with project_id as "undefined"
```
ERROR gns3server.api.server:208 Request validation error in /v3/projects/undefined/nodes/{node_id} (PUT):
1 validation error:
  {'type': 'uuid_parsing', 'loc': ('path', 'project_id'), 'msg': 'Input should be a valid UUID, invalid character: expected an optional prefix of `urn:uuid:` followed by [0-9a-fA-F-], found `u` at 1', 'input': 'undefined', ...}
```

### 3. TCP Port Still in Use Warning
```
WARNING gns3server.compute.project:355 Project d672144c-4de9-4a97-a23d-307ddc3ab9b1 has TCP ports still in use: {5001}
```

## Root Cause

When using `kill -9` to forcibly terminate the gns3server process, gns3server has no opportunity to properly clean up its spawned child processes, leaving the following residual processes running:

- **Dynamips hypervisor processes** (dynamips)
- **VPCS virtual PC processes** (vpcs)
- **Docker containers** (although shown as removed in logs, some state may not be cleaned up)
- **Other emulator processes**

These residual processes will:
1. Occupy the same port numbers and resource IDs
2. Maintain old socket connections
3. Cause the newly started gns3server to be unable to reallocate the same resources

## Solutions

### Method 1: Manual Cleanup of Residual Processes (Recommended)

After forcibly closing gns3server, find and clean up residual processes:

```bash
# Find dynamips processes
ps aux | grep dynamips

# Find vpcs processes
ps aux | grep vpcs

# Terminate residual processes
killall dynamips
killall vpcs
```

### Method 2: Use pkill to Clean Related Processes

```bash
# Clean all GNS3 related processes
pkill -9 dynamips
pkill -9 vpcs
pkill -9 ubridge
```

### Method 3: Check Before Restart

Before restarting gns3server, ensure there are no residual processes:

```bash
# Check if there are residual GNS3 processes
ps aux | grep -E "(dynamips|vpcs|ubridge|gns3)" | grep -v grep
```

## Preventive Measures

### 1. Use Proper Shutdown Methods

Prefer the following methods to close gns3server instead of `kill -9`:

```bash
# If using systemd
sudo systemctl stop gns3server

# If running directly
# Press Ctrl+C or use normal kill signal
kill <gns3server-pid>
```

### 2. Use SIGTERM Instead of SIGKILL

```bash
# Try normal termination first (allows process to clean up)
kill -15 <gns3server-pid>

# Wait a few seconds, if process is still running, then use kill -9
sleep 3
if ps -p <gns3server-pid> > /dev/null; then
    kill -9 <gns3server-pid>
fi
```

### 3. Implement Automatic Cleanup Script

You can create a startup script to check and clean up residual processes:

```bash
#!/bin/bash
# cleanup_before_start.sh

# Check and clean residual dynamips processes
if pgrep -f dynamips > /dev/null; then
    echo "Found residual dynamips processes, cleaning up..."
    killall -9 dynamips
fi

# Check and clean residual vpcs processes
if pgrep -f vpcs > /dev/null; then
    echo "Found residual vpcs processes, cleaning up..."
    killall -9 vpcs
fi

# Wait for ports to be released
sleep 1

# Start gns3server
gns3server
```

## Technical Details

### Why Does kill -9 Cause This Problem?

1. **SIGKILL signal cannot be captured**: Processes cannot capture or ignore the SIGKILL signal, so there's no chance to execute cleanup code
2. **Child processes become orphans**: After the parent process is forcibly terminated, child processes are adopted by init/PID 1, but they don't know the parent has died
3. **Resources not released**: Sockets, ports, file locks, and other resources are not properly released
4. **State inconsistency**: gns3server's internal state (such as port allocation, ID allocation) is cleared, but actual resources are still occupied

### Code Locations Involved

- **Dynamips Process Management**: `gns3server/compute/dynamips/`
- **Port Allocation and Tracking**: `gns3server/compute/project.py:355`
- **Node Update API**: `gns3server/api/routes/controller/nodes.py:230`

## Related Issues

- [ ] Consider automatically detecting and cleaning up residual processes at gns3server startup
- [ ] Add process health check mechanism
- [ ] Implement more robust port and ID reuse logic
- [ ] Add residual process detection and warnings
