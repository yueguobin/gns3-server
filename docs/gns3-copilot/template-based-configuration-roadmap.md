# Template-Based Configuration with HITL - Future Roadmap

**Status:** 💡 Proposed
**Target Version:** Next Release
**Last Updated:** 2026-03-20

## Overview

This document outlines the plan for implementing a **Jinja2-based template system with Human-in-the-Loop (HITL) confirmations** for network device configuration in GNS3 AI Copilot.

### Motivation

The current implementation requires AI to generate complete configuration commands for every device, which:

- **Consumes excessive tokens:** Each device configuration is generated independently (~150 tokens/device × 10 devices = 1500 tokens)
- **Lacks user control:** Configurations are executed immediately without human review
- **No reusability:** Similar configurations must be regenerated from scratch
- **Higher error risk:** Direct execution without preview or confirmation

### Proposed Solution

Implement a **three-step HITL workflow** using Jinja2 templates:

1. **AI generates template** → Human reviews and confirms
2. **AI generates parameters** → Human reviews and confirms
3. **Local rendering and execution** → Results displayed

**Expected Token Savings:** 70-80% reduction for multi-device configurations

---

## Architecture Design

### Workflow Diagram

```
User Request: "Configure OSPF on all routers"
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 1: AI Generates Jinja2 Template                         │
│                                                              │
│ Output:                                                      │
│ {                                                            │
│   "template_content": "router ospf {{ pid }}\n...",         │
│   "description": "OSPF basic configuration",                │
│   "params_schema": {                                         │
│     "process_id": "int - OSPF process ID",                  │
│     "networks": "List[Dict] - network list",                │
│     "area": "str - area ID"                                 │
│   }                                                          │
│ }                                                            │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ 🔵 HITL Checkpoint 1: Template Review                       │
│                                                              │
│ User sees:                                                  │
│ - Template content (Jinja2 syntax)                          │
│ - Parameter schema                                          │
│ - Example rendered output                                   │
│                                                              │
│ Options: [✓ Confirm] [✏️ Modify] [❌ Cancel]                 │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: AI Generates Parameters                             │
│                                                              │
│ Output:                                                      │
│ {                                                            │
│   "project_id": "uuid-xxx",                                  │
│   "device_params": [                                         │
│     {                                                        │
│       "device_name": "R1",                                   │
│       "process_id": 1,                                       │
│       "networks": [{"ip": "192.168.1.0", "mask": "0.0.0.255"}], │
│       "area": "0"                                            │
│     },                                                       │
│     ... // More devices                                      │
│   ]                                                          │
│ }                                                            │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ 🔵 HITL Checkpoint 2: Parameter Review                      │
│                                                              │
│ User sees:                                                  │
│ - Parameter preview per device                              │
│ - Rendered configuration commands                           │
│ - Summary of changes                                         │
│                                                              │
│ Options: [✓ Execute] [✏️ Modify] [👁️ Preview] [❌ Cancel]    │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Local Rendering & Execution                         │
│                                                              │
│ Process:                                                     │
│ 1. Render template with parameters (0 tokens)               │
│ 2. Call existing ExecuteMultipleDeviceConfigCommands        │
│ 3. Return execution results                                  │
└─────────────────────────────────────────────────────────────┘
```

### Token Consumption Comparison

#### Scenario: Configure OSPF on 10 Cisco Routers

| Approach | Token Usage | Breakdown |
|----------|-------------|-----------|
| **Current Method** | **~1500 tokens** | 150 tokens/device × 10 devices |
| **Template Method** | **~400 tokens** | Template: 150 + Parameters: 250 |
| **Savings** | **73%** | 1100 tokens saved |

#### Scenario: Configure VLANs on 20 Switches

| Approach | Token Usage | Breakdown |
|----------|-------------|-----------|
| **Current Method** | **~1600 tokens** | 80 tokens/switch × 20 switches |
| **Template Method** | **~400 tokens** | Template: 100 + Parameters: 300 |
| **Savings** | **75%** | 1200 tokens saved |

#### 🔥 Scenario: Large-Scale Topology - 500+ Routers

**This is where the template-based approach truly shines for rapid environment provisioning.**

| Approach | Token Usage | Execution Time | Breakdown |
|----------|-------------|----------------|-----------|
| **Current Method (AI)** | **~75,000 tokens** | ~25 minutes | 150 tokens/device × 500 devices, serial execution |
| **Template + AI** | **~5,000 tokens** | ~10 minutes | Template once + AI generates params, but slow |
| **Template + Rules (Direct)** | **~400 tokens** | **~3 minutes** | Template once + rule engine (0 tokens) + parallel execution |
| **Savings** | **99.5%** | **88%** | **Game-changing for large deployments** |

