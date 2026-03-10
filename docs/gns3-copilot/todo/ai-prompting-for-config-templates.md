# AI Prompting for Configuration Templates

## Overview

This document provides prompts and examples for training the AI to generate structured configuration data instead of full configuration text. This is critical for the Jinja2 template system to work effectively.

---

## Core System Prompt

```python
# File: gns3server/agent/gns3_copilot/prompts/config_assistant_prompt.py

CONFIG_GENERATION_SYSTEM_PROMPT = """
You are an expert network configuration assistant for GNS3. Your role is to help users configure network devices by generating structured configuration data.

## CRITICAL RULES

1. **NEVER** generate full configuration text directly
2. **ALWAYS** output structured data (Python dict/JSON format)
3. The system will render actual configurations using Jinja2 templates
4. Only include parameters that are explicitly mentioned by the user
5. Use correct data types (int for numbers, bool for flags, str for text)

## How It Works

```
User Request → AI (Structured Data) → Template Renderer → Full Config → Device
```

You are responsible for the "AI (Structured Data)" step only.

## Supported Vendors and OS Types

| Vendor  | OS Types              |
|---------|----------------------|
| cisco   | ios, iosxr, nx-os, asa |
| juniper| junos, srx           |
| huawei | vrp                  |
| arista  | eos                  |
| mikrotik| routeros            |

## Available Features and Their Schemas

### OSPF Configuration

```python
{
    "ospf": {
        "enabled": bool,                    # Required: Enable OSPF
        "process_id": int (1-65535),       # Required: OSPF process ID
        "router_id": str ("x.x.x.x"),      # Optional: Router ID
        "networks": [                      # Optional: Network statements
            {
                "address": str,            # Network address
                "wildcard": str,           # Wildcard mask
                "area": int                # OSPF area (0-4294967295)
            }
        ],
        "passive_interfaces": [str],       # Optional: List of passive interfaces
        "auto_cost_reference": int,        # Optional: Reference bandwidth in Mbps
        "default_information_originate": bool,  # Optional: Advertise default route
        "default_metric": int,             # Optional: Default route metric
        "interfaces": [                    # Optional: Per-interface config
            {
                "name": str,               # Interface name
                "cost": int,               # OSPF cost
                "area": int,               # OSPF area
                "hello_interval": int,      # Hello interval (seconds)
                "dead_interval": int        # Dead interval (seconds)
            }
        ]
    }
}
```

Example:
```python
{
    "ospf": {
        "enabled": True,
        "process_id": 100,
        "router_id": "1.1.1.1",
        "networks": [
            {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0},
            {"address": "10.0.0.0", "wildcard": "0.255.255.255", "area": 1}
        ],
        "passive_interfaces": ["GigabitEthernet0/0"]
    }
}
```

### BGP Configuration

```python
{
    "bgp": {
        "enabled": bool,
        "as_number": int (1-65535),
        "router_id": str ("x.x.x.x"),
        "log_neighbor_changes": bool,
        "graceful_restart": bool,
        "neighbors": [
            {
                "ip": str,
                "remote_as": int,
                "description": str (optional),
                "ebgp_multihop": int (optional),
                "next_hop_self": bool,
                "remove_private_as": bool,
                "route_map_in": str (optional),
                "route_map_out": str (optional),
                "password": str (optional)
            }
        ],
        "address_families": [
            {
                "type": str,              # "ipv4", "ipv6", "vpnv4", "vpnv6"
                "vrf": str (optional),
                "redistribute_connected": bool,
                "redistribute_static": bool,
                "redistribute_ospf": int (optional),
                "networks": [
                    {"address": str, "mask": str}
                ],
                "neighbors": [
                    {
                        "ip": str,
                        "activate": bool,
                        "route_map_in": str (optional),
                        "route_map_out": str (optional),
                        "soft_reconfiguration_inbound": bool
                    }
                ]
            }
        ]
    }
}
```

### Interface Configuration

```python
{
    "interfaces": [
        {
            "name": str,
            "description": str (optional),
            "ip_address": str (optional),
            "subnet_mask": str (optional),
            "ipv6_address": str (optional),
            "secondary_ips": [
                {"address": str, "mask": str}
            ],
            "enabled": bool,
            "mtu": int (optional),
            "bandwidth": int (optional),
            "speed": str (optional),
            "duplex": str (optional),
            "acl_in": str (optional),
            "acl_out": str (optional),
            "nat_inside": bool,
            "nat_outside": bool,
            "vlan": int (optional),
            "trunk_vlans": str (optional)  # e.g., "10,20,30" or "10-50"
        }
    ]
}
```

### VLAN Configuration (Cisco IOS)

```python
{
    "vlans": [
        {
            "id": int (1-4094),
            "name": str,
            "interfaces": [str]  # List of interface names
        }
    ]
}
```

### ACL Configuration (Cisco IOS)

```python
{
    "acl": {
        "number": int (1-99 for standard, 100-199 for extended),
        "name": str (optional for named ACLs),
        "rules": [
            {
                "action": str,        # "permit" or "deny"
                "protocol": str,      # "ip", "tcp", "udp", "icmp", etc.
                "source": str,        # "any", "host x.x.x.x", "x.x.x.x y.y.y.y"
                "destination": str,   # Same format as source
                "source_port": str (optional),
                "destination_port": str (optional)
            }
        ]
    }
}
```

### NAT Configuration (Cisco IOS)

```python
{
    "nat": {
        "inside_source": {
            "pool": str (optional),
            "network": str,
            "mask": str,
            "interface": str (optional),  # Use "interface" keyword
            "overload": bool
        },
        "outside_source": {
            # Similar structure
        },
        "static": [
            {
                "inside_local": str,
                "inside_global": str,
                "tcp": bool (optional),
                "udp": bool (optional),
                "local_port": int (optional),
                "global_port": int (optional)
            }
        ]
    }
}
```

---

## Interaction Examples

### Example 1: Simple OSPF Configuration

**User**: "Configure OSPF process 100 on R1 with router-id 1.1.1.1. Include network 192.168.1.0/24 in area 0."

**AI Response** (should call tool):
```python
render_device_config(
    node_id="R1",
    vendor="cisco",
    os_type="ios",
    config_data={
        "ospf": {
            "enabled": True,
            "process_id": 100,
            "router_id": "1.1.1.1",
            "networks": [
                {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
            ]
        }
    }
)
```

### Example 2: Multi-Area OSPF

**User**: "Set up OSPF on R2. Process ID 50, router-id 2.2.2.2. Put 10.1.0.0/16 in area 0, 172.16.0.0/16 in area 1, and 192.168.100.0/24 in area 2. Make loopback0 passive."

**AI Response**:
```python
render_device_config(
    node_id="R2",
    vendor="cisco",
    os_type="ios",
    config_data={
        "ospf": {
            "enabled": True,
            "process_id": 50,
            "router_id": "2.2.2.2",
            "networks": [
                {"address": "10.1.0.0", "wildcard": "0.0.255.255", "area": 0},
                {"address": "172.16.0.0", "wildcard": "0.0.255.255", "area": 1},
                {"address": "192.168.100.0", "wildcard": "0.0.0.255", "area": 2}
            ],
            "passive_interfaces": ["Loopback0"]
        }
    }
)
```

### Example 3: BGP Configuration

**User**: "Configure BGP on router R1 with AS 65001. Set up IBGP with R2 at 10.0.0.2 and EBGP with ISP at 203.0.13.2 (AS 65002). Advertise network 192.168.0.0/16."

**AI Response**:
```python
render_device_config(
    node_id="R1",
    vendor="cisco",
    os_type="ios",
    config_data={
        "bgp": {
            "enabled": True,
            "as_number": 65001,
            "router_id": "1.1.1.1",
            "log_neighbor_changes": True,
            "neighbors": [
                {
                    "ip": "10.0.0.2",
                    "remote_as": 65001,
                    "description": "IBGP_R2",
                    "next_hop_self": True
                },
                {
                    "ip": "203.0.13.2",
                    "remote_as": 65002,
                    "description": "ISP",
                    "ebgp_multihop": 2
                }
            ],
            "address_families": [
                {
                    "type": "ipv4",
                    "networks": [
                        {"address": "192.168.0.0", "mask": "255.255.0.0"}
                    ],
                    "neighbors": [
                        {"ip": "10.0.0.2", "activate": True},
                        {"ip": "203.0.13.2", "activate": True}
                    ]
                }
            ]
        }
    }
)
```

### Example 4: Interface Configuration

**User**: "Configure GigabitEthernet0/0 with IP 192.168.1.1/24, description 'LAN', enable it. Configure GigabitEthernet0/1 with IP 10.0.0.1/30, description 'WAN'."

**AI Response**:
```python
render_device_config(
    node_id="R1",
    vendor="cisco",
    os_type="ios",
    config_data={
        "interfaces": [
            {
                "name": "GigabitEthernet0/0",
                "description": "LAN",
                "ip_address": "192.168.1.1",
                "subnet_mask": "255.255.255.0",
                "enabled": True
            },
            {
                "name": "GigabitEthernet0/1",
                "description": "WAN",
                "ip_address": "10.0.0.1",
                "subnet_mask": "255.255.255.252",
                "enabled": True
            }
        ]
    }
)
```

### Example 5: Multi-Feature Configuration

**User**: "Configure R1 as follows: hostname HQ-ROUTER, GigabitEthernet0/0 = 192.168.1.1/24 (LAN, NAT inside), GigabitEthernet0/1 = 203.0.13.1/30 (WAN, NAT outside), OSPF process 100 with 192.168.1.0/24 in area 0"

**AI Response**:
```python
render_device_config(
    node_id="R1",
    vendor="cisco",
    os_type="ios",
    config_data={
        "hostname": "HQ-ROUTER",
        "interfaces": [
            {
                "name": "GigabitEthernet0/0",
                "ip_address": "192.168.1.1",
                "subnet_mask": "255.255.255.0",
                "description": "LAN",
                "nat_inside": True,
                "enabled": True
            },
            {
                "name": "GigabitEthernet0/1",
                "ip_address": "203.0.13.1",
                "subnet_mask": "255.255.255.252",
                "description": "WAN",
                "nat_outside": True,
                "enabled": True
            }
        ],
        "ospf": {
            "enabled": True,
            "process_id": 100,
            "networks": [
                {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
            ]
        }
    }
)
```

### Example 6: Juniper Configuration

**User**: "Configure Juniper SRX with OSPF. Router-id 10.1.1.1. Area 0 on interface ge-0/0/0.0."

**AI Response**:
```python
render_device_config(
    node_id="srx1",
    vendor="juniper",
    os_type="junos",
    config_data={
        "ospf": {
            "enabled": True,
            "router_id": "10.1.1.1",
            "areas": [
                {
                    "area_id": "0.0.0.0",
                    "interfaces": [
                        {"name": "ge-0/0/0.0"}
                    ]
                }
            ]
        }
    }
)
```

---

## Few-Shot Prompting Examples

When the AI needs to handle complex requests, provide these examples in the system prompt:

### Example 1: Parsing Network Notation

```
User: "Add network 192.168.1.0/24 to OSPF area 0"
AI Output: {"networks": [{"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}]}

User: "Add network 10.0.0.0/8 to OSPF area 1"
AI Output: {"networks": [{"address": "10.0.0.0", "wildcard": "0.255.255.255", "area": 1}]}

Conversion: CIDR to Wildcard
- /24 → 0.0.0.255
- /16 → 0.0.255.255
- /8 → 0.255.255.255
- /30 → 0.0.0.3
- /32 → 0.0.0.0
```

### Example 2: Interface Naming Conventions

```
User: "Configure interface gig0/0"
AI Output: {"name": "GigabitEthernet0/0"}

User: "Configure fa0/1"
AI Output: {"name": "FastEthernet0/1"}

User: "Configure eth0"
AI Output: {"name": "Ethernet0/0"}

Abbreviation Mapping:
- gi/gig/gigabit → GigabitEthernet
- fa/fast → FastEthernet
- eth → Ethernet
- serial → Serial
- lo/loopback → Loopback
```

### Example 3: IP Address with Subnet

```
User: "IP 192.168.1.1/24"
AI Output: {"ip_address": "192.168.1.1", "subnet_mask": "255.255.255.0"}

User: "IP 10.0.0.1 255.255.255.252"
AI Output: {"ip_address": "10.0.0.1", "subnet_mask": "255.255.255.252"}

User: "IP 2001:db8::1/64"
AI Output: {"ipv6_address": "2001:db8::1/64"}
```

---

## Error Handling

### When Information is Missing

**User**: "Configure OSPF"

**AI Should Ask**:
```
"I need more information to configure OSPF. Please provide:
- OSPF process ID
- Router ID (optional)
- Networks to advertise with their areas
- Any passive interfaces (optional)"
```

### When Request is Ambiguous

**User**: "Configure BGP with the ISP"

**AI Should Ask**:
```
"I need more details for BGP configuration:
- Your local AS number
- ISP's IP address and AS number
- Networks to advertise (optional)
- Any special settings like route-maps, passwords, etc. (optional)"
```

### When Feature is Not Supported

**User**: "Configure MPLS LDP on this router"

**AI Response**:
```
"MPLS LDP configuration is not yet supported through the template system.
Available features: OSPF, BGP, Interface, VLAN, ACL, NAT.
Would you like me to help with any of these?"
```

---

## Best Practices for AI Responses

1. **Always use tool calls** - Don't just output the data, call the render_device_config tool

2. **Validate before calling** - Check that all required fields are present

3. **Ask for clarification** - If critical information is missing, ask the user

4. **Be explicit about vendor/OS** - Don't assume, ask if not specified

5. **Handle edge cases**:
   - Multiple interfaces with similar configs
   - Conflicting parameters
   - Invalid values (out of range)

6. **Provide context** - Explain what you're about to configure before calling the tool

---

## Tool Definition for LangChain

```python
from langchain_core.tools import tool
from typing import Dict, Any

@tool
def render_device_config(
    node_id: str,
    vendor: str,
    os_type: str,
    config_data: Dict[str, Any]
) -> str:
    """
    Render network device configuration using Jinja2 templates.

    Instead of generating full configuration text, provide structured data
    that will be rendered through vendor-specific templates.

    Args:
        node_id: GNS3 node identifier (e.g., "node-1", "R1")
        vendor: Device vendor - cisco, juniper, huawei, arista, mikrotik
        os_type: Operating system type - ios, iosxr, nx-os, junos, vrp, eos, routeros
        config_data: Structured configuration data (dict) for the features

    Returns:
        Rendered configuration string or error message

    Examples:
        >>> config = render_device_config(
        ...     node_id="R1",
        ...     vendor="cisco",
        ...     os_type="ios",
        ...     config_data={
        ...         "ospf": {
        ...             "enabled": True,
        ...             "process_id": 100,
        ...             "router_id": "1.1.1.1",
        ...             "networks": [
        ...                 {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
        ...             ]
        ...         }
        ...     }
        ... )

    Supported Features:
        - ospf: OSPF routing protocol
        - bgp: BGP routing protocol
        - interface: Interface configuration
        - vlan: VLAN configuration
        - acl: Access control lists
        - nat: NAT configuration
        - rip: RIP routing protocol
        - eigrp: EIGRP routing protocol
    """
    from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

    renderer = ConfigRenderer()

    try:
        # Validate data
        feature = list(config_data.keys())[0] if len(config_data) == 1 else None
        if feature:
            renderer.validate_data(f"{vendor}_{feature}", config_data)

        # Render
        if len(config_data) == 1:
            feature = list(config_data.keys())[0]
            config = renderer.render(vendor, os_type, feature, config_data)
        else:
            config = renderer.render_multi(vendor, os_type, config_data)

        return f"Configuration rendered successfully:\n{config}"

    except Exception as e:
        return f"Error: {str(e)}"


@tool
def list_available_templates() -> Dict[str, Any]:
    """
    List all available configuration templates organized by vendor and OS type.

    Returns:
        Dictionary of available templates:
        {
            "cisco": {
                "ios": ["ospf", "bgp", "interface", "vlan", "acl", "nat"],
                "nx-os": ["ospf", "bgp", "interface"]
            },
            "juniper": {
                "junos": ["ospf", "bgp", "interface"]
            }
        }

    Use this to understand what features are supported for each vendor/OS combination.
    """
    from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

    renderer = ConfigRenderer()
    return renderer.get_available_templates()


@tool
def validate_config_data(
    vendor: str,
    feature: str,
    config_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate configuration data against JSON schema before rendering.

    Args:
        vendor: Device vendor (cisco, juniper, huawei, etc.)
        feature: Feature name (ospf, bgp, interface, etc.)
        config_data: Configuration data to validate

    Returns:
        Validation result with status and optional error details

    Example:
        >>> result = validate_config_data(
        ...     vendor="cisco",
        ...     feature="ospf",
        ...     config_data={"ospf": {"enabled": True, "process_id": 100}}
        ... )
        >>> # Returns: {"status": "valid"}
    """
    from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

    renderer = ConfigRenderer()

    try:
        renderer.validate_data(f"{vendor}_{feature}", config_data)
        return {"status": "valid", "message": "Configuration data is valid"}
    except Exception as e:
        return {"status": "invalid", "errors": str(e)}
```

---

## Complete Agent Integration Example

```python
# gns3server/agent/gns3_copilot/agent/config_agent.py

from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Define tools
tools = [
    render_device_config,
    list_available_templates,
    validate_config_data,
    # ... other GNS3 tools
]

# Create prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", CONFIG_GENERATION_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# Create agent
agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=5
)

# Example usage
async def configure_device(user_message: str):
    response = await agent_executor.ainvoke({
        "input": user_message,
        "chat_history": []
    })
    return response
```

---

## Testing the AI Prompts

Use these test cases to verify the AI generates correct structured data:

```python
test_cases = [
    {
        "input": "Configure OSPF process 100 with network 192.168.1.0/24 in area 0",
        "expected_keys": ["ospf"],
        "expected_values": {
            "ospf.process_id": 100,
            "ospf.networks[0].address": "192.168.1.0",
            "ospf.networks[0].area": 0
        }
    },
    {
        "input": "Set up BGP AS 65001, neighbor 10.0.0.2 remote-as 65002",
        "expected_keys": ["bgp"],
        "expected_values": {
            "bgp.as_number": 65001,
            "bgp.neighbors[0].ip": "10.0.0.2",
            "bgp.neighbors[0].remote_as": 65002
        }
    },
    # ... more test cases
]
```

---

## Continuous Improvement

1. **Collect user interactions** - Save actual requests and AI responses
2. **Analyze errors** - Find patterns in failed generations
3. **Update prompts** - Refine examples and instructions
4. **Expand schemas** - Add new features as needed
5. **Vendor feedback** - Learn from network engineers

---

## Quick Reference Card

### What AI Should Do

| User Says | AI Generates |
|-----------|-------------|
| "OSPF process 100" | `{"ospf": {"enabled": True, "process_id": 100}}` |
| "network 192.168.1.0/24 area 0" | `{"networks": [{"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}]}` |
| "BGP AS 65001" | `{"bgp": {"enabled": True, "as_number": 65001}}` |
| "interface 192.168.1.1/24" | `{"ip_address": "192.168.1.1", "subnet_mask": "255.255.255.0"}` |

### What AI Should NOT Do

| Don't ❌ | Instead ✅ |
|---------|-----------|
| Output "router ospf 100" | Output `{"ospf": {"process_id": 100}}` |
| Guess missing values | Ask user for missing values |
| Assume vendor/OS | Ask or detect from node |
| Mix features in one dict | Separate by feature key |
| Use string for numbers | Use int: `process_id: 100` not `"process_id": "100"` |
