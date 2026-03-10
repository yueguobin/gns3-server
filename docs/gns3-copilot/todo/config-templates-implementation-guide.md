# Configuration Templates Implementation Guide

## Quick Start Examples

### Example 1: Configure OSPF on a Cisco Router

**User Request**:
```
"Configure OSPF on R1 with process ID 100, router-id 1.1.1.1.
Include network 192.168.1.0/24 in area 0 and 10.0.0.0/8 in area 1.
Make GigabitEthernet0/0 a passive interface."
```

**AI Should Generate** (structured JSON):
```json
{
  "ospf": {
    "enabled": true,
    "process_id": 100,
    "router_id": "1.1.1.1",
    "networks": [
      {
        "address": "192.168.1.0",
        "wildcard": "0.0.0.255",
        "area": 0
      },
      {
        "address": "10.0.0.0",
        "wildcard": "0.255.255.255",
        "area": 1
      }
    ],
    "passive_interfaces": ["GigabitEthernet0/0"]
  }
}
```

**Agent Action**:
```python
# The agent calls the render tool with the structured data
result = render_device_config(
    node_id="node-1",
    vendor="cisco",
    os_type="ios",
    config_data=ai_output
)
```

**Rendered Configuration**:
```cisco
router ospf 100
 router-id 1.1.1.1
 network 192.168.1.0 mask 0.0.0.255 area 0
 network 10.0.0.0 mask 0.255.255.255 area 1
 passive-interface GigabitEthernet0/0
!
```

---

### Example 2: Configure BGP with Multiple Neighbors

**User Request**:
```
"Configure BGP on R1 with AS 65001. Set up IBGP with R2 (10.0.0.2, AS 65001)
and EBGP with ISP (203.0.13.2, AS 65002). Advertise network 192.168.0.0/16.
Enable route-map INBOUND-FILTER on R2 inbound."
```

**AI Generates**:
```json
{
  "bgp": {
    "enabled": true,
    "as_number": 65001,
    "router_id": "1.1.1.1",
    "log_neighbor_changes": true,
    "neighbors": [
      {
        "ip": "10.0.0.2",
        "remote_as": 65001,
        "description": "IBGP_Peer_R2",
        "next_hop_self": true,
        "route_map_in": "INBOUND-FILTER"
      },
      {
        "ip": "203.0.13.2",
        "remote_as": 65002,
        "description": "ISP_EBGP",
        "ebgp_multihop": 2
      }
    ],
    "address_families": [
      {
        "type": "ipv4",
        "networks": [
          {
            "address": "192.168.0.0",
            "mask": "255.255.0.0"
          }
        ],
        "neighbors": [
          {"ip": "10.0.0.2", "activate": true},
          {"ip": "203.0.13.2", "activate": true}
        ]
      }
    ]
  }
}
```

**Rendered Configuration**:
```cisco
router bgp 65001
 bgp router-id 1.1.1.1
 bgp log-neighbor-changes
 neighbor 10.0.0.2 remote-as 65001
 neighbor 10.0.0.2 description IBGP_Peer_R2
 neighbor 10.0.0.2 next-hop-self
 neighbor 10.0.0.2 route-map INBOUND-FILTER in
 neighbor 203.0.13.2 remote-as 65002
 neighbor 203.0.13.2 description ISP_EBGP
 neighbor 203.0.13.2 ebgp-multihop 2
 address-family ipv4
  network 192.168.0.0 mask 255.255.0.0
  neighbor 10.0.0.2 activate
  neighbor 203.0.13.2 activate
 exit-address-family
!
```

---

### Example 3: Configure Interfaces with IP Addresses

**User Request**:
```
"Configure GigabitEthernet0/0 with IP 192.168.1.1/24, description 'LAN Network'.
Configure GigabitEthernet0/1 with IP 10.0.0.1/30, description 'WAN Link'.
Both interfaces should be enabled."
```

**AI Generates**:
```json
{
  "interfaces": [
    {
      "name": "GigabitEthernet0/0",
      "description": "LAN Network",
      "ip_address": "192.168.1.1",
      "subnet_mask": "255.255.255.0",
      "enabled": true
    },
    {
      "name": "GigabitEthernet0/1",
      "description": "WAN Link",
      "ip_address": "10.0.0.1",
      "subnet_mask": "255.255.255.252",
      "enabled": true
    }
  ]
}
```