**Key Insight:** For environments with **hundreds or thousands of nodes**, the direct execution mode (skipping AI) becomes critical for rapid topology preparation.

---

## Core Components

### 1. New LangChain Tools

#### Tool 1: `GenerateConfigTemplate`

```python
class GenerateConfigTemplate(BaseTool):
    """
    Generates Jinja2 configuration templates for human review.

    This tool ONLY generates templates. No configuration is executed.

    Input:
    {
        "project_id": "project-uuid",
        "device_type": "cisco_ios | huawei_vrp | ...",
        "requirement": "user requirement description"
    }

    Output:
    {
        "template_content": "jinja2 template string",
        "template_description": "human-readable description",
        "params_schema": {
            "param_name": "type - description"
        },
        "rendered_example": "example output with sample data"
    }
    """

    name = "generate_config_template"
    description = "Generate Jinja2 templates for network device configuration"
```

#### Tool 2: `GenerateTemplateParams`

```python
class GenerateTemplateParams(BaseTool):
    """
    Generates parameter data for confirmed templates.

    Uses the template that was confirmed in the previous step.

    Input:
    {
        "project_id": "project-uuid",
        "confirmed_template": { ... },  # From previous step
        "topology_context": { ... }
    }

    Output:
    {
        "project_id": "project-uuid",
        "device_params": [
            {
                "device_name": "R1",
                "param1": "value1",
                "param2": "value2"
            }
        ],
        "preview": {
            "R1": ["config", "commands"],
            "R2": ["config", "commands"]
        }
    }
    """

    name = "generate_template_params"
    description = "Generate parameters for confirmed configuration templates"
```

#### Tool 3: `ExecuteTemplateBasedConfig`

```python
class ExecuteTemplateBasedConfig(BaseTool):
    """
    Executes configuration using confirmed template and parameters.

    This tool ONLY executes. No generation happens here.

    Input:
    {
        "project_id": "project-uuid",
        "confirmed_template": "jinja2 template",
        "confirmed_params": [ ... ]
    }

    Output:
    {
        "results": [
            {
                "device_name": "R1",
                "status": "success",
                "config_commands": ["command1", "command2"],
                "output": "execution output"
            }
        ]
    }
    """

    name = "execute_template_based_config"
    description = "Execute configuration from templates (0 token cost)"
```

### 2. Template Renderer Module

```python
# gns3server/agent/gns3_copilot/config_templates/template_renderer.py

from jinja2 import Environment, BaseLoader

class ConfigTemplateRenderer:
    """
    Renders Jinja2 templates for network device configuration.

    Key features:
    - Preserves configuration indentation
    - Supports conditionals and loops
    - No token consumption (local execution)
    """

    def __init__(self):
        self.env = Environment(
            loader=BaseLoader(),
            trim_l_blocks=True,      # Remove left whitespace
            trim_r_blocks=True,      # Remove right whitespace
            lstrip_blocks=True,      # Strip leading whitespace
            keep_trailing_newline=False,
            autoescape=False         # Don't escape config commands
        )

    def render(self, template: str, params: dict) -> list[str]:
        """
        Render template and return configuration commands.

        Args:
            template: Jinja2 template string
            params: Template parameters

        Returns:
            List of configuration commands (one per line)
        """
        tmpl = self.env.from_string(template)
        rendered = tmpl.render(**params)

        # Split into commands and filter empty lines
        commands = [
            line.strip()
            for line in rendered.split('\n')
            if line.strip()
        ]

        return commands
```

### 3. Session State Management

```python
# gns3server/agent/gns3_copilot/template_session_manager.py

class TemplateSessionManager:
    """
    Manages template state across HITL workflow.

    Stores:
    - Confirmed templates (awaiting parameter generation)
    - Template metadata (description, schema)
    - Session history
    """

    def __init__(self):
        self.sessions = {}  # project_id -> session_data

    def save_template(self, project_id: str, template_data: dict):
        """Save user-confirmed template to session."""
        if project_id not in self.sessions:
            self.sessions[project_id] = {}

        self.sessions[project_id]['confirmed_template'] = template_data
        self.sessions[project_id]['updated_at'] = datetime.now()

    def get_template(self, project_id: str) -> dict | None:
        """Retrieve confirmed template for session."""
        return self.sessions.get(project_id, {}).get('confirmed_template')

    def clear_session(self, project_id: str):
        """Clear session data after execution or cancellation."""
        if project_id in self.sessions:
            del self.sessions[project_id]
```

### 4. Updated System Prompt

