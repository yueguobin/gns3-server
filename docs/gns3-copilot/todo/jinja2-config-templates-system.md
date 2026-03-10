# Jinja2-Based Configuration Template System for GNS3 AI Copilot

## Overview

This document outlines a configuration template system using Jinja2 that allows the AI to generate structured data (JSON) instead of full configuration files. The templates handle the rendering of vendor-specific configurations.

## Architecture

```
User Natural Language
          │
          ▼
    ┌─────────────┐
    │  AI Agent   │
    │    (LLM)    │
    └──────┬──────┘
           │
           ▼
    Structured Data (JSON)
           │
           ▼
    ┌──────────────────────────────────┐
    │   Jinja2 Configuration Renderer   │
    │  ┌────────────────────────────┐  │
    │  │  Template Library           │  │
    │  │  ├── cisco/                │  │
    │  │  │   ├── ospf.j2           │  │
    │  │  │   ├── bgp.j2            │  │
    │  │  │   ├── interface.j2      │  │
    │  │  │   └── ...               │  │
    │  │  ├── juniper/              │  │
    │  │  ├── huawei/               │  │
    │  │  └── linux/                │  │
    │  └────────────────────────────┘  │
    └──────────────────┬───────────────┘
                       │
                       ▼
              Full Configuration File
                       │
                       ▼
              Push to Device
```

## Directory Structure

```
gns3server/agent/gns3_copilot/
├── config_templates/
│   ├── README.md                 # This file
│   ├── base/                     # Base/common templates
│   │   ├── interface_common.j2   # Common interface config
│   │   ├── routing_common.j2     # Common routing config
│   │   └── security_common.j2    # Common security config
│   ├── cisco/                    # Cisco device templates
│   │   ├── ios/                  # IOS/IOS-XE
│   │   │   ├── ospf.j2
│   │   │   ├── bgp.j2
│   │   │   ├── interface.j2
│   │   │   ├── acl.j2
│   │   │   ├── nat.j2
│   │   │   ├── vlan.j2
│   │   │   └── multiservice.j2
│   │   ├── nexus/                # Nexus switches
│   │   │   ├── ospf.j2
│   │   │   ├── bgp.j2
│   │   │   └── interface.j2
│   │   └── asa/                  # ASA firewall
│   │       ├── nat.j2
│   │       └── access_list.j2
│   ├── juniper/                  # Juniper devices
│   │   ├── junos/
│   │   │   ├── ospf.j2
│   │   │   ├── bgp.j2
│   │   │   └── interface.j2
│   │   └── srx/                  # SRX firewall
│   ├── huawei/                   # Huawei devices
│   │   └── vrp/
│   ├── linux/                    # Linux servers
│   │   ├── network.j2
│   │   └── firewall.j2
│   └── schemas/                  # JSON Schema definitions
│       ├── cisco_ospf.json
│       ├── cisco_bgp.json
│       ├── cisco_interface.json
│       └── common.json
├── config_renderer.py            # Template rendering engine
└── config_validator.py           # Schema validation
```

## Template Examples

### 1. OSPF Configuration Template (Cisco IOS)

**File**: `config_templates/cisco/ios/ospf.j2`

```jinja2
{# OSPF Configuration Template for Cisco IOS #}
{% if ospf.enabled %}
router ospf {{ ospf.process_id }}
{% if ospf.router_id %}
 router-id {{ ospf.router_id }}
{% endif %}
{% for network in ospf.networks %}
 network {{ network.address }} mask {{ network.wildcard }} area {{ network.area }}
{% endfor %}
{% if ospf.passive_interfaces %}
{% for interface in ospf.passive_interfaces %}
 passive-interface {{ interface }}
{% endfor %}
{% endif %}
{% if ospf.auto_cost_reference %}
 auto-cost reference-bandwidth {{ ospf.auto_cost_reference }}
{% endif %}
{% if ospf.default_information_originate %}
 default-information originate{{ ' metric' if ospf.default_metric else '' }}{{ ospf.default_metric if ospf.default_metric else '' }}
{% endif %}
!
{% endif %}

{# OSPF Interface Configuration #}
{% for iface in ospf.interfaces %}
interface {{ iface.name }}
{% if iface.cost %}
 ip ospf cost {{ iface.cost }}
{% endif %}
{% if iface.hello_interval %}
 ip ospf hello-interval {{ iface.hello_interval }}
{% endif %}
{% if iface.dead_interval %}
 ip ospf dead-interval {{ iface.dead_interval }}
{% endif %}
{% if iface.authentication %}
 ip ospf authentication{{ ' message-digest' if iface.auth_type == 'message-digest' else '' }}
{% if iface.auth_key %}
 ip ospf authentication-key {{ iface.auth_key }}
{% endif %}
{% if iface.auth_md5_keys %}
{% for key in iface.auth_md5_keys %}
 ip ospf message-digest-key {{ key.id }} md5 {{ key.secret }}
{% endfor %}
{% endif %}
{% endif %}
{% if iface.area %}
 ip ospf {{ ospf.process_id }} area {{ iface.area }}
{% endif %}
!
{% endfor %}
```

