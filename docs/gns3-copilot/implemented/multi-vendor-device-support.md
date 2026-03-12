# Multi-Vendor Network Device Support

## Overview

GNS3-Copilot supports network devices from multiple vendors through Netmiko and Nornir integration. The system includes a custom Netmiko driver for Huawei devices in GNS3 emulation environments and supports dynamic device type detection.

## Supported Vendors

| Vendor | Platform | Device Type | Protocol | Status |
|--------|----------|-------------|----------|--------|
| **Cisco** | `cisco_ios` | `cisco_ios_telnet` | Telnet | ✅ Tested |
| **Huawei** | `huawei` | `huawei_telnet_ce` | Telnet | ✅ Tested (Custom Driver) |

## Custom Huawei Driver (`HuaweiTelnetCE`)

### Problem Statement

GNS3-emulated Huawei devices connect via console **without requiring authentication**. Standard Netmiko drivers attempt username/password authentication, causing connection timeouts.

**Standard Driver Behavior:**
```
Telnet Connection → Wait for username prompt → Send username → Wait for password → Send password → Access
                    ^ Times out after 20 seconds
```

**GNS3 Huawei Device:**
```
Telnet Connection → Direct access to command line (no login prompts)
                    <HUAWEI>
```

### Solution: Custom Driver Architecture

```
BaseConnection (Netmiko base class)
    ↓
CiscoBaseConnection (Cisco-style base class)
    ↓
HuaweiBase (Huawei device base class) ← Inherits VRP support
    ↓
HuaweiTelnetCE (Custom GNS3 driver) ← Overrides telnet_login only
```

**Why Inherit from HuaweiBase?**
- ✅ Built-in VRP (Versatile Routing Platform) command handling
- ✅ Huawei-specific configuration mode (`system-view`)
- ✅ Huawei prompt patterns (`<...>`, `[...]`)
- ✅ Huawei paging disable (`screen-length 0 temporary`)
- ✅ Minimal code changes - only override authentication

### HuaweiTelnetCE Implementation

#### Location
```
gns3server/agent/gns3_copilot/utils/custom_netmiko/huawei_ce.py
```

**Package Structure:**
```
custom_netmiko/
├── __init__.py              # Package initialization, auto-registers all drivers
├── huawei_ce.py             # Huawei CloudEngine custom driver
├── README.md                # Driver development guide
└── tests/                   # Unit tests
    ├── __init__.py
    └── test_huawei_ce.py    # Huawei CE driver tests
```

#### Key Features

1. **Skip Authentication**
   - Directly detect Huawei prompt patterns
   - No username/password prompts
   - Connection ready in < 1 second

2. **VRP Prompt Recognition**
   ```
   User view:    <HUAWEI>
   System view:  [HUAWEI]
   Interface:    [HUAWEI-GigabitEthernet0/0/1]
   ```

3. **Automatic Confirmation Handling**
   - Detects and responds to `[y/n]` prompts
   - Example: `return` command asks "Return to user view? [y/n]:"
   - Automatically sends `y` to confirm

4. **Proper Output Collection**
   - Uses Netmiko's `read_channel_timing()` for reliable output
   - Waits for command completion (2s no new data = done)
   - 30-second absolute timeout prevents hanging

5. **Auto-Commit Before Exit**
   - Automatically sends `commit` command before exiting config mode
   - Prevents "Uncommitted configurations [Y/N/C]" prompt
   - Ensures configuration changes are saved

#### Limitations

**Authentication Requirement:**
- The `huawei_telnet_ce` driver is designed for GNS3 devices **without authentication**
- If your Huawei device has been configured with a username/password:
  - **Option 1**: Use the standard `huawei_telnet` driver (requires username/password)
  - **Option 2**: Remove authentication from the device for GNS3 testing
- The driver does **not** currently auto-detect authentication requirements

**When to Use Each Driver:**

| Scenario | Use Driver | Requires Credentials? |
|----------|-----------|----------------------|
| GNS3 Huawei (fresh, no auth) | `huawei_telnet_ce` | ❌ No |
| GNS3 Huawei (configured with username/password) | `huawei_telnet` | ✅ Yes |
| Real Huawei hardware | `huawei_telnet` | ✅ Yes |

#### Method Overrides

**1. `telnet_login` - Skip Authentication**
```python
def telnet_login(self, pri_prompt_terminator=r"<\S+>|>\s*$",
                alt_prompt_terminator=r"\[\S+\]", ...) -> str:
    # Clear buffer
    self.read_channel()

    # Send returns until prompt detected
    for i in range(max_loops):
        self.write_channel(self.RETURN)
        output = self.read_channel()

        # Check for Huawei prompts
        if re.search(pri_prompt_terminator, output):
            return output  # Success!

    return output  # Best effort
```

