# SPDX-License-Identifier: GPL-3.0-or-later
#
# GNS3-Copilot - AI-powered Network Lab Assistant for GNS3
#
# This file is part of GNS3-Copilot project.
#
# GNS3-Copilot is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# GNS3-Copilot is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with GNS3-Copilot. If not, see <https://www.gnu.org/licenses/>.
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""
GNS3 Client Package

This package provides a Python interface for interacting with GNS3 servers.
Adapted from the upstream gns3fy project with modifications for compatibility
with langchain and reduced dependency conflicts.

Main classes:
- Gns3Connector: Connector for GNS3 server API interaction
- Project: GNS3 Project management
- Node: GNS3 Node management
- Link: GNS3 Link management
- GNS3TopologyTool: GNS3 topology reading tool
- GNS3ProjectInfoTool: GNS3 project info tool

Main functions:
- get_gns3_connector: Factory function to create Gns3Connector
- get_gns3_connector_with_llm_config: Create connector AND retrieve LLM config
- get_gns3_server_host: Get GNS3 server hostname from Controller or Config
- get_llm_config: Get LLM model configuration for a user

This module is part of the GNS3-Copilot project.
GitHub: https://github.com/yueguobin/gns3-copilot

Upstream gns3fy: https://github.com/davidban77/gns3fy
"""

from .connector_factory import (
    get_gns3_connector,
    get_gns3_connector_with_llm_config,
    get_gns3_server_host,
    get_llm_config,
    set_current_jwt_token,
    get_current_jwt_token,
    set_current_llm_config,
    get_current_llm_config,
)
from .custom_gns3fy import (
    CONSOLE_TYPES,
    LINK_TYPES,
    NODE_TYPES,
    Gns3Connector,
    Link,
    Node,
    Project,
)
from .gns3_topology_reader import GNS3TopologyTool
from .gns3_project_info import GNS3ProjectInfoTool

# Dynamic version management
try:
    from importlib.metadata import version

    __version__ = version("gns3-copilot")
except Exception:
    __version__ = "unknown"

__author__ = "Guobin Yue"
__description__ = "AI-powered network automation assistant for GNS3"
__url__ = "https://github.com/yueguobin/gns3-copilot"

__all__ = [
    "Gns3Connector",
    "Project",
    "Node",
    "Link",
    "NODE_TYPES",
    "CONSOLE_TYPES",
    "LINK_TYPES",
    "GNS3TopologyTool",
    "GNS3ProjectInfoTool",
    "get_gns3_connector",
    "get_gns3_connector_with_llm_config",
    "get_gns3_server_host",
    "get_llm_config",
    "set_current_jwt_token",
    "get_current_jwt_token",
    "set_current_llm_config",
    "get_current_llm_config",
]