**Rendered Configuration**:
```cisco
interface GigabitEthernet0/0
 description LAN Network
 ip address 192.168.1.1 255.255.255.0
 no shutdown
!
interface GigabitEthernet0/1
 description WAN Link
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
```

---

## Advanced Examples

### Example 4: Multi-Feature Configuration

**User Request**:
```
"Configure R1 as follows:
- Hostname: CORE-R1
- GigabitEthernet0/0: 192.168.1.1/24, LAN, enable NAT inside
- GigabitEthernet0/1: 203.0.13.1/30, WAN, enable NAT outside
- OSPF: process 100, router-id 1.1.1.1, advertise 192.168.1.0/24 in area 0
- NAT: overload interface GigabitEthernet0/1 for 192.168.1.0/24"
```

**AI Generates** (complete configuration):
```json
{
  "hostname": "CORE-R1",
  "interfaces": [
    {
      "name": "GigabitEthernet0/0",
      "description": "LAN",
      "ip_address": "192.168.1.1",
      "subnet_mask": "255.255.255.0",
      "nat_inside": true,
      "enabled": true
    },
    {
      "name": "GigabitEthernet0/1",
      "description": "WAN",
      "ip_address": "203.0.13.1",
      "subnet_mask": "255.255.255.252",
      "nat_outside": true,
      "enabled": true
    }
  ],
  "ospf": {
    "enabled": true,
    "process_id": 100,
    "router_id": "1.1.1.1",
    "networks": [
      {
        "address": "192.168.1.0",
        "wildcard": "0.0.0.255",
        "area": 0
      }
    ]
  },
  "nat": {
    "inside_source": {
      "pool": "LAN_POOL",
      "network": "192.168.1.0",
      "mask": "255.255.255.0",
      "interface": "GigabitEthernet0/1",
      "overload": true
    }
  }
}
```

---

### Example 5: Juniper JunOS Configuration

**User Request**:
```
"Configure Juniper SRX with OSPF area 0 on interface ge-0/0/0.0 with IP 192.168.1.1/24.
Set router-id to 10.1.1.1."
```

**AI Generates**:
```json
{
  "ospf": {
    "enabled": true,
    "router_id": "10.1.1.1",
    "areas": [
      {
        "area_id": "0.0.0.0",
        "interfaces": [
          {
            "name": "ge-0/0/0.0",
            "address": "192.168.1.1/24"
          }
        ]
      }
    ]
  }
}
```

**Template**: `config_templates/juniper/junos/ospf.j2`
```jinja2
{% if ospf.enabled %}
protocols {
    ospf {
{% if ospf.router_id %}
        router-id {{ ospf.router_id }};
{% endif %}
{% for area in ospf.areas %}
        area {{ area.area_id }} {
{% for iface in area.interfaces %}
            interface {{ iface.name }} {
{% if iface.address %}
                family inet {
                    address {{ iface.address }};
                }
{% endif %}
            }
{% endfor %}
        }
{% endfor %}
    }
}
{% endif %}
```

**Rendered Configuration**:
```junos
protocols {
    ospf {
        router-id 10.1.1.1;
        area 0.0.0.0 {
            interface ge-0/0/0.0 {
                family inet {
                    address 192.168.1.1/24;
                }
            }
        }
    }
}
```

---

## Integration with LangGraph Agent

### Updated Agent Flow

```python
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.tools import tool

@tool
def render_and_apply_config(
    node_id: str,
    vendor: str,
    os_type: str,
    config_data: dict
) -> str:
    """Render configuration and apply to device"""
    from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

    renderer = ConfigRenderer()

    # Step 1: Validate
    try:
        renderer.validate_data(f"{vendor}_config", config_data)
    except Exception as e:
        return f"Validation failed: {e}"

    # Step 2: Render
    try:
        if len(config_data) == 1:
            feature = list(config_data.keys())[0]
            config = renderer.render(vendor, os_type, feature, config_data)
        else:
            config = renderer.render_multi(vendor, os_type, config_data)

        # Step 3: Apply to device (via telnet/console/SSH)
        # result = apply_config_to_node(node_id, config)
        return f"Configuration rendered successfully:\n{config}"

    except Exception as e:
        return f"Rendering failed: {e}"


# Updated agent prompt
SYSTEM_PROMPT = """
You are a network configuration assistant for GNS3.

When users ask to configure network devices:
1. Extract the configuration requirements
2. Generate STRUCTURED DATA (JSON/dict), NOT full configuration text
3. Call the render_and_apply_config tool with the structured data
4. The system will render the actual configuration using templates

Example for OSPF:
- User: "Configure OSPF with process 100, network 192.168.1.0/24 in area 0"
- You should output: {"ospf": {"enabled": true, "process_id": 100, ...}}

Available vendors: cisco, juniper, huawei, arista
Available OS types: ios, iosxr, nexus, junos, vrp, eos
"""
```

