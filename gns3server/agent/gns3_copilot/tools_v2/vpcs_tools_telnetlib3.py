"""
Multi-device VPCS command execution tool using telnetlib3 with threading.
Supports concurrent execution of multiple command groups across multiple VPCS devices.
"""

import json
import logging
import os
import re
import threading
from time import sleep
from typing import Any

from langchain.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from telnetlib3 import Telnet

from gns3_copilot.gns3_client import get_gns3_server_host
from gns3_copilot.utils import get_device_ports_from_topology

logger = logging.getLogger(__name__)


class VPCSMultiCommands(BaseTool):
    """
    A tool for VPCS (Virtual PC Simulator) devices to view PC configurations and test connectivity.

    **VPCS-SPECIFIC TOOL** - This tool ONLY works with VPCS virtual PC devices.

    **IMPORTANT DISTINCTION:**
    Unlike network devices (routers/switches), VPCS devices are lightweight virtual PCs that
    simulate basic network functionality. Commands like 'ip' are basic PC IP configuration,
    NOT network device configuration.

    **Allowed VPCS Commands:**
    - IP configuration: ip <address>/<mask> <gateway> (Basic PC IP setup)
    - View configuration: ip, show ip
    - Connectivity testing: ping <destination>
    - Display ARP: arp
    - Display version: version
    - Save/Load: save, load

    **Usage Context:**
    This tool is used in lab environments where students need to configure virtual PC IP
    addresses and test network connectivity. It does NOT configure network infrastructure.
    """

    name: str = "execute_vpcs_multi_commands"
    description: str = """
    **VPCS VIRTUAL PC TOOL** - Configure and test Virtual PC Simulator devices.

    This tool ONLY works with VPCS (Virtual PC Simulator) devices, NOT routers/switches.

    **IMPORTANT: VPCS vs Network Devices**
    - VPCS = Lightweight virtual PCs for lab testing (NOT network infrastructure)
    - 'ip' command on VPCS = Basic PC IP configuration (like 'ipconfig' on Windows)
    - This is NOT the same as configuring router interfaces or routing protocols

    **When to Use This Tool:**
    - Configure IP addresses on virtual PCs: ip 10.10.0.12/24 10.10.0.254
    - Test connectivity from PCs: ping 10.10.0.254
    - View PC IP configuration: ip, show ip
    - Display ARP table: arp
    - Check PC version: version

    **Input Format:**
        {
            "project_id": "f32ebf3d-ef8c-4910-b0d6-566ed828cd24",
            "device_configs": [
                {
                    "device_name": "PC1",
                    "commands": ["ip", "ping 10.10.0.254"]
                },
                {
                    "device_name": "PC2",
                    "commands": ["show ip"]
                }
            ]
        }

    **Returns:** PC command outputs for IP configuration and connectivity testing.

    **Note:** For network devices (Cisco/Huawei routers), use execute_multiple_device_commands instead.
    """

    def _connect_and_execute_commands(
        self,
        device_name: str,
        commands: list[str],
        results_list: list[Any],
        index: int,
        device_ports: dict[str, Any],
        gns3_host: str,
    ) -> None:
        """
        Internal method to connect to VPCS device and execute commands.

        VPCS devices are lightweight virtual PCs used in GNS3 labs for testing
        network connectivity and basic IP configuration.
        """

        logger.info(
            "Starting connection for device '%s' with %d commands",
            device_name,
            len(commands),
        )

        # Check if device has port information
        if device_name not in device_ports:
            logger.warning(
                "Device '%s' not found in topology or missing console port", device_name
            )
            results_list[index] = {
                "device_name": device_name,
                "status": "error",
                "output": f"Device '{device_name}' not found in topology or missing console port",
                "commands": commands,
            }
            return

        port = device_ports[device_name]["port"]
        host = gns3_host

        logger.info("Connecting to device '%s' at %s:%d", device_name, host, port)

        tn = Telnet()
        try:
            tn.open(host=host, port=port, timeout=30)
            logger.info(
                "Successfully connected to device '%s' at %s:%d",
                device_name,
                host,
                port,
            )

            # Initialize connection
            tn.write(b"\n")
            sleep(0.5)
            tn.write(b"\n")
            sleep(0.5)
            tn.write(b"\n")
            sleep(0.5)
            tn.write(b"\n")
            sleep(0.5)
            tn.expect([rb"PC\d+>"])
            logger.info("Connection initialized for device '%s'", device_name)

            # Execute all commands and merge output
            combined_output = ""
            for i, command in enumerate(commands):
                logger.info(
                    "Executing command %d/%d on device '%s': %s",
                    i + 1,
                    len(commands),
                    device_name,
                    command,
                )
                tn.write(command.encode(encoding="ascii") + b"\n")
                sleep(5)
                tn.expect([rb"PC\d+>"])
                output = tn.read_very_eager().decode("utf-8")
                combined_output += output

            # Add result to list
            results_list[index] = {
                "device_name": device_name,
                "status": "success",
                "output": combined_output,
                "commands": commands,
            }
            logger.info(
                "Successfully executed all %d commands on device '%s'",
                len(commands),
                device_name,
            )

        except Exception as e:
            logger.error(
                "Error executing commands on device '%s': %s", device_name, str(e)
            )
            results_list[index] = {
                "device_name": device_name,
                "status": "error",
                "output": str(e),
                "commands": commands,
            }
        finally:
            tn.close()
            logger.debug("Connection closed for device '%s'", device_name)

    def _validate_project_id(self, project_id: str) -> bool:
        """
        Validate project_id format (UUID).

        Args:
            project_id: The project ID to validate

        Returns:
            True if valid UUID format, False otherwise
        """
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        is_valid = bool(re.match(uuid_pattern, project_id, re.IGNORECASE))
        if not is_valid:
            logger.warning("project_id '%s' is not a valid UUID format", project_id)
        return is_valid

    def _validate_tool_input(
        self, tool_input: str | bytes | list[Any] | dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Validate device command input and extract project_id and device_configs.

        Args:
            tool_input: The input received from the LangChain/LangGraph tool call.

        Returns:
            Tuple containing (device_configs_list, project_id) or (error_list, "")
        """

        parsed_input = None

        # Compatibility Check and Parsing ---
        # Check if the input is a string (or bytes) which needs to be parsed.
        if isinstance(tool_input, (str, bytes, bytearray)):
            # Handle models that return a raw JSON string.
            try:
                parsed_input = json.loads(tool_input)
                logger.info("Successfully parsed tool input from JSON string.")
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON string received as tool input: %s", e)
                return ([{"error": f"Invalid JSON input: {e}"}], "")
        else:
            # Handle standard models where the framework has already parsed the JSON.
            parsed_input = tool_input
            logger.info(
                "Using tool input directly as type: %s", type(parsed_input).__name__
            )

        # Validate input is a dictionary
        if not isinstance(parsed_input, dict):
            error_msg = (
                "Tool input must be a JSON object containing 'project_id' and 'device_configs', "
                f"but got {type(parsed_input).__name__}"
            )
            logger.error(error_msg)
            return ([{"error": error_msg}], "")

        # Extract and validate project_id
        project_id = parsed_input.get("project_id")
        if not project_id:
            error_msg = "Missing required field 'project_id' in input"
            logger.error(error_msg)
            return ([{"error": error_msg}], "")

        # Validate project_id format
        if not self._validate_project_id(project_id):
            error_msg = (
                f"Invalid project_id format: {project_id}. Expected UUID format."
            )
            logger.error(error_msg)
            return ([{"error": error_msg}], "")

        # Extract and validate device_configs
        device_configs = parsed_input.get("device_configs")
        if device_configs is None:
            error_msg = "Missing required field 'device_configs' in input"
            logger.error(error_msg)
            return ([{"error": error_msg}], "")

        # Validate device_configs is a list
        if not isinstance(device_configs, list):
            error_msg = f"'device_configs' must be a list, but got {type(device_configs).__name__}"
            logger.error(error_msg)
            return ([{"error": error_msg}], "")

        # Handle empty list
        if not device_configs:
            logger.warning("Device configs list is empty.")
            return [], ""

        # Validate each item in device_configs
        for i, item in enumerate(device_configs):
            if not isinstance(item, dict):
                error_msg = (
                    f"Item at index {i} must be a dictionary, got {type(item).__name__}"
                )
                logger.error(error_msg)
                return ([{"error": error_msg}], "")

            # Validate required fields in each device config
            if "device_name" not in item:
                error_msg = f"Item at index {i} missing required field 'device_name'"
                logger.error(error_msg)
                return ([{"error": error_msg}], "")

            if "commands" not in item:
                error_msg = f"Item at index {i} missing required field 'commands'"
                logger.error(error_msg)
                return ([{"error": error_msg}], "")

            if not isinstance(item["commands"], list):
                error_msg = (
                    f"'commands' in item at index {i} must be a list, "
                    f"but got {type(item['commands']).__name__}"
                )
                logger.error(error_msg)
                return ([{"error": error_msg}], "")

        logger.info(
            "Input validated successfully. project_id=%s, device_configs_count=%d",
            project_id,
            len(device_configs),
        )
        return device_configs, project_id

    def _run(
        self,
        tool_input: str,
        run_manager: CallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Main method to execute commands on multiple VPCS virtual PC devices concurrently.

        VPCS (Virtual PC Simulator) devices are lightweight virtual machines that simulate
        basic PC network functionality for lab testing. This is NOT network device configuration.

        Args:
            tool_input: JSON string containing project_id and device_configs with VPCS commands

        Returns:
            List of execution results for each VPCS device
        """

        # Log received input
        logger.info("Received input: %s", tool_input)

        # Validate tool input and extract project_id and device_configs
        device_configs, project_id = self._validate_tool_input(tool_input)

        # Check if validation returned an error
        if (
            isinstance(device_configs, list)
            and len(device_configs) > 0
            and "error" in device_configs[0]
        ):
            return device_configs

        # Extract all device names from input using set comprehension
        device_names = {config["device_name"] for config in device_configs}

        # Get device port mapping with project_id
        device_ports = get_device_ports_from_topology(
            list(device_names), project_id=project_id
        )
        logger.info(
            "Retrieved port mappings for %d devices: %s",
            len(device_ports),
            list(device_ports.keys()),
        )

        # Get GNS3 server host from connector factory
        gns3_host = get_gns3_server_host()
        logger.info("Using GNS3 server host: %s", gns3_host)

        # Initialize results list (pre-allocate space for concurrent writes)
        results: list[dict[str, Any]] = [{} for _ in range(len(device_configs))]
        threads = []

        # Create thread for each command group
        logger.info("Starting parallel execution for %d devices", len(device_configs))
        for i, cmd_group in enumerate(device_configs):
            device_name = cmd_group["device_name"]
            thread = threading.Thread(
                target=self._connect_and_execute_commands,
                args=(
                    cmd_group["device_name"],
                    cmd_group["commands"],
                    results,
                    i,
                    device_ports,
                    gns3_host,
                ),
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Count successful and failed executions
        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = sum(1 for r in results if r.get("status") == "error")

        logger.info(
            "Multi-device command execution completed. Total: %d, Success: %d, Error: %d",
            len(results),
            success_count,
            error_count,
        )

        return results


if __name__ == "__main__":
    # Example usage
    command_groups = json.dumps(
        {
            "project_id": "f32ebf3d-ef8c-4910-b0d6-566ed828cd24",
            "device_configs": [
                {
                    "device_name": "PC1",
                    "commands": [
                        "ip 10.10.0.12/24 10.10.0.254",
                        "ping 10.10.0.254",
                    ],
                },
                {
                    "device_name": "PC2",
                    "commands": ["ip 10.10.0.13/24 10.10.0.254"],
                },
                {
                    "device_name": "PC3",
                    "commands": [
                        "ip 10.20.0.22/24 10.20.0.254",
                        "ping 10.20.0.254",
                    ],
                },
                {
                    "device_name": "PC4",
                    "commands": ["ip 10.20.0.23/24 10.20.0.254"],
                },
            ],
        }
    )

    exe_cmd = VPCSMultiCommands()
    result = exe_cmd._run(tool_input=command_groups)
    print("Execution results:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