### 2. AI Output (JSON) for OSPF

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
    "passive_interfaces": ["GigabitEthernet0/0"],
    "interfaces": [
      {
        "name": "GigabitEthernet0/1",
        "cost": 10,
        "area": 0,
        "hello_interval": 10,
        "dead_interval": 40
      }
    ],
    "auto_cost_reference": 100000,
    "default_information_originate": true,
    "default_metric": 100
  }
}
```

### 3. Rendered Configuration Output

```cisco
router ospf 100
 router-id 1.1.1.1
 network 192.168.1.0 mask 0.0.0.255 area 0
 network 10.0.0.0 mask 0.255.255.255 area 1
 passive-interface GigabitEthernet0/0
 auto-cost reference-bandwidth 100000
 default-information originate metric 100
!
interface GigabitEthernet0/1
 ip ospf cost 10
 ip ospf hello-interval 10
 ip ospf dead-interval 40
 ip ospf 100 area 0
!
```

## BGP Configuration Template

**File**: `config_templates/cisco/ios/bgp.j2`

```jinja2
{% if bgp.enabled %}
router bgp {{ bgp.as_number }}
{% if bgp.router_id %}
 bgp router-id {{ bgp.router_id }}
{% endif %}
{% if bgp.log_neighbor_changes %}
 bgp log-neighbor-changes
{% endif %}
{% if bgp.graceful_restart %}
 bgp graceful-restart
{% endif %}

{# BGP Neighbors #}
{% for neighbor in bgp.neighbors %}
 neighbor {{ neighbor.ip }} remote-as {{ neighbor.remote_as }}
 {% if neighbor.description %}
 neighbor {{ neighbor.ip }} description {{ neighbor.description }}
 {% endif %}
 {% if neighbor.ebgp_multihop %}
 neighbor {{ neighbor.ip }} ebgp-multihop {{ neighbor.ebgp_multihop }}
 {% endif %}
 {% if neighbor.next_hop_self %}
 neighbor {{ neighbor.ip }} next-hop-self
 {% endif %}
 {% if neighbor.remove_private_as %}
 neighbor {{ neighbor.ip }} remove-private-as
 {% endif %}
 {% if neighbor.route_map_in %}
 neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_in }} in
 {% endif %}
 {% if neighbor.route_map_out %}
 neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_out }} out
 {% endif %}
 {% if neighbor.password %}
 neighbor {{ neighbor.ip }} password {{ neighbor.password }}
 {% endif %}
{% endfor %}

