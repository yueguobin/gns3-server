"""
This module uses Nornir + Netmiko to batch execute Linux commands on GNS3 topology devices
via Telnet console.
"""

import json
import logging
import os
import re
import time
from typing import Any

from langchain.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from nornir import InitNornir
from nornir.core import Nornir
from nornir.core.task import AggregatedResult, Result, Task
from nornir_netmiko.tasks import netmiko_send_command

from gns3_copilot.utils import get_device_ports_from_topology

# config log
logger = logging.getLogger(__name__)


# Local Nornir configuration functions for Linux Telnet devices
def _get_nornir_defaults() -> dict[str, Any]:
    """Get Nornir default configuration for Linux Telnet."""
    return {"data": {"location": "gns3"}}


def _get_nornir_groups_config() -> dict[str, dict[str, Any]]:
    """Get Nornir groups configuration for Linux Telnet devices."""
    return {
        "linux_telnet": {
            "platform": "linux",
            "hostname": os.getenv("GNS3_SERVER_HOST", "127.0.0.1"),
            "timeout": 120,
            "username": os.getenv("LINUX_TELNET_USERNAME", ""),
            "password": os.getenv("LINUX_TELNET_PASSWORD", ""),
            "connection_options": {
                "netmiko": {
                    "platform": "linux",
                    "extras": {
                        "device_type": "generic_telnet",
                        "global_delay_factor": 3,
                        "timeout": 120,
                        "fast_cli": False,
                    },
                }
            },
        },
    }


def _get_nornir_group(group_name: str = "linux_telnet") -> dict[str, Any]:
    """Get Nornir group configuration for a specific group."""
    all_groups = _get_nornir_groups_config()
    return all_groups.get(group_name, {})