```python
# gns3server/agent/gns3_copilot/prompts/template_workflow_prompt.py

TEMPLATE_WORKFLOW_GUIDE = """
# Configuration Generation with HITL Workflow

When users request device configuration, follow this THREE-STEP process:

## Step 1: Generate Configuration Template

Use `generate_config_template` to create a Jinja2 template.

**IMPORTANT:** Wait for user confirmation before proceeding.

### Template Format Example

```jinja2
router ospf {{ process_id }}
{% for network in networks %}
 network {{ network.ip }} {{ network.mask }} area {{ area }}
{% endfor %}
```

### Parameter Schema Example

```json
{
  "process_id": "int - OSPF process ID",
  "networks": "List[Dict] - Each dict has 'ip' and 'mask' keys",
  "area": "str - OSPF area ID"
}
```

## Step 2: Generate Parameters

After user confirms the template, use `generate_template_params` to generate device-specific parameters.

**IMPORTANT:** Wait for user confirmation before executing.

## Step 3: Execute Configuration

After user confirms parameters, use `execute_template_based_config` to execute.

## Critical Rules

- ⚠️ MUST wait for confirmation after each step
- ⚠️ DO NOT skip confirmation steps
- ✅ Proceed to next step only after user confirmation
- ❌ Stop if user cancels at any point

## Benefits

- **70-80% token savings** for multi-device configurations
- **Human review** at every critical step
- **Template reusability** across similar configurations
- **Preview capabilities** before execution
"""
```

### 5. LangGraph State Machine

```python
# gns3server/agent/gns3_copilot/workflows/template_config_graph.py

from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal

class TemplateConfigState(TypedDict):
    """State for template-based configuration workflow."""
    messages: list[BaseMessage]
    current_step: Literal[
        "idle",
        "generating_template",
        "template_review",
        "generating_params",
        "params_review",
        "executing",
        "completed",
        "cancelled"
    ]
    project_id: str
    confirmed_template: dict | None
    confirmed_params: dict | None
    user_confirmation: str | None
    execution_results: dict | None

def should_generate_params(state: TemplateConfigState) -> str:
    """Check if template was confirmed."""
    if state.get("user_confirmation") == "template_confirmed":
        return "generate_params"
    return "end"

def should_execute(state: TemplateConfigState) -> str:
    """Check if params were confirmed."""
    if state.get("user_confirmation") == "params_confirmed":
        return "execute"
    return "end"

# Build workflow graph
workflow = StateGraph(TemplateConfigState)

# Add nodes
workflow.add_node("generate_template", generate_template_node)
workflow.add_node("generate_params", generate_params_node)
workflow.add_node("execute", execute_config_node)

# Add conditional edges
workflow.add_conditional_edges(
    "generate_template",
    should_generate_params,
    {
        "generate_params": "generate_params",
        "end": END
    }
)

workflow.add_conditional_edges(
    "generate_params",
    should_execute,
    {
        "execute": "execute",
        "end": END
    }
)

workflow.add_edge("execute", END)
```

---

## UI/UX Design

### Template Review Interface

```
┌────────────────────────────────────────────────────────────────┐
│ 📋 AI-Generated Configuration Template                         │
│ ────────────────────────────────────────────────────────────── │
│                                                                 │
│ Device Type: Cisco IOS                                          │
│ Description: OSPF basic configuration                          │
│                                                                 │
│ Template Content:                                               │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ router ospf {{ process_id }}                             │   │
│ │ {% for network in networks %}                            │   │
│ │  network {{ network.ip }} {{ network.mask }} area {{ area }} │   │
│ │ {% endfor %}                                             │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│ Parameter Schema:                                               │
│ • process_id: int - OSPF process ID                            │
│ • networks: List[Dict] - Network configurations                │
│   - ip: str - Network address                                  │
│   - mask: str - Wildcard mask                                  │
│ • area: str - OSPF area ID                                     │
│                                                                 │
│ Example Output:                                                 │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ router ospf 1                                            │   │
│ │  network 192.168.1.0 0.0.0.255 area 0                    │   │
│ │  network 10.0.0.0 0.255.255.255 area 0                   │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│ [✓ Confirm & Continue]  [✏️ Request Modification]  [❌ Cancel]  │
└────────────────────────────────────────────────────────────────┘
```

### Parameter Review Interface

```
┌────────────────────────────────────────────────────────────────┐
│ 📊 Configuration Parameters Preview                            │
│ ────────────────────────────────────────────────────────────── │
│                                                                 │
│ Total Devices: 3                                               │
│ Template: OSPF basic configuration                             │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Device: R1                                               │   │
│ │ ─────────────────────────────────────────────────────── │   │
│ │ • process_id: 1                                          │   │
│ │ • area: 0                                                │   │
│ │ • networks:                                              │   │
│ │   - 192.168.1.0/24 → area 0                             │   │
│ │   - 10.0.0.0/8 → area 0                                 │   │
│ │                                                          │   │
│ │ Rendered Configuration:                                  │   │
│ │ router ospf 1                                           │   │
│ │  network 192.168.1.0 0.0.0.255 area 0                   │   │
│ │  network 10.0.0.0 0.255.255.255 area 0                  │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Device: R2                                               │   │
│ │ ...                                                      │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│ [✓ Execute Configuration]  [✏️ Modify Parameters]               │
│ [👁️ Preview All]  [❌ Cancel]                                  │
└────────────────────────────────────────────────────────────────┘
```