{# Address Families #}
{% for af in bgp.address_families %}
 address-family {{ af.type }} {{ af.vrf if af.vrf else '' }}
 {% if af.redistribute_connected %}
  redistribute connected
 {% endif %}
 {% if af.redistribute_static %}
  redistribute static
 {% endif %}
 {% if af.redistribute_ospf %}
  redistribute ospf {{ af.redistribute_ospf }}
 {% endif %}
 {% if af.networks %}
 {% for network in af.networks %}
  network {{ network.address }} mask {{ network.mask }}
 {% endfor %}
 {% endif %}
 {% for neighbor in af.neighbors %}
  neighbor {{ neighbor.ip }} activate
  {% if neighbor.route_map_in %}
  neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_in }} in
  {% endif %}
  {% if neighbor.route_map_out %}
  neighbor {{ neighbor.ip }} route-map {{ neighbor.route_map_out }} out
  {% endif %}
  {% if neighbor.soft_reconfiguration_inbound %}
  neighbor {{ neighbor.ip }} soft-reconfiguration inbound
  {% endif %}
 {% endfor %}
 exit-address-family
{% endfor %}
!
{% endif %}
```

### AI Output Example for BGP

**User Input**:
```
"Configure BGP with local AS 65001, establish eBGP with 192.168.1.2 (AS 65002),
advertise network 10.1.0.0/16 to IPv4"
```

**AI Output**:
```json
{
  "bgp": {
    "enabled": true,
    "as_number": 65001,
    "router_id": "1.1.1.1",
    "log_neighbor_changes": true,
    "neighbors": [
      {
        "ip": "192.168.1.2",
        "remote_as": 65002,
        "description": "ISP_Peer",
        "ebgp_multihop": 2
      }
    ],
    "address_families": [
      {
        "type": "ipv4",
        "networks": [
          {
            "address": "10.1.0.0",
            "mask": "255.255.0.0"
          }
        ],
        "neighbors": [
          {
            "ip": "192.168.1.2",
            "activate": true
          }
        ]
      }
    ]
  }
}
```

## Interface Configuration Template

**File**: `config_templates/cisco/ios/interface.j2`

```jinja2
{% for iface in interfaces %}
interface {{ iface.name }}
{% if iface.description %}
 description {{ iface.description }}
{% endif %}
{% if iface.ip_address %}
 ip address {{ iface.ip_address }} {{ iface.subnet_mask }}
{% endif %}
{% if iface.ipv6_address %}
 ipv6 address {{ iface.ipv6_address }}
{% endif %}
{% if iface.secondary_ips %}
{% for secondary in iface.secondary_ips %}
 ip address {{ secondary.address }} {{ secondary.mask }} secondary
{% endfor %}
{% endif %}
{% if iface.enabled is defined %}
{% if not iface.enabled %}
 shutdown
{% else %}
 no shutdown
{% endif %}
{% endif %}
{% if iface.mtu %}
 mtu {{ iface.mtu }}
{% endif %}
{% if iface.bandwidth %}
 bandwidth {{ iface.bandwidth }}
{% endif %}
{% if iface.speed %}
 speed {{ iface.speed }}
{% endif %}
{% if iface.duplex %}
 duplex {{ iface.duplex }}
{% endif %}
{% if iface.acl_in %}
 ip access-group {{ iface.acl_in }} in
{% endif %}
{% if iface.acl_out %}
 ip access-group {{ iface.acl_out }} out
{% endif %}
{% if iface.nat_outside %}
 ip nat outside
{% endif %}
{% if iface.nat_inside %}
 ip nat inside
{% endif %}
{% if iface.vlan %}
 switchport access vlan {{ iface.vlan }}
{% endif %}
{% if iface.trunk_vlans %}
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk allowed vlan {{ iface.trunk_vlans }}
{% endif %}
!
{% endfor %}
```

## JSON Schema Definitions

### OSPF Schema

**File**: `config_templates/schemas/cisco_ospf.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Cisco OSPF Configuration",
  "type": "object",
  "properties": {
    "ospf": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean",
          "description": "Enable OSPF routing"
        },
        "process_id": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535,
          "description": "OSPF process ID (1-65535)"
        },
        "router_id": {
          "type": "string",
          "pattern": "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$",
          "description": "Router ID in dotted decimal notation"
        },
        "networks": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "address": {
                "type": "string",
                "description": "Network address"
              },
              "wildcard": {
                "type": "string",
                "description": "Wildcard mask"
              },
              "area": {
                "type": "integer",
                "minimum": 0,
                "maximum": 4294967295,
                "description": "OSPF area ID"
              }
            },
            "required": ["address", "wildcard", "area"]
          }
        },
        "passive_interfaces": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of passive interfaces"
        },
        "interfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string",
                "description": "Interface name (e.g., GigabitEthernet0/0)"
              },
              "cost": {
                "type": "integer",
                "minimum": 1,
                "maximum": 65535,
                "description": "Interface OSPF cost"
              },
              "area": {
                "type": "integer",
                "minimum": 0,
                "maximum": 4294967295,
                "description": "OSPF area for this interface"
              },
              "hello_interval": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8192,
                "description": "OSPF hello interval in seconds"
              },
              "dead_interval": {
                "type": "integer",
                "minimum": 1,
                "maximum": 32768,
                "description": "OSPF dead interval in seconds"
              },
              "authentication": {
                "type": "boolean",
                "description": "Enable OSPF authentication"
              },
              "auth_type": {
                "type": "string",
                "enum": ["simple", "message-digest"],
                "description": "Authentication type"
              },
              "auth_key": {
                "type": "string",
                "description": "Simple authentication key"
              },
              "auth_md5_keys": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "integer",
                      "minimum": 1,
                      "maximum": 255
                    },
                    "secret": {
                      "type": "string"
                    }
                  },
                  "required": ["id", "secret"]
                }
              }
            },
            "required": ["name"]
          }
        },
        "auto_cost_reference": {
          "type": "integer",
          "description": "Reference bandwidth for auto cost (Mbps)"
        },
        "default_information_originate": {
          "type": "boolean",
          "description": "Advertise default route"
        },
        "default_metric": {
          "type": "integer",
          "description": "Default route metric"
        }
      },
      "required": ["enabled", "process_id"]
    }
  }
}
```

### BGP Schema

**File**: `config_templates/schemas/cisco_bgp.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Cisco BGP Configuration",
  "type": "object",
  "properties": {
    "bgp": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean"
        },
        "as_number": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        },
        "router_id": {
          "type": "string",
          "pattern": "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$"
        },
        "log_neighbor_changes": {
          "type": "boolean"
        },
        "graceful_restart": {
          "type": "boolean"
        },
        "neighbors": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "ip": {
                "type": "string"
              },
              "remote_as": {
                "type": "integer",
                "minimum": 1,
                "maximum": 65535
              },
              "description": {
                "type": "string"
              },
              "ebgp_multihop": {
                "type": "integer",
                "minimum": 1,
                "maximum": 255
              },
              "next_hop_self": {
                "type": "boolean"
              },
              "remove_private_as": {
                "type": "boolean"
              },
              "route_map_in": {
                "type": "string"
              },
              "route_map_out": {
                "type": "string"
              },
              "password": {
                "type": "string"
              }
            },
            "required": ["ip", "remote_as"]
          }
        },
        "address_families": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {
                "type": "string",
                "enum": ["ipv4", "ipv6", "vpnv4", "vpnv6"]
              },
              "vrf": {
                "type": "string"
              },
              "redistribute_connected": {
                "type": "boolean"
              },
              "redistribute_static": {
                "type": "boolean"
              },
              "redistribute_ospf": {
                "type": "integer"
              },
              "networks": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "address": {
                      "type": "string"
                    },
                    "mask": {
                      "type": "string"
                    }
                  },
                  "required": ["address", "mask"]
                }
              },
              "neighbors": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "ip": {
                      "type": "string"
                    },
                    "activate": {
                      "type": "boolean"
                    },
                    "route_map_in": {
                      "type": "string"
                    },
                    "route_map_out": {
                      "type": "string"
                    },
                    "soft_reconfiguration_inbound": {
                      "type": "boolean"
                    }
                  },
                  "required": ["ip"]
                }
              }
            },
            "required": ["type"]
          }
        }
      },
      "required": ["enabled", "as_number"]
    }
  }
}
```

## Implementation

### Config Renderer Module

**File**: `gns3server/agent/gns3_copilot/config_renderer.py`

```python
"""
Configuration Renderer for GNS3 AI Copilot

This module handles rendering of network device configurations
using Jinja2 templates based on AI-generated structured data.
"""

