"""
GNS3 Client Package

This package provides a Python interface for interacting with GNS3 servers.
It's adapted from the upstream gns3fy project with modifications for compatibility
with langchain and reduced dependency conflicts.

Main classes:
- Gns3Connector: Connector for GNS3 server API interaction
- Project: GNS3 Project management
- Node: GNS3 Node management
- Link: GNS3 Link management
- GNS3TopologyTool: GNS3 topology reading tool
- GNS3UpdateDrawingTool: GNS3 drawing update tool

Main functions:
- get_gns3_connector: Factory function to create Gns3Connector from environment
- get_gns3_connector_with_llm_config: Factory function to create connector AND retrieve LLM config
- get_gns3_server_host: Get GNS3 server hostname from Controller or Config
- get_llm_config: Get LLM model configuration for a user
"""

from .connector_factory import (
    get_gns3_connector,
    get_gns3_connector_with_llm_config,
    get_gns3_server_host,
    get_llm_config,
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
    "get_gns3_connector",
    "get_gns3_connector_with_llm_config",
    "get_gns3_server_host",
    "get_llm_config",
]