---

## 🔥 Large-Scale Topology Support (1000+ Nodes)

### Overview

One of the most powerful use cases for the template-based configuration system is **rapid provisioning of large-scale network topologies**. This section details optimizations for environments with **hundreds to thousands of nodes**.

### Challenge: Traditional AI Approach at Scale

```
Problem: Configure 1000 routers with OSPF

Traditional AI Approach:
- AI generates config for each router: 150 tokens × 1000 = 150,000 tokens
- Serial or limited parallel execution: ~30-50 minutes
- High cost, slow execution, poor scalability
```

### Solution: Direct Execution Mode

The key innovation is allowing users to **modify and directly execute** templates without requiring AI re-analysis:

```
Template-Based Direct Execution:
1. AI generates template once: ~150 tokens
2. User reviews and modifies if needed
3. User clicks "⚡ Confirm & Execute"
4. Rule engine generates params for 1000 devices: 0 tokens
5. Parallel execution (50-100 concurrent): ~5 minutes
6. Total: 150 tokens, 5 minutes
```

### Enhanced HITL Workflow for Scale

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: AI Generates Template (Once)                         │
│                                                              │
│ User: "Configure OSPF on all 1000 routers"                   │
│                                                              │
│ AI generates template: ~150 tokens                           │
│ router ospf {{ process_id }}                                 │
│ {% for network in networks %}                                │
│  network {{ network.ip }} {{ network.mask }} area {{ area }} │
│ {% endfor %}                                                 │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ 🔵 HITL Checkpoint 1: Template Review                        │
│                                                              │
│ User can:                                                    │
│ - Review template syntax                                     │
│ - Modify template directly                                  │
│ - See preview with sample data                               │
│                                                              │
│ Actions: [✓ Confirm & Continue]  [⚡ Confirm & Execute*]     │
│          [✏️ Modify]  [❌ Cancel]                             │
│                                                              │
│ * "Confirm & Execute" = Skip AI, go to rule engine           │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2A: Rule Engine (0 tokens) OR Step 2B: AI (5000 tokens)│
│                                                              │
│ If user chose "⚡ Confirm & Execute":                        │
│   → Rule engine analyzes template                            │
│   → Extracts device names from topology                      │
│   → Auto-assigns IPs and parameters                          │
│   → Generates 1000 device param sets: 0 tokens               │
│                                                              │
│ If user chose "✓ Confirm & Continue":                       │
│   → AI analyzes template                                     │
│   → Generates parameters: ~5000 tokens                       │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ 🔵 HITL Checkpoint 2: Parameter Review                       │
│                                                              │
│ For 1000 devices, show SUMMARY:                              │
│ - Total devices: 1000                                        │
│ - Configuration patterns: 3 unique patterns                 │
│ - Sample configs (first 3 devices)                           │
│ - IP addressing scheme used                                  │
│                                                              │
│ Actions: [⚡ Execute All*]  [✓ Review & Modify]  [❌ Cancel] │
│                                                              │
│ * "Execute All" = Start parallel execution                   │
└─────────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Parallel Batch Execution                             │
│                                                              │
│ Configuration execution:                                     │
│ - Batch size: 50 devices (configurable)                      │
│ - Batches: 20 total (1000 / 50)                              │
│ - Parallel execution within each batch                       │
│ - Real-time progress updates via SSE                         │
│ - Estimated time: 3-5 minutes                                │
│                                                              │
│ Progress updates:                                             │
│ Batch 1/20: Configuring devices 1-50...                      │
│ Batch 2/20: Configuring devices 51-100...                    │
│ ...                                                          │
│ Complete: 998 success, 2 failed                              │
└─────────────────────────────────────────────────────────────┘
```

### Rule Engine: Intelligent Parameter Generation

```python
# gns3server/agent/gns3_copilot/config_templates/param_generator.py