**2. `send_config_set` - Configuration Commands**
```python
def send_config_set(self, config_commands, **kwargs) -> str:
    # Enter config mode
    output += self.config_mode(config_command="system-view")

    # Send all commands
    for cmd in config_commands:
        self.write_channel(f"{cmd}{self.RETURN}")
        time.sleep(delay_factor * 0.05)

    # Collect output using Netmiko standard method
    output += self.read_channel_timing(read_timeout=30, last_read=2.0)

    # Auto-commit before exit (prevents [Y/N/C] prompt)
    self.write_channel(f"commit{self.RETURN}")
    time.sleep(0.5 * self.global_delay_factor)
    output += self.read_channel()

    # Exit config mode
    output += self.exit_config_mode()

    return output
```

**3. `exit_config_mode` - Handle Confirmation**
```python
def exit_config_mode(self, exit_config="return", pattern=r"<\S+>|>\s*$") -> str:
    self.write_channel(f"return{self.RETURN}")

    # Look for confirmation prompt
    for _ in range(20):
        new_output = self.read_channel()

        if re.search(r"\[y/n\]", new_output):
            self.write_channel(f"y{self.RETURN}")  # Auto-confirm

        if re.search(pattern, new_output):
            return output  # Back to user view

    return output
```

### Device Type Registration

The custom driver must be registered with Netmiko's global mappings:

```python
def register_custom_device_type() -> None:
    import importlib
    sd = importlib.import_module("netmiko.ssh_dispatcher")

    # Register in CLASS_MAPPER (for ConnectHandler)
    sd.CLASS_MAPPER["huawei_telnet_ce"] = HuaweiTelnetCE
    sd.CLASS_MAPPER["huawei_ce"] = HuaweiTelnetCE

    # Register in CLASS_MAPPER_BASE (for base class definitions)
    sd.CLASS_MAPPER_BASE["huawei_telnet_ce"] = HuaweiTelnetCE
    sd.CLASS_MAPPER_BASE["huawei_ce"] = HuaweiTelnetCE

    # CRITICAL: Rebuild static lists
    sd.platforms = list(sd.CLASS_MAPPER.keys())
    sd.platforms.sort()
    sd.telnet_platforms = [x for x in sd.platforms if "telnet" in x]
```

**Important: Static List Problem**
- `ssh_dispatcher.platforms` is computed at module import time
- Modifying `CLASS_MAPPER` doesn't automatically update `platforms`
- Must manually rebuild the list after registration

**Auto-Registration**
```python
# Automatically runs on module import
try:
    register_custom_device_type()
except Exception as e:
    logger.warning(f"Failed to register custom device type: {e}")
```

## Dynamic Device Type Detection

### GNS3 Node Tags

Device type and platform are extracted from GNS3 node tags:

```
device_type:huawei_telnet_ce    → Netmiko device type (precise)
platform:huawei                  → Nornir platform (high-level)
```

**Tag Examples:**

| Vendor | Device Type Tag | Platform Tag |
|--------|----------------|--------------|
| Cisco IOS | `device_type:cisco_ios_telnet` | `platform:cisco_ios` |
| Huawei CE | `device_type:huawei_telnet_ce` | `platform:huawei` |

### Automatic Group Generation

Nornir groups are dynamically generated based on device type:

```python
# From get_gns3_device_port.py
if device_type and "_telnet" in device_type:
    group_name = f"{platform}_telnet"  # e.g., "huawei_telnet"
else:
    group_name = platform  # e.g., "cisco_ios"

hosts_data[device_name] = {
    "port": console_port,
    "groups": [group_name],
    "device_type": device_type,
    "platform": platform,
}
```

**Why Dynamic Groups?**
- Single Nornir instance can handle multiple vendors
- Each device gets correct connection parameters
- Vendor-specific commands work automatically

## Usage Examples

### Direct Netmiko Usage

**Huawei Device (Custom Driver):**
```python
from netmiko import ConnectHandler
from gns3server.agent.gns3_copilot.utils import custom_netmiko

# Custom driver auto-registers on import
device = {
    "device_type": "huawei_telnet_ce",
    "host": "127.0.0.1",
    "port": 5000,
    # No username/password needed!
}

with ConnectHandler(**device) as conn:
    # Execute display command
    output = conn.send_command("display version")

    # Execute configuration commands
    config = [
        "interface GE1/0/1",
        "description Uplink-to-Core",
        "undo shutdown"
    ]
    output = conn.send_config_set(config)
```

**Cisco IOS Device (Standard Driver):**
```python
from netmiko import ConnectHandler

device = {
    "device_type": "cisco_ios_telnet",
    "host": "127.0.0.1",
    "port": 5001,
    "username": "cisco",
    "password": "cisco",
}

with ConnectHandler(**device) as conn:
    output = conn.send_command("show version")
    config = ["interface GigabitEthernet0/0", "description Test"]
    output = conn.send_config_set(config)
```

### Nornir Multi-Vendor Automation