---

## Template Snippets Library

### OSPF Interface Templates

**Cisco IOS**:
```jinja2
{# ospf.j2 - Cisco IOS OSPF #}
{% if ospf.enabled %}
router ospf {{ ospf.process_id }}
{% if ospf.router_id %}
 router-id {{ ospf.router_id }}
{% endif %}
{% for network in ospf.networks %}
 network {{ network.address }} mask {{ network.wildcard }} area {{ network.area }}
{% endfor %}
{% for iface in ospf.passive_interfaces %}
 passive-interface {{ iface }}
{% endfor %}
!
{% endif %}
```

**Juniper JunOS**:
```jinja2
{# ospf.j2 - Juniper JunOS OSPF #}
{% if ospf.enabled %}
protocols {
    ospf {
{% if ospf.router_id %}
        router-id {{ ospf.router_id }};
{% endif %}
{% for area in ospf.areas %}
        area {{ area.area_id }} {
{% for iface in area.interfaces %}
            interface {{ iface.name }};
{% endfor %}
        }
{% endfor %}
    }
}
{% endif %}
```

**Huawei VRP**:
```jinja2
{# ospf.j2 - Huawei VRP OSPF #}
{% if ospf.enabled %}
ospf {{ ospf.process_id }}
{% if ospf.router_id %}
 router-id {{ ospf.router_id }}
{% endif %}
{% for area in ospf.areas %}
 area {{ area.area_id }}
{% for network in area.networks %}
  network {{ network.address }} {{ network.wildcard }}
{% endfor %}
{% endfor %}
{% endif %}
```

---

## Testing Framework

### Unit Test for Template Rendering

```python
# tests/agent/test_config_renderer.py

import pytest
from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

def test_ospf_cisco_ios():
    """Test OSPF configuration rendering for Cisco IOS"""
    renderer = ConfigRenderer()

    data = {
        "ospf": {
            "enabled": True,
            "process_id": 100,
            "router_id": "1.1.1.1",
            "networks": [
                {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
            ]
        }
    }

    config = renderer.render("cisco", "ios", "ospf", data)

    assert "router ospf 100" in config
    assert "router-id 1.1.1.1" in config
    assert "network 192.168.1.0 mask 0.0.0.255 area 0" in config

def test_bgp_cisco_ios():
    """Test BGP configuration rendering for Cisco IOS"""
    renderer = ConfigRenderer()

    data = {
        "bgp": {
            "enabled": True,
            "as_number": 65001,
            "neighbors": [
                {"ip": "10.0.0.2", "remote_as": 65002}
            ],
            "address_families": [
                {
                    "type": "ipv4",
                    "neighbors": [
                        {"ip": "10.0.0.2", "activate": True}
                    ]
                }
            ]
        }
    }

    config = renderer.render("cisco", "ios", "bgp", data)

    assert "router bgp 65001" in config
    assert "neighbor 10.0.0.2 remote-as 65002" in config
    assert "address-family ipv4" in config
    assert "neighbor 10.0.0.2 activate" in config

def test_interface_cisco_ios():
    """Test interface configuration rendering"""
    renderer = ConfigRenderer()

    data = {
        "interfaces": [
            {
                "name": "GigabitEthernet0/0",
                "description": "Test Interface",
                "ip_address": "192.168.1.1",
                "subnet_mask": "255.255.255.0",
                "enabled": True
            }
        ]
    }

    config = renderer.render("cisco", "ios", "interface", data)

    assert "interface GigabitEthernet0/0" in config
    assert "description Test Interface" in config
    assert "ip address 192.168.1.1 255.255.255.0" in config
    assert "no shutdown" in config
```

---

## API Integration