def generate_params_for_large_topology(
    template: str,
    topology_info: dict,
    addressing_scheme: str = "sequential"
) -> dict:
    """
    Generate parameters for 1000+ devices using rule-based logic.

    Key features:
    - Extract device numbering from names (R1, R2, ... R1000)
    - Auto-assign IP addresses sequentially
    - Group devices by type and apply patterns
    - Zero AI token consumption
    """

    nodes = topology_info.get("nodes", [])

    # Group by device type
    devices_by_type = group_by_device_type(nodes)
    # Result: {"router": [R1, R2, ..., R500], "switch": [SW1, ..., SW500]}

    device_params = []

    for device_type, type_nodes in devices_by_type.items():
        for idx, node in enumerate(type_nodes, start=1):
            device_name = node.get("name")

            # Extract device number from name
            device_num = extract_device_number(device_name, idx)
            # R1 → 1, Router-100 → 100, DeviceX → fallback to idx

            # Generate parameters using rules
            params = {
                "device_name": device_name,
                "process_id": 1,
                "area": "0",
                "router_id": f"1.1.1.{device_num}",
                "networks": [
                    {
                        "ip": f"192.168.{device_num}.0",
                        "mask": "0.0.0.255"
                    }
                ],
                "loopback": {
                    "ip": f"10.{device_num}.1.1",
                    "mask": "255.255.255.255"
                }
            }

            device_params.append(params)

    return {
        "device_params": device_params,
        "total_devices": len(device_params),
        "generation_method": "rule_engine",
        "addressing_scheme": addressing_scheme
    }


# Example: 1000 devices configured in < 1 second
# Token cost: 0 (pure rule-based logic)
```

### Batch Parallel Execution

```python
# gns3server/agent/gns3_copilot/tools_v2/config_tools_nornir.py

class ExecuteTemplateBasedConfig(BaseTool):
    """Optimized for large-scale parallel execution."""

    def _run(self, tool_input: str | dict) -> dict:
        """Execute configuration with dynamic batching."""

        device_params = data.get("device_params", [])
        total_devices = len(device_params)

        # 🔥 Dynamic batch sizing based on device count
        if total_devices <= 10:
            batch_size = 10
        elif total_devices <= 50:
            batch_size = 20
        elif total_devices <= 100:
            batch_size = 30
        elif total_devices <= 500:
            batch_size = 50
        else:  # 500+ devices
            batch_size = 100  # High concurrency for large topologies

        results = {
            "total_devices": total_devices,
            "batch_size": batch_size,
            "total_batches": (total_devices + batch_size - 1) // batch_size,
            "batches": []
        }

        # Process in batches with progress tracking
        for batch_num in range(0, total_devices, batch_size):
            batch_end = min(batch_num + batch_size, total_devices)
            batch_params = device_params[batch_num:batch_end]

            # Render configs for this batch
            batch_configs = [
                {
                    "device_name": p["device_name"],
                    "config_commands": renderer.render(template, p)
                }
                for p in batch_params
            ]

            # Execute batch in parallel using Nornir
            batch_result = self._execute_batch_parallel(
                project_id,
                batch_configs,
                batch_num // batch_size + 1
            )

            results["batches"].append(batch_result)

            # Yield progress for SSE streaming
            yield_progress({
                "type": "batch_complete",
                "batch": batch_num // batch_size + 1,
                "progress": int((batch_end / total_devices) * 100)
            })

        return results
```

### Real-Time Progress Streaming

```typescript
// Frontend: Large-scale configuration progress UI

class LargeScaleConfigProgress {
  displayProgress() {
    // Show progress bar for 1000 devices
    return `
      <div class="config-progress">
        <h3>⚙️ Configuring 1000 Devices</h3>

        <div class="progress-bar">
          <div class="progress-fill" style="width: 0%"></div>
        </div>

        <div class="stats">
          <div class="stat success">
            <span class="icon">✅</span>
            <span class="label">Success:</span>
            <span class="value" id="success-count">0</span>
          </div>

          <div class="stat failed">
            <span class="icon">❌</span>
            <span class="label">Failed:</span>
            <span class="value" id="failed-count">0</span>
          </div>

          <div class="stat progress">
            <span class="icon">📊</span>
            <span class="label">Progress:</span>
            <span class="value" id="progress-text">0%</span>
          </div>

          <div class="stat time">
            <span class="icon">⏱️</span>
            <span class="label">ETA:</span>
            <span class="value" id="eta">~5 min</span>
          </div>
        </div>

        <div class="current-batch">
          <span id="batch-info">Preparing...</span>
        </div>
      </div>
    `;
  }

