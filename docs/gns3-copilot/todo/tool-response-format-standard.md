# GNS3 Copilot Tool Response Format Standard

## Overview

This document defines the standard response format for GNS3 Copilot tools, ensuring all tools return a unified data structure for easy frontend processing and display.

## Standard Response Format

### Top-level Structure

All tools should return the following standard format:

```python
{
    "success": bool,           # Whether the overall operation succeeded
    "total": int,              # Total number of operations
    "successful": int,         # Number of successful operations
    "failed": int,             # Number of failed operations
    "data": list[dict],       # Detailed result list
    "error": str,             # Global error message (optional, when operation completely fails)
    "metadata": dict          # Metadata (optional)
}
```

**Field Descriptions**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `success` | `bool` | Yes | Whether the overall operation succeeded (True when `failed == 0`) |
| `total` | `int` | Yes | Total number of items processed |
| `successful` | `int` | Yes | Number of successful items |
| `failed` | `int` | Yes | Number of failed items |
| `data` | `list[dict]` | Yes | Detailed results for each item |
| `error` | `str` | No | Global error message (when entire operation fails) |
| `metadata` | `dict` | No | Metadata (timestamp, execution time, etc.) |

### Single Item Format

Each item in the `data` array should follow this format:

```python
{
    "id": str,                 # Device/node/link ID
    "name": str,               # Human-readable name
    "status": "success" | "failed",  # Item status
    "result": str,             # Result or output on success
    "error": str               # Error message on failure
}
```

**Field Descriptions**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | Yes | Unique identifier for device/node/link |
| `name` | `str` | Yes | Human-readable name |
| `status` | `str` | Yes | `"success"` or `"failed"` |
| `result` | `str` | Conditional | Output when status is `success` |
| `error` | `str` | Conditional | Error message when status is `failed` |

## Examples

### Success Response Example

```python
# Execute display commands on multiple devices
{
    "success": True,
    "total": 3,
    "successful": 2,
    "failed": 1,
    "data": [
        {
            "id": "R1",
            "name": "Router1",
            "status": "success",
            "result": "Cisco IOS Software...\nRouter1# show version\n..."
        },
        {
            "id": "R2",
            "name": "Router2",
            "status": "success",
            "result": "Cisco IOS Software...\nRouter2# show version\n..."
        },
        {
            "id": "R3",
            "name": "Router3",
            "status": "failed",
            "error": "Connection refused"
        }
    ],
    "metadata": {
        "tool_name": "execute_multiple_device_commands",
        "execution_time": 5.2
    }
}
```

### Complete Failure Example

```python
# Entire operation failed (e.g., parameter error)
{
    "success": False,
    "total": 0,
    "successful": 0,
    "failed": 0,
    "data": [],
    "error": "Invalid project_id format",
    "metadata": {
        "tool_name": "execute_multiple_device_commands"
    }
}
```

### Single Device Operation Example

```python
# Operate on a single device
{
    "success": True,
    "total": 1,
    "successful": 1,
    "failed": 0,
    "data": [
        {
            "id": "PC1",
            "name": "VPCS-1",
            "status": "success",
            "result": "IP configuration updated: 192.168.1.10/24"
        }
    ],
    "metadata": {}
}
```

## Using the Standardization Function

The `normalize_tool_response` function is provided in the `gns3server.agent.gns3_copilot.utils` module to convert various formats to the standard format:

```python
from gns3server.agent.gns3_copilot.utils import normalize_tool_response

# Normalize tool response
normalized = normalize_tool_response(raw_response, tool_name="my_tool")
```

This function supports:
- List format (`[{...}, {...}]`)
- Dict format (`{"nodes": [...]}`)
- String format (automatically parses JSON/Python literal)
- Mixed format (compatible with legacy tools)

## Compatibility

### Backward Compatibility

The `normalize_tool_response` function is designed to be backward compatible and can handle various formats from existing tools:

- `status` / `error` fields
- `output` / `result` fields
- `device_name` / `name` fields
- `total_nodes` / `total` fields

### Recommended Migration Strategy

1. **New Tools**: Return standard format directly
2. **Existing Tools**: Keep unchanged, use `normalize_tool_response` to standardize
3. **Frontend**: Rely on standard format for display processing

## Frontend Integration Recommendations

### Rendering Logic

```javascript
function renderToolResponse(response) {
    if (!response.success) {
        // Show global error
        showError(response.error);
        return;
    }

    // Show statistics summary
    showSummary(response.total, response.successful, response.failed);

    // Render each item
    response.data.forEach(item => {
        if (item.status === 'success') {
            showSuccess(item.name, item.result);
        } else {
            showError(item.name, item.error);
        }
    });
}
```

### Status Icons

| Status | Icon Suggestion | Color |
|--------|----------------|-------|
| `success` | ✓ Green | Green |
| `failed` | ✗ Red | Red |
| `unknown` | ? Gray | Gray |

## Version Control

Current standard version: `v1.0`

When the format changes, update the `metadata.version` field, and the frontend adapts accordingly.

## References

- Implementation: `gns3server/agent/gns3_copilot/utils/parse_tool_content.py`
- Message conversion: `gns3server/agent/gns3_copilot/utils/message_converters.py`
- Tool examples: `gns3server/agent/gns3_copilot/tools_v2/`