```python
from nornir import InitNornir
from gns3server.agent.gns3_copilot.utils import custom_netmiko

# Auto-register custom driver (happens automatically on import)
from gns3server.agent.gns3_copilot.utils.custom_netmiko import huawei_ce
huawei_ce.register_custom_device_type()

# Initialize Nornir with mixed-vendor inventory
inventory = {
    "options": {
        "hosts": {
            "huawei-sw1": {
                "hostname": "127.0.0.1",
                "port": 5001,
                "platform": "huawei",
                "device_type": "huawei_telnet_ce",
                "groups": ["huawei_telnet"]
            },
            "cisco-r1": {
                "hostname": "127.0.0.1",
                "port": 5002,
                "platform": "cisco_ios",
                "device_type": "cisco_ios_telnet",
                "groups": ["cisco_ios_telnet"]
            }
        },
        "groups": {
            "huawei_telnet": {
                "platform": "huawei",
                "device_type": "huawei_telnet_ce"
            },
            "cisco_ios_telnet": {
                "platform": "cisco_ios",
                "device_type": "cisco_ios_telnet"
            }
        }
    }
}

nr = InitNornir(inventory=inventory)

# Execute commands on all devices (multi-vendor)
result = nr.run(task=send_commands, commands=["display version"])

# Each device gets vendor-specific command handling
```

### GNS3 Copilot Tool Usage

```python
from gns3server.agent.gns3_copilot.tools_v2 import DisplayToolNornir

tool = DisplayToolNornir()
result = tool._run(json.dumps({
    "device_names": ["huawei-sw1", "cisco-r1"],
    "commands": ["display version", "show version"],
    "project_id": "project-uuid"
}))

# Returns:
# {
#   "huawei-sw1": {
#     "display version": "<Huawei output>",
#     "status": "success"
#   },
#   "cisco-r1": {
#     "show version": "<Cisco output>",
#     "status": "success"
#   }
# }
```

## Module Structure

```
gns3server/agent/gns3_copilot/
├── utils/
│   ├── custom_netmiko/            # Custom Netmiko drivers package
│   │   ├── __init__.py             # Package initialization
│   │   ├── huawei_ce.py            # Huawei CloudEngine driver
│   │   ├── README.md               # Driver development guide
│   │   └── tests/                  # Unit tests
│   │       ├── __init__.py
│   │       └── test_huawei_ce.py   # Huawei CE driver tests
│   └── get_gns3_device_port.py     # Device port extraction
├── tools_v2/
│   ├── display_tools_nornir.py     # Multi-vendor display commands
│   └── config_tools_nornir.py      # Multi-vendor config commands
```

## Unit Testing

### Test Coverage

```python
# test_netmiko_custom.py

class TestHuaweiTelnetCEDriver(unittest.TestCase):
    def test_device_type_registered(self):
        """Verify huawei_telnet_ce is in Netmiko CLASS_MAPPER"""
        from netmiko.ssh_dispatcher import CLASS_MAPPER
        self.assertIn("huawei_telnet_ce", CLASS_MAPPER)

    def test_inheritance_from_huawei_base(self):
        """Verify inherits from HuaweiBase"""
        from netmiko.huawei.huawei import HuaweiBase
        self.assertTrue(issubclass(HuaweiTelnetCE, HuaweiBase))

    def test_vrp_methods_available(self):
        """Verify VRP-specific methods are available"""
        methods = ["config_mode", "check_config_mode", "exit_config_mode"]
        for method in methods:
            self.assertTrue(hasattr(HuaweiTelnetCE, method))
```

**Running Tests:**
```bash
source venv/bin/activate
python gns3server/agent/gns3_copilot/utils/custom_netmiko/tests/test_huawei_ce.py
```

**Current Test Status:** ✅ All 9 tests passing

## Platform vs Device Type

### Key Concepts

**Platform (Nornir):**
- High-level vendor identifier
- Used for inventory grouping
- Examples: `huawei`, `cisco_ios`

**Device Type (Netmiko):**
- Precise driver type
- Includes protocol information
- Examples: `huawei_telnet_ce`, `cisco_ios_telnet`

### Mapping

| Platform | Device Type | Notes |
|----------|-------------|-------|
| `huawei` | `huawei_telnet_ce` | Custom driver for GNS3 |
| `cisco_ios` | `cisco_ios_telnet` | Standard Netmiko driver |

## Related Documentation

- [Custom Netmiko README](../../../../../gns3server/agent/gns3_copilot/utils/custom_netmiko/README.md) - Driver development guide
- [Node Control Tools](./node-control-tools.md) - Device lifecycle management
- [Command Security](./command-security.md) - Command filtering and validation
- [Chat API](./chat-api.md) - Session management and SSE

## References

- [Netmiko Documentation](https://ktbyers.github.io/netmiko/)
- [Netmiko PLATFORMS.md](https://github.com/ktbyers/netmiko/blob/master/PLATFORMS.md)
- [Nornir Documentation](https://nornir.readthedocs.io/)

---

_Implementation Date: 2026-03-12_

_Status: ✅ Implemented - Custom Huawei driver for GNS3 emulation, multi-vendor support with Cisco IOS and Huawei tested_

_Unit Tests: ✅ 9/9 passing_