  updateProgress(data) {
    // Update progress bar
    const fill = document.querySelector('.progress-fill');
    fill.style.width = `${data.progress}%`;

    // Update stats
    document.getElementById('success-count').textContent = data.success;
    document.getElementById('failed-count').textContent = data.failed;
    document.getElementById('progress-text').textContent = `${data.progress}%`;
    document.getElementById('batch-info').textContent =
      `Batch ${data.batch}/20: Configuring devices ${data.range}...`;
  }
}
```

### Configuration Summary for Large Topologies

For 1000 devices, showing full configurations is impractical. Instead, provide **intelligent summaries**:

```python
class ConfigSummaryGenerator:
    """Generate summaries for large-scale configurations."""

    def generate_summary(self, template: str, device_params: list) -> dict:
        """
        Generate configuration summary for 1000+ devices.

        Shows:
        - Pattern analysis (how many unique config patterns)
        - Sample configs (first 3 devices)
        - IP addressing scheme used
        - Estimated total lines of configuration
        """

        total_devices = len(device_params)

        # Render all configs to analyze patterns
        renderer = ConfigTemplateRenderer()
        all_configs = {}

        for params in device_params:
            device_name = params["device_name"]
            config = renderer.render(template, params)
            all_configs[device_name] = config

        # Analyze patterns
        unique_patterns = {}
        for device_name, config in all_configs.items():
            pattern_hash = hash(tuple(config))
            if pattern_hash not in unique_patterns:
                unique_patterns[pattern_hash] = []
            unique_patterns[pattern_hash].append(device_name)

        # Generate summary
        return {
            "total_devices": total_devices,
            "unique_patterns": len(unique_patterns),
            "patterns": [
                {
                    "count": len(devices),
                    "sample_devices": devices[:5] + ["..."] if len(devices) > 5 else devices,
                    "config_preview": all_configs[devices[0]][:5]  # First 5 lines
                }
                for devices in unique_patterns.values()
            ],
            "estimated_total_lines": sum(len(c) for c in all_configs.values()),
            "examples": {
                device_name: all_configs[device_name]
                for device_name in list(all_configs.keys())[:3]  # First 3 only
            }
        }
```

### Performance Benchmarks

#### Scenario: 1000 Router OSPF Configuration

| Metric | Traditional AI | Template + AI | Template + Direct |
|--------|---------------|---------------|-------------------|
| **Token Consumption** | 150,000 | 5,000 | **400** |
| **Execution Time** | 30-50 min | 10-15 min | **3-5 min** |
| **Cost (at $10/M tokens)** | $1.50 | $0.05 | **$0.004** |
| **User Control** | Low | Medium | **High** |
| **Parallel Execution** | Limited | Yes | **Yes (100 concurrent)** |

#### Scenario: 5000 Switch VLAN Configuration

| Metric | Traditional AI | Template + Direct |
|--------|---------------|-------------------|
| **Token Consumption** | 400,000 | **400** |
| **Execution Time** | 2-3 hours | **15-20 min** |
| **Cost** | $4.00 | **$0.004** |
| **Scalability** | Poor | **Excellent** |

### Addressing Schemes for Large Topologies

The rule engine supports multiple automatic addressing schemes:

```python
# 1. Sequential Addressing (Default)
# R1: 192.168.1.0/24, R2: 192.168.2.0/24, ..., R1000: 192.168.1000.0/24

# 2. VLAN-Based Addressing
# VLAN 100: 10.0.100.0/24, VLAN 101: 10.0.101.0/24, ...

# 3. Hierarchical Addressing
# Core routers: 10.0.0.0/24
# Distribution routers: 10.1.0.0/16
# Access switches: 10.100.0.0/16