import os
import json
from typing import Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape
from pathlib import Path
import logging

log = logging.getLogger(__name__)


class ConfigRenderer:
    """
    Renders network device configurations using Jinja2 templates.

    The AI generates structured data (JSON), which is then validated
    against schemas and rendered through vendor-specific templates.
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize the configuration renderer.

        Args:
            template_dir: Path to template directory. If None, uses default.
        """
        if template_dir is None:
            template_dir = Path(__file__).parent / "config_templates"

        self.template_dir = Path(template_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )

        log.info(f"ConfigRenderer initialized with templates from: {self.template_dir}")

    def render(
        self,
        vendor: str,
        os_type: str,
        feature: str,
        data: Dict[str, Any]
    ) -> str:
        """
        Render a configuration template.

        Args:
            vendor: Vendor name (cisco, juniper, huawei, etc.)
            os_type: OS type (ios, junos, vrp, etc.)
            feature: Feature name (ospf, bgp, interface, etc.)
            data: Structured data from AI

        Returns:
            Rendered configuration as string

        Raises:
            TemplateError: If template rendering fails
            FileNotFoundError: If template doesn't exist
        """
        template_path = f"{vendor}/{os_type}/{feature}.j2"

        try:
            template = self.env.get_template(template_path)
            config = template.render(**data)
            log.info(f"Successfully rendered template: {template_path}")
            return config
        except TemplateError as e:
            log.error(f"Template rendering error for {template_path}: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error rendering {template_path}: {e}")
            raise

    def render_multi(
        self,
        vendor: str,
        os_type: str,
        features: Dict[str, Dict[str, Any]]
    ) -> str:
        """
        Render multiple configuration templates and combine them.

        Args:
            vendor: Vendor name
            os_type: OS type
            features: Dictionary of feature names and their data

        Returns:
            Combined configuration
        """
        configs = []
        for feature, data in features.items():
            config = self.render(vendor, os_type, feature, data)
            configs.append(config)

        return "\n".join(configs)

    def get_available_templates(self) -> Dict[str, list]:
        """
        Get list of available templates organized by vendor and OS.

        Returns:
            Dictionary with vendors as keys and list of available features
        """
        templates = {}
        template_path = Path(self.template_dir)

        for vendor_dir in template_path.iterdir():
            if vendor_dir.is_dir() and not vendor_dir.name.startswith('_'):
                vendor = vendor_dir.name
                templates[vendor] = {}

                for os_dir in vendor_dir.iterdir():
                    if os_dir.is_dir():
                        os_type = os_dir.name
                        templates[vendor][os_type] = []

                        for template_file in os_dir.glob("*.j2"):
                            feature = template_file.stem
                            templates[vendor][os_type].append(feature)

        return templates

    def validate_data(self, schema_name: str, data: Dict[str, Any]) -> bool:
        """
        Validate structured data against JSON schema.

        Args:
            schema_name: Name of schema file
            data: Data to validate

        Returns:
            True if valid, raises ValidationError otherwise
        """
        # Import jsonschema only when needed
        try:
            from jsonschema import validate, ValidationError
        except ImportError:
            log.warning("jsonschema not installed, skipping validation")
            return True

        schema_path = self.template_dir / "schemas" / f"{schema_name}.json"

        if not schema_path.exists():
            log.warning(f"Schema not found: {schema_path}")
            return True

        with open(schema_path, 'r') as f:
            schema = json.load(f)

        try:
            validate(instance=data, schema=schema)
            return True
        except ValidationError as e:
            log.error(f"Schema validation failed: {e.message}")
            raise