### New Controller Endpoint

```python
# gns3server/api/routes/controller/config_templates.py

from fastapi import APIRouter, Depends
from typing import Dict, Any
from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

router = APIRouter()

@router.get("/config-templates")
async def list_templates() -> Dict[str, Any]:
    """List all available configuration templates"""
    renderer = ConfigRenderer()
    return renderer.get_available_templates()

@router.post("/config-templates/render")
async def render_config_template(
    vendor: str,
    os_type: str,
    feature: str,
    data: Dict[str, Any]
) -> Dict[str, str]:
    """Render a configuration template with provided data"""
    renderer = ConfigRenderer()

    try:
        config = renderer.render(vendor, os_type, feature, data)
        return {"status": "success", "config": config}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/config-templates/validate")
async def validate_config_data(
    schema_name: str,
    data: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate configuration data against schema"""
    renderer = ConfigRenderer()

    try:
        is_valid = renderer.validate_data(schema_name, data)
        return {"status": "valid"}
    except Exception as e:
        return {"status": "invalid", "errors": str(e)}
```

---

## Prompt Engineering for AI

### System Prompt Template

```python
CONFIG_GENERATION_PROMPT = """
You are a network configuration expert. When users request device configurations:

1. UNDERSTAND the requirements (vendor, OS, features, parameters)
2. GENERATE structured data (dict/JSON), NOT full configuration text
3. CALL the appropriate rendering tool with the structured data

RULES:
- NEVER output full configuration text directly
- ALWAYS use structured data format
- Include only the parameters that are explicitly mentioned
- Use correct data types (int for numbers, bool for flags)
- Follow the JSON schema for each feature

VENDORS: cisco, juniper, huawei, arista, mikrotik
OS TYPES: ios, iosxr, nx-os, junos, vrp, eos, routeros

FEATURES AVAILABLE:
- ospf: process_id, router_id, networks[{address,wildcard,area}]
- bgp: as_number, router_id, neighbors[{ip,remote_as,description,...}]
- interface: name, ip_address, subnet_mask, description, enabled
- vlan: id, name, interfaces[]
- acl: number, rules[{action,protocol,source,destination}]
- nat: inside_source, outside_source, static

EXAMPLE:

User: "Configure OSPF process 100 with router-id 1.1.1.1, network 192.168.1.0/24 area 0"

Your tool call:
render_device_config(
    node_id="node-1",
    vendor="cisco",
    os_type="ios",
    config_data={{
        "ospf": {{
            "enabled": True,
            "process_id": 100,
            "router_id": "1.1.1.1",
            "networks": [
                {{"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}}
            ]
        }}
    }}
)
"""
```

---

## Migration Path

### Phase 1: Core Templates (Week 1-2)
- Cisco IOS: ospf, bgp, interface, vlan, acl
- Juniper JunOS: ospf, bgp, interface
- Schema definitions

### Phase 2: Extended Features (Week 3-4)
- NAT, QoS, Multicast
- Nexus, IOS-XR variants
- Huawei VRP support

### Phase 3: Advanced Features (Week 5-6)
- MPLS, VPN
- Firewall policies (ASA, SRX)
- Automation and testing

### Phase 4: Integration (Week 7-8)
- Integrate with AI Copilot
- Add rendering endpoint to API
- Testing and validation

---

## Best Practices

1. **Template Design**:
   - Keep templates simple and focused
   - Use conditionals sparingly
   - Add comments for complex logic
   - Follow vendor syntax conventions

2. **Schema Design**:
   - Define all fields with types
   - Add descriptions for AI
   - Include validation rules
   - Use enums for fixed values

3. **AI Prompting**:
   - Provide clear examples
   - Specify expected output format
   - Include error handling guidance
   - Test with various inputs

4. **Testing**:
   - Unit test each template
   - Test with real devices
   - Validate schemas
   - Integration testing

---

## Troubleshooting

### Common Issues

**Issue**: Template not found
```
Solution: Check template path format: "{vendor}/{os_type}/{feature}.j2"
```

**Issue**: Invalid data structure
```
Solution: Validate against JSON schema first
```

**Issue**: Rendering produces empty config
```
Solution: Check if feature flag "enabled" is set to True
```

**Issue**: Syntax error in rendered config
```
Solution: Review template logic, check conditional statements
```