# 4. Device Type Based
# Routers: 192.168.0.0/16
# Switches: 192.169.0.0/16
# Firewalls: 192.170.0.0/16
```

### Error Handling for Scale

For 1000+ devices, some failures are inevitable. The system provides:

```python
{
    "total_devices": 1000,
    "summary": {
        "success": 987,
        "failed": 13,
        "skipped": 0
    },
    "failed_devices": [
        {
            "device_name": "R456",
            "error": "Connection timeout",
            "retry_available": true
        },
        ...
    ],
    "retry_suggestions": {
        "auto_retry": True,
        "retry_batch_size": 10,
        "exponential_backoff": True
    }
}
```

### Use Cases for Large-Scale Support

1. **Network Training Labs**: Provision 1000+ device labs for student training
2. **CI/CD Testing**: Automated topology setup for testing network automation scripts
3. **Disaster Recovery Drills**: Rapid deployment of large backup topologies
4. **Network Simulation**: Research environments with thousands of nodes
5. **Data Center Fabric**: Configure spine-leaf topologies with hundreds of leaf switches

---

## Implementation Phases

### Phase 1: Core MVP (Minimum Viable Product)

**Status:** 📋 Planned
**Estimated Effort:** 3-5 days

**Tasks:**
1. ✅ Create `ConfigTemplateRenderer` class
2. ✅ Create `TemplateSessionManager` class
3. ✅ Implement `GenerateConfigTemplate` tool
4. ✅ Implement `GenerateTemplateParams` tool
5. ✅ Implement `ExecuteTemplateBasedConfig` tool
6. ✅ Create `config_templates/` package structure
7. ✅ Update system prompts with template workflow
8. ✅ Basic error handling and validation

**Deliverables:**
- Working three-step HITL workflow
- Template rendering for Cisco IOS devices
- Basic CLI/API responses
- Unit tests for core components

### Phase 2: Enhanced User Experience & Direct Execution

**Status:** 💡 Proposed
**Estimated Effort:** 2-3 days

**Tasks:**
1. Enhanced UI for template/parameter review
2. Configuration preview functionality
3. Template modification and retry logic
4. 🔥 **Direct execution mode** (skip AI, use rule engine)
5. Progress indicators for multi-device configs
6. Improved error messages and recovery

**Deliverables:**
- User-friendly review interfaces
- Preview-before-execute capability
- **Rule-based parameter generation (0 token cost)**
- User documentation

### Phase 3: Template Library & Large-Scale Support

**Status:** 💡 Proposed
**Estimated Effort:** 2-3 days

**Tasks:**
1. Template persistence and storage
2. Pre-built template library (OSPF, BGP, VLAN, NAT, etc.)
3. 🔥 **Batch parallel execution** (dynamic batching for 100+ devices)
4. 🔥 **Rule engine enhancements** (intelligent parameter generation)
5. 🔥 **Real-time progress streaming** via SSE
6. Template versioning and history

**Deliverables:**
- 20+ pre-built templates
- **Support for 1000+ device configurations**
- **Parallel execution with 50-100 concurrent connections**
- Template management API

### Phase 4: Advanced Features & Optimization

**Status:** 💡 Proposed
**Estimated Effort:** 3-4 days

**Tasks:**
1. Multi-vendor template support (Huawei, H3C, Juniper)
2. 🔥 **Intelligent addressing schemes** (sequential, VLAN-based, hierarchical)
3. 🔥 **Configuration summary generation** (pattern analysis for large topologies)
4. Configuration diff and comparison
5. Template analytics and usage statistics
6. 🔥 **Performance optimization** (caching, connection pooling)

**Deliverables:**
- Multi-vendor template ecosystem
- **Optimized for 10,000+ node topologies**
- Advanced configuration management
- Analytics dashboard

---

## Technical Considerations

### Jinja2 Configuration

```python
# Network device configurations require special handling
Environment(
    # Preserve indentation for config hierarchy
    trim_l_blocks=True,      # Remove block left whitespace
    trim_r_blocks=True,      # Remove block right whitespace
    lstrip_blocks=True,      # Strip leading whitespace from lines

    # Don't escape configuration commands
    autoescape=False,

    # Custom filters for network operations
    filters={
        'to_cidr': lambda ip, mask: f"{ip}/{mask}",
        'ip_network': lambda ip: ipaddr.IPv4Network(ip),
        # Add more as needed
    }
)
```

### Security Considerations

1. **Template Validation:**
   - Validate template syntax before rendering
   - Check for dangerous operations (file I/O, system calls)
   - Sandbox Jinja2 environment

2. **Parameter Validation:**
   - Type checking for all parameters
   - Range validation (IP addresses, VLAN IDs, etc.)
   - Device-specific validation

3. **Command Filtering:**
   - Apply existing `command_filter.py` checks
   - Integrate with forbidden commands list
   - Maintain audit logging

### Error Handling Strategy

```python
class TemplateExecutionError(Exception):
    """Base class for template execution errors."""
    pass

class TemplateSyntaxError(TemplateExecutionError):
    """Template has invalid Jinja2 syntax."""
    pass

class ParameterValidationError(TemplateExecutionError):
    """Parameters don't match template schema."""
    pass

class RenderingError(TemplateExecutionError):
    """Error during template rendering."""
    pass

# Error response format
{
    "error": "error_type",
    "message": "Human-readable error message",
    "details": {
        "template": "...",
        "params": {...},
        "traceback": "..."  # Only in development
    },
    "suggestions": [
        "Check template syntax",
        "Verify parameter types",
        "Review device compatibility"
    ]
}
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_template_renderer.py
def test_simple_template_rendering():
    template = "interface {{ name }}\n ip address {{ ip }} {{ mask }}"
    params = {"name": "GigabitEthernet0/0", "ip": "192.168.1.1", "mask": "255.255.255.0"}
    renderer = ConfigTemplateRenderer()
    result = renderer.render(template, params)
    assert result == [
        "interface GigabitEthernet0/0",
        "ip address 192.168.1.1 255.255.255.0"
    ]

def test_loop_template_rendering():
    template = "{% for n in networks %}network {{ n }}\n{% endfor %}"
    params = {"networks": ["192.168.1.0", "192.168.2.0"]}
    renderer = ConfigTemplateRenderer()
    result = renderer.render(template, params)
    assert result == ["network 192.168.1.0", "network 192.168.2.0"]