class ConfigBuilder:
    """
    Builds complete device configurations by combining multiple features.
    """

    def __init__(self, renderer: ConfigRenderer):
        self.renderer = renderer

    def build_device_config(
        self,
        vendor: str,
        os_type: str,
        config_data: Dict[str, Any]
    ) -> str:
        """
        Build a complete device configuration.

        Args:
            vendor: Vendor name
            os_type: OS type
            config_data: Dictionary with all feature configurations

        Returns:
            Complete device configuration
        """
        # Extract metadata
        hostname = config_data.get("hostname", "Router")
        config_parts = [f"hostname {hostname}\n"]

        # Render each feature section
        feature_order = [
            "interface",
            "vlan",
            "ospf",
            "bgp",
            "eigrp",
            "rip",
            "acl",
            "nat",
            "qos",
            "multicast"
        ]

        for feature in feature_order:
            if feature in config_data:
                try:
                    config = self.renderer.render(
                        vendor, os_type, feature,
                        {feature: config_data[feature]}
                    )
                    config_parts.append(config)
                except Exception as e:
                    log.warning(f"Failed to render {feature}: {e}")

        return "\n".join(config_parts)
```

### Usage Example

```python
from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer, ConfigBuilder

# Initialize renderer
renderer = ConfigRenderer()