class LinuxTelnetBatchTool(BaseTool):
    """
    A tool to execute commands on Linux devices via Telnet console in GNS3 labs.

    **CRITICAL: NON-INTERACTIVE ONLY**

    This tool ONLY supports non-interactive commands that exit immediately.
    Interactive commands will cause the tool to hang and fail.

    **Strictly Prohibited (Interactive Commands):**
    - Text editors: vi, vim, nano, emacs
    - Interactive viewers: less, more
    - Continuous monitors: top, htop, iotop (use top -b -n 1 instead)
    - Interactive shells: bash, sh, python, REPL environments
    - Commands requiring user input: passwd, chsh, interactive installers
    - Any command with pagination that waits for user input

    **Required: Non-Interactive Alternatives**
    - INSTEAD OF: top → USE: top -b -n 1 (batch mode, single iteration)
    - INSTEAD OF: vi file.txt → USE: cat file.txt or head file.txt
    - INSTEAD OF: less file.txt → USE: cat file.txt or head -n 50 file.txt
    - INSTEAD OF: ping host → USE: ping -c 4 host (limited count)
    - INSTEAD OF: tail → USE: tail -n 20 (explicit line count)

    **Allowed Command Types:**
    - System info: uname -a, hostnamectl, cat /etc/os-release
    - Network diagnostics: ip a, ip route, ping -c 4, traceroute -n
    - Process listing: ps aux, ps aux --sort=-%mem | head -20
    - Service status: systemctl status ssh --no-pager
    - Log viewing: journalctl -u ssh --no-pager -n 50, cat /var/log/syslog | tail -50
    - File operations: ls -la, cat, head, tail (with explicit limits), find, grep
    """

    name: str = "linux_telnet_batch_commands"
    description: str = """
    **LINUX DIAGNOSTIC TOOL** - Execute non-interactive commands on Linux devices via Telnet.

    **CRITICAL: NON-INTERACTIVE COMMANDS ONLY**

    This tool will HANG and FAIL if you use interactive commands. All commands MUST exit immediately without user input.

    **STRICTLY FORBIDDEN:**
    ❌ Text editors: vi, vim, nano, emacs
    ❌ Interactive pagers: less, more
    ❌ Continuous monitors: top, htop, iotop (unless using batch mode)
    ❌ Interactive shells: bash, sh, python, REPL
    ❌ User input commands: passwd, chsh, SSH with password prompts
    ❌ Any command that waits for keyboard input or pagination

    **NON-INTERACTIVE ALTERNATIVES (USE THESE):**
    ✅ System info: uname -a, hostnamectl, cat /etc/os-release
    ✅ Network: ip a, ip route, ping -c 4 <host>, traceroute -n
    ✅ Processes: ps aux, ps aux --sort=-%mem | head -20
    ✅ Services: systemctl status <service> --no-pager
    ✅ Logs: journalctl -u <unit> --no-pager -n 50, tail -50 /var/log/syslog
    ✅ Files: cat, head -n 50, tail -n 20, grep, find
    ✅ Batch monitoring: top -b -n 1 (NOT interactive top)

    **Input Format:**
        {
            "project_id": "f32ebf3d-ef8c-4910-b0d6-566ed828cd24",
            "device_configs": [
                {
                    "device_name": "debian01",
                    "commands": ["uname -a", "ip a", "ping -c 4 8.8.8.8"]
                },
                {
                    "device_name": "ubuntu01",
                    "commands": ["hostnamectl", "systemctl status ssh --no-pager"]
                }
            ]
        }

    **Important Notes:**
    - ALL commands must use --no-pager flag when available
    - Add explicit limits: head -n 50, tail -n 20, ping -c 4
    - For testing: Execute server/client commands on one device at a time, NOT simultaneously
    - This tool is for diagnostics and information gathering
    """

    def _run(
        self,
        tool_input: str | bytes | list[Any] | dict[str, Any],
        run_manager: CallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Execute non-interactive Linux commands on multiple devices via Telnet.

        **CRITICAL:** All commands MUST be non-interactive and exit immediately.
        Interactive commands (vi, top, less, etc.) will cause execution to hang.

        Args:
            tool_input: JSON string containing project_id and device_configs with commands

        Returns:
            List of execution results for each Linux device
        """
        # Log received input
        logger.info("Received input: %s", tool_input)

        # Validate input first (before checking credentials)
        device_configs_list, project_id = self._validate_tool_input(tool_input)
        if (
            isinstance(device_configs_list, list)
            and len(device_configs_list) > 0
            and "error" in device_configs_list[0]
        ):
            return device_configs_list

        # Check credentials only for valid inputs
        linux_username = os.getenv("LINUX_TELNET_USERNAME", "")
        linux_password = os.getenv("LINUX_TELNET_PASSWORD", "")

        if not linux_username or not linux_password:
            user_message = (
                "Sorry, I can't proceed just yet.\n\n"
                "You haven't configured the Linux login credentials (username and password) yet.\n"
                "Please go to the **Settings** page and fill in the Linux username and password under the login credentials section.\n\n"
                "Once you've saved them, just come back and say anything (like 'Done' or 'Configured'), "
                "and I'll immediately continue with the task!\n\n"
                "Need help finding the settings page? Let me know — happy to guide you!"
            )
            logger.warning(
                "Linux login credentials not configured — user prompted to set them up"
            )
            return [
                {
                    "error": user_message,
                    "action_required": "configure_linux_credentials",
                    "user_message": user_message,  # optional, if your frontend uses a separate field
                }
            ]

        # Create a mapping of device names to their display commands
        device_configs_map = self._configs_map(device_configs_list)

        # Prepare device hosts data
        try:
            hosts_data = self._prepare_device_hosts_data(
                device_configs_list, project_id
            )
        except ValueError as e:
            logger.error("Failed to prepare device hosts data: %s", e)
            return [{"error": str(e)}]

        # Initialize Nornir
        try:
            dynamic_nr = self._initialize_nornir(hosts_data)
        except ValueError as e:
            logger.error("Failed to initialize Nornir: %s", e)
            return [{"error": str(e)}]

        results = []

        # Execute login first, then commands
        try:
            # Step 1: Execute login for all devices
            login_result = dynamic_nr.run(task=self._linux_telnet_login)

            # Step 2: Check login results and execute commands for successful logins
            successful_logins = []
            failed_logins = []

            for device_name, result in login_result.items():
                if result.failed:
                    failed_logins.append(device_name)
                    logger.error(
                        "Device %s login failed: %s", device_name, result.result
                    )
                else:
                    successful_logins.append(device_name)
                    logger.info(
                        "Device %s login successful: %s", device_name, result.result
                    )

            task_result: AggregatedResult | dict[str, Any]

            # Step 3: Execute commands only for devices with successful login
            if successful_logins:
                # Filter device_configs_map to only include successfully logged in devices
                filtered_device_configs_map = {
                    device_name: commands
                    for device_name, commands in device_configs_map.items()
                    if device_name in successful_logins
                }

                task_result = dynamic_nr.run(
                    task=self._run_all_device_configs_with_single_retry,
                    device_configs_map=filtered_device_configs_map,
                )
            else:
                task_result = AggregatedResult("empty_command_execution")

            # Step 4: Process results for all devices
            results = self._process_task_results(
                device_configs_list, hosts_data, task_result, login_result
            )

        except Exception as e:
            # Overall execution failed
            logger.error("Error executing display on all devices: %s", e)
            return [{"error": f"Execution error: {str(e)}"}]

        logger.info(
            "Multiple device display execution completed. Results: %s",
            json.dumps(results, indent=2, ensure_ascii=False),
        )

        return results

    def _linux_telnet_login(self, task: Task) -> Result:
        """
        Smart Linux Telnet login: detect login status and only login when needed.

        This method handles authentication for Linux Telnet sessions in GNS3 labs.
        It detects whether a device is already logged in before attempting authentication.
        """
        try:
            net_connect = task.host.get_connection("netmiko", task.nornir.config)

            # Clear the buffer + press Enter several times to wake up the device.
            net_connect.clear_buffer()
            time.sleep(0.3)
            net_connect.write_channel("\n\n")

            # Read the device output (wait up to 10 seconds)
            output = net_connect.read_channel_timing(read_timeout=10)
            logger.info("Device %s initial output: %s", task.host.name, output)

            # Check if output contains "login:" prompt
            if re.search(r"(?i)(^|\n).{0,60}(debian\s+)?login:\s*$", output):
                # Need to login, execute login process
                logger.info(
                    "Device %s requires login - detected login prompt", task.host.name
                )

                # Send username
                net_connect.write_channel(f"{task.host.username}\n")
                time.sleep(1)
                output = net_connect.read_until_prompt_or_pattern(
                    "Password:", read_timeout=10
                )

                # Send password
                net_connect.write_channel(f"{task.host.password}\n")
                time.sleep(1)
                output += net_connect.read_until_prompt_or_pattern(
                    r"[$#]", read_timeout=10
                )

                logger.info("Device %s login successful", task.host.name)
                return Result(host=task.host, result="Login successful")

            # Already logged in, return directly
            logger.info(
                "Device %s already logged in - no login prompt detected", task.host.name
            )
            return Result(host=task.host, result="Already logged in")

        except Exception as e:
            logger.error("Device %s login failed: %s", task.host.name, e)
            return Result(host=task.host, result=f"Login failed: {str(e)}", failed=True)

    def _run_all_device_configs_with_single_retry(
        self, task: Task, device_configs_map: dict[str, list[str]]
    ) -> Result:
        """
        Execute non-interactive commands one-by-one on a single Linux device.

        **WARNING:** Each command MUST exit immediately without user input.
        If any command hangs waiting for input, the entire execution will fail.

        Optimized for generic_telnet with $ prompt and passwordless sudo.
        """
        device_name = task.host.name
        config_commands = device_configs_map.get(device_name, [])

        if not config_commands:
            return Result(host=task.host, result="No display commands to execute")

        _outputs = {}
        for _cmd in config_commands:
            try:
                # Use timing mode + increased delay_factor to ensure stability with $ prompt
                # and passwordless sudo
                _result = task.run(
                    task=netmiko_send_command,
                    command_string=_cmd,
                    use_timing=True,
                    delay_factor=3,
                    max_loops=5000,
                )
                _outputs[_cmd] = _result.result
            except Exception as e:
                _outputs[_cmd] = f"Command execution failed: {str(e)}"

        return Result(host=task.host, result=_outputs)

    def _validate_tool_input(
        self, tool_input: str | bytes | list[Any] | dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Validate device display command input, handling both new and legacy input formats.
        Supports new format with project_id and device_configs, as well as legacy array format.

        Args:
            tool_input: The input received from the LangChain/LangGraph tool call.

        Returns:
            Tuple containing (device_configs_list, project_id) or (error_list, None)
        """

        parsed_input = None

        # Compatibility Check and Parsing ---
        # Check if the input is a string (or bytes) which needs to be parsed.
        if isinstance(tool_input, (str, bytes, bytearray)):
            # Handle models (like potentially DeepSeek) that return a raw JSON string.
            try:
                parsed_input = json.loads(tool_input)
                logger.info("Successfully parsed tool input from JSON string.")
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON string received as tool input: %s", e)
                return ([{"error": f"Invalid JSON string input from model: {e}"}], None)
        else:
            # Handle standard models (like GPT/OpenAI) where the framework
            # has already parsed the JSON into a Python object (dict or list).
            parsed_input = tool_input
            logger.info(
                "Using tool input directly as type: %s", type(parsed_input).__name__
            )

        # Handle new format: {"project_id": "...", "device_configs": [...]}
        if isinstance(parsed_input, dict):
            project_id = parsed_input.get("project_id")
            device_configs = parsed_input.get("device_configs")

            # Validate project_id
            if not project_id:
                error_msg = "Missing required 'project_id' field in input"
                logger.error(error_msg)
                return ([{"error": error_msg}], None)

            if not self._validate_project_id(project_id):
                error_msg = (
                    f"Invalid project_id format: {project_id}. Expected UUID format."
                )
                logger.error(error_msg)
                return ([{"error": error_msg}], None)

            # Validate device_configs
            if not isinstance(device_configs, list):
                error_msg = "'device_configs' must be an array"
                logger.error(error_msg)
                return ([{"error": error_msg}], None)

            if not device_configs:
                logger.warning("Device configs list is empty.")
                return [], project_id

            return device_configs, project_id

        # Handle legacy format: [...]
        elif isinstance(parsed_input, list):
            logger.warning(
                "Using legacy input format without project_id. Please use new format with project_id."
            )
            return parsed_input, None

        else:
            error_msg = (
                "Tool input must be a JSON object with 'project_id' and 'device_configs' fields, "
                f"or a legacy JSON array, but got {type(parsed_input).__name__}"
            )
            logger.error(error_msg)
            return ([{"error": error_msg}], None)

    def _validate_project_id(self, project_id: str) -> bool:
        """
        Validate project_id format (UUID).

        Args:
            project_id: The project ID to validate

        Returns:
            True if valid UUID format, False otherwise
        """
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        return bool(re.match(uuid_pattern, project_id, re.IGNORECASE))

    def _configs_map(
        self, device_config_list: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """Create a mapping of device names to their display commands."""
        device_configs_map = {}
        for device_config in device_config_list:
            device_name = device_config["device_name"]
            config_commands = device_config["commands"]
            device_configs_map[device_name] = config_commands

        return device_configs_map

    def _prepare_device_hosts_data(
        self, device_config_list: list[dict[str, Any]], project_id: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """Prepare device hosts data from topology information."""
        # Extract device names list
        device_names = [
            device_config["device_name"] for device_config in device_config_list
        ]

        # Get device port information with project_id
        hosts_data = get_device_ports_from_topology(device_names, project_id)

        if not hosts_data:
            error_msg = (
                f"Failed to get device information from topology or no valid devices found. "
                f"Project ID: {project_id}, Devices: {device_names}"
            )
            raise ValueError(error_msg)

        # Force all devices to use linux_telnet group (compatible with generic_telnet)
        for _, _host_info in hosts_data.items():
            _host_info["groups"] = ["linux_telnet"]

        # Check for missing devices
        missing_devices = set(device_names) - set(hosts_data.keys())
        if missing_devices:
            logger.warning(
                "Some devices not found in topology (Project ID: %s): %s",
                project_id or "default",
                missing_devices,
            )

        return hosts_data

    def _initialize_nornir(self, hosts_data: dict[str, dict[str, Any]]) -> Nornir:
        """Initialize Nornir with the provided hosts data."""
        try:
            # Get latest environment configuration
            groups_data = _get_nornir_group("linux_telnet")
            defaults = _get_nornir_defaults()

            return InitNornir(
                inventory={
                    "plugin": "DictInventory",
                    "options": {
                        "hosts": hosts_data,
                        "groups": {"linux_telnet": groups_data},
                        "defaults": defaults,
                    },
                },
                runner={
                    "plugin": "threaded",
                    "options": {"num_workers": 10},
                },
                logging={"enabled": False},
            )
        except Exception as e:
            logger.error("Failed to initialize Nornir: %s", e)
            raise ValueError(f"Failed to initialize Nornir: {e}") from e

    def _process_task_results(
        self,
        device_configs_list: list[dict[str, Any]],
        hosts_data: dict[str, dict[str, Any]],
        task_result: AggregatedResult,
        login_result: AggregatedResult | None = None,
    ) -> list[dict[str, Any]]:
        """Process task results and format them for return."""
        results = []

        for device_config in device_configs_list:
            device_name = device_config["device_name"]
            config_commands = device_config["commands"]

            # Check if device is in topology
            if device_name not in hosts_data:
                device_result = {
                    "device_name": device_name,
                    "status": "failed",
                    "error": (
                        f"Device '{device_name}' not found in topology or missing console_port"
                    ),
                }
                results.append(device_result)
                continue

            # Check login result first
            if login_result and device_name in login_result:
                login_status = login_result[device_name]
                if login_status.failed:
                    device_result = {
                        "device_name": device_name,
                        "status": "failed",
                        "error": f"Login failed: {login_status.result}",
                        "login_status": login_status.result,
                    }
                    results.append(device_result)
                    continue

            # Check if device has execution results
            if device_name not in task_result:
                device_result = {
                    "device_name": device_name,
                    "status": "failed",
                    "error": (f"Device '{device_name}' not found in task results"),
                }
                results.append(device_result)
                continue

            # Process execution results
            multi_result = task_result[device_name]
            device_result = {"device_name": device_name}

            if multi_result[0].failed:
                # Execution failed
                device_result["status"] = "failed"
                device_result["error"] = (
                    f"Command execution failed: {multi_result[0].result}"
                )
                device_result["output"] = multi_result[0].result
            else:
                # Execution successful
                device_result["status"] = "success"
                device_result["output"] = multi_result[0].result
                device_result["config_commands"] = config_commands

            # Add login status if available
            if login_result and device_name in login_result:
                device_result["login_status"] = login_result[device_name].result

            results.append(device_result)

        return results


if __name__ == "__main__":
    # Example usage with new format
    device_commands = json.dumps(
        {
            "project_id": "f32ebf3d-ef8c-4910-b0d6-566ed828cd24",
            "device_configs": [
                {
                    "device_name": "Debian12.6-1",
                    "commands": [
                        "uname -a",
                        "hostnamectl || hostname",
                        "cat /etc/os-release",
                        "whoami && id",
                        "id",
                        "pwd",
                        "top -b -n 1 | head -20",
                        "ip neigh show | grep -v REACHABLE | grep -v PERMANENT",
                        "ping -c 3 114.114.114.114",
                        "ps aux --sort=-%mem | head -15",
                        "journalctl -u ssh --no-pager -n 20",
                        'find /etc -name "*.conf" | head -10',
                    ],
                },
                {
                    "device_name": "Debian12.6-2",
                    "commands": [
                        "uname -a",
                        "hostnamectl || hostname",
                        "cat /etc/os-release",
                        "whoami && id",
                        "id",
                        "pwd",
                        "top -b -n 1 | head -20",
                        "ip neigh show | grep -v REACHABLE | grep -v PERMANENT",
                        "ping -c 3 114.114.114.114",
                        "ps aux --sort=-%mem | head -15",
                        "journalctl -u ssh --no-pager -n 20",
                        'find /etc -name "*.conf" | head -10',
                    ],
                },
            ],
        }
    )

    exe_cmd = LinuxTelnetBatchTool()

    failed_count = 0

    for _i in range(0, 1):
        exe_results = exe_cmd._run(tool_input=device_commands)
        for exe_result in exe_results:
            for exe_result in exe_results:
                if exe_result.get("status") == "failed":
                    failed_count += 1

    print("Execution results:")
    print(json.dumps(exe_results, indent=2, ensure_ascii=False))
    print(f"Failed Count: {failed_count}")