def test_conditional_template_rendering():
    template = "{% if ospf %}router ospf 1\n{% endif %}exit"
    params = {"ospf": True}
    renderer = ConfigTemplateRenderer()
    result = renderer.render(template, params)
    assert "router ospf 1" in result
```

### Integration Tests

```python
# tests/test_template_workflow_integration.py
def test_full_template_workflow():
    """Test complete HITL workflow from template to execution."""
    # Step 1: Generate template
    template_tool = GenerateConfigTemplate()
    template_result = template_tool._run({
        "project_id": test_project_id,
        "device_type": "cisco_ios",
        "requirement": "Configure OSPF"
    })
    assert "template_content" in template_result

    # Step 2: Generate params
    params_tool = GenerateTemplateParams()
    params_result = params_tool._run({
        "project_id": test_project_id,
        "confirmed_template": template_result
    })
    assert "device_params" in params_result

    # Step 3: Execute
    execute_tool = ExecuteTemplateBasedConfig()
    exec_result = execute_tool._run({
        "project_id": test_project_id,
        "confirmed_template": template_result["template_content"],
        "confirmed_params": params_result["device_params"]
    })
    assert "results" in exec_result
```

### End-to-End Tests

```python
# tests/test_e2e_template_config.py
def test_ospf_configuration_10_routers():
    """Test OSPF configuration on 10 routers."""
    # Setup: Create GNS3 project with 10 routers
    project_id = create_test_project(device_count=10)

    # Execute workflow
    result = run_template_workflow(
        project_id=project_id,
        requirement="Configure OSPF on all routers"
    )

    # Verify
    assert result["status"] == "success"
    assert len(result["configured_devices"]) == 10
    assert all(["ospf" in dev["config"] for dev in result["configured_devices"]])
```

---

## Success Metrics

### Token Savings

- **Target:** 70%+ reduction in token usage for multi-device configurations
- **Measurement:** Compare token usage before/after for same tasks

### User Adoption

- **Target:** 60%+ of configuration tasks use template workflow
- **Measurement:** Track tool usage statistics

### Error Reduction

- **Target:** 50%+ reduction in configuration errors
- **Measurement:** Compare error rates before/after HITL

### User Satisfaction

- **Target:** 4.5+ star rating (5-star scale)
- **Measurement:** Post-task user surveys

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| AI generates invalid Jinja2 syntax | High | Add template validation, provide syntax feedback |
| Users find HITL workflow too slow | Medium | Add "quick confirm" option, template reuse |
| Template reuse causes stale configs | Medium | Template versioning, checksum validation |
| Multi-vendor complexity | High | Phase 1: Cisco only, Phase 4: expand |
| Session state management bugs | Medium | Comprehensive testing, state cleanup |

---

## Open Questions

1. **Template Storage:** Should templates be stored per-user or shared globally?
2. **Template Validation:** How strict should template validation be?
3. **Backward Compatibility:** Should existing direct-config tools remain available?
4. **Template Sharing:** Should users be able to share templates in a marketplace?
5. **Performance:** How to handle template rendering for 100+ devices?

---

## Dependencies

### Required Python Packages

```txt
jinja2>=3.1.0
langchain>=0.1.0
langgraph>=0.0.20
```

### Integration Points

- `gns3server/agent/gns3_copilot/tools_v2/config_tools_nornir.py` (existing)
- `gns3server/agent/gns3_copilot/prompts/lab_automation_assistant_prompt.py` (update)
- `gns3server/agent/gns3_copilot/gns3_client/gns3_topology_reader.py` (existing)
- `gns3server/agent/gns3_copilot/utils/command_filter.py` (existing)

---

## Timeline

### Sprint 1: Foundation (Week 1-2)
- Core rendering engine
- Three LangChain tools
- Basic session management
- System prompt updates

### Sprint 2: User Experience (Week 3)
- Review interfaces
- Preview functionality
- Error handling
- Documentation

### Sprint 3: Enhancement (Week 4-5)
- Template library
- Caching mechanisms
- Multi-vendor support
- Testing and QA

### Sprint 4: Polish (Week 6)
- Performance optimization
- Bug fixes
- User feedback integration
- Release preparation

---

## References

- [Jinja2 Documentation](https://jinja.palletsprojects.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Existing Config Tools](../implemented/multi-vendor-device-support.md)
- [Command Security](../implemented/command-security.md)

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-20 | 0.2 | Added large-scale topology support section (1000+ nodes), direct execution mode, batch parallel execution, rule engine optimizations |
| 2026-03-20 | 0.1 | Initial roadmap document created |

---

**Document Status:** 💡 Proposed - Awaiting Implementation
**Next Review:** After Phase 1 completion

---

*For questions or feedback about this roadmap, please open an issue or contact the AI Copilot team.*