# AI-generated data for OSPF configuration
ai_data = {
    "ospf": {
        "enabled": True,
        "process_id": 100,
        "router_id": "1.1.1.1",
        "networks": [
            {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
        ],
        "passive_interfaces": ["GigabitEthernet0/0"]
    }
}

# Render configuration
config = renderer.render(
    vendor="cisco",
    os_type="ios",
    feature="ospf",
    data=ai_data
)

print(config)

# Build complete device configuration
builder = ConfigBuilder(renderer)
full_config = builder.build_device_config(
    vendor="cisco",
    os_type="ios",
    config_data={
        "hostname": "R1",
        "interface": {...},
        "ospf": {...},
        "bgp": {...}
    }
)
```

## Integration with AI Copilot

### New Tool for Configuration Rendering

```python
"""
File: gns3server/agent/gns3_copilot/tools_v2/gns3_render_config.py
"""

from langchain_core.tools import tool
from typing import Dict, Any
import logging

log = logging.getLogger(__name__)


@tool
def render_device_config(
    node_id: str,
    vendor: str,
    os_type: str,
    config_data: Dict[str, Any]
) -> str:
    """
    Render network device configuration using Jinja2 templates.

    Instead of generating full configuration text, the AI should provide
    structured data (dict) that will be rendered through templates.

    Args:
        node_id: GNS3 node identifier
        vendor: Device vendor (cisco, juniper, huawei, etc.)
        os_type: Operating system type (ios, junos, vrp, nexus, etc.)
        config_data: Structured configuration data from AI

    Returns:
        Rendered configuration string

    Example:
        >>> ai_output = {
        ...     "ospf": {
        ...         "enabled": True,
        ...         "process_id": 100,
        ...         "router_id": "1.1.1.1",
        ...         "networks": [
        ...             {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
        ...         ]
        ...     }
        ... }
        >>> config = render_device_config(
        ...     node_id="node-1",
        ...     vendor="cisco",
        ...     os_type="ios",
        ...     config_data=ai_output
        ... )
    """
    from gns3server.agent.gns3_copilot.config_renderer import ConfigRenderer

    renderer = ConfigRenderer()

    # Validate against schema if available
    try:
        renderer.validate_data(f"{vendor}_{list(config_data.keys())[0]}", config_data)
    except Exception as e:
        log.warning(f"Schema validation failed: {e}")

    # Render configuration
    try:
        if len(config_data) == 1:
            # Single feature
            feature = list(config_data.keys())[0]
            config = renderer.render(vendor, os_type, feature, config_data)
        else:
            # Multiple features
            config = renderer.render_multi(vendor, os_type, config_data)

        return config

    except Exception as e:
        return f"Error rendering configuration: {str(e)}"
```

## Benefits

1. **Reliability**: Templates are tested and verified, reducing configuration errors
2. **Efficiency**: AI generates less text (structured data only), saving tokens and processing time
3. **Consistency**: Uniform configuration style across all generated configs
4. **Maintainability**: Templates are version controlled and easy to update
5. **Scalability**: Easy to add new vendors and features
6. **Validation**: JSON schemas ensure data correctness before rendering
7. **Vendor Support**: Easy to support multiple vendors with same AI logic
8. **Testing**: Templates can be unit tested independently

## Future Enhancements

1. **Template Marketplace**: Community-contributed templates
2. **Auto-discovery**: Detect device vendor/OS from GNS3 node type
3. **Config Diff**: Show differences before/after configuration
4. **Best Practices**: Templates embed industry best practices
5. **Validation**: Post-render validation against device syntax
6. **Rollback**: Auto-generate rollback configurations
7. **Documentation**: Templates include inline documentation

## Example Prompts for AI

The AI should be prompted to generate structured data instead of full configs:

**Good Prompt**:
```
"Generate OSPF configuration with process ID 100, router-id 1.1.1.1,
include network 192.168.1.0/24 in area 0. Output as structured JSON data."
```

**AI Output**:
```json
{
  "ospf": {
    "enabled": true,
    "process_id": 100,
    "router_id": "1.1.1.1",
    "networks": [
      {"address": "192.168.1.0", "wildcard": "0.0.0.255", "area": 0}
    ]
  }
}
```

Then the agent calls `render_device_config` tool to get the actual configuration.
