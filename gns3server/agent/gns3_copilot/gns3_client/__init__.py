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
- GNS3ProjectReadFileTool: LangChain tool for reading project files
- GNS3ProjectWriteFileTool: LangChain tool for writing project files
- GNS3ProjectListFilesTool: LangChain tool for listing project files
- GNS3ProjectLock: LangChain tool for locking/unlocking GNS3 projects

File Manager Modules:
- gns3_project_read_file: GNS3ProjectReadFileTool implementation
- gns3_project_write_file: GNS3ProjectWriteFileTool implementation
- gns3_project_list_files: GNS3ProjectListFilesTool implementation
- gns3_file_index: File index management utilities

Main functions:
- get_gns3_connector: Factory function to create Gns3Connector from environment
- get_gns3_connector_with_llm_config: Factory function to create connector AND retrieve LLM config
"""

from .connector_factory import (
    get_gns3_connector,
    get_gns3_connector_with_llm_config,
    get_gns3_server_host,
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
from .gns3_create_drawing import GNS3CreateDrawingTool
from .gns3_delete_drawing import GNS3DeleteDrawingTool
from .gns3_file_index import add_file_to_index, get_file_list
from .gns3_get_drawings import GNS3GetDrawingsTool
from .gns3_get_nodes import GNS3GetNodesTool
from .gns3_project_create import GNS3ProjectCreate
from .gns3_project_delete import GNS3ProjectDelete
from .gns3_project_list_files import GNS3ProjectListFilesTool
from .gns3_project_lock import GNS3ProjectLock
from .gns3_project_open import GNS3ProjectOpen
from .gns3_project_path import GNS3ProjectPath
from .gns3_project_read_file import GNS3ProjectReadFileTool
from .gns3_project_update import GNS3ProjectUpdate
from .gns3_project_write_file import GNS3ProjectWriteFileTool
from .gns3_projects_list import GNS3ProjectList
from .gns3_topology_reader import GNS3TopologyTool
from .gns3_update_drawing import GNS3UpdateDrawingTool

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
    "GNS3ProjectList",
    "GNS3ProjectOpen",
    "GNS3ProjectPath",
    "GNS3ProjectCreate",
    "GNS3ProjectDelete",
    "GNS3ProjectLock",
    "GNS3ProjectUpdate",
    "GNS3ProjectReadFileTool",
    "GNS3ProjectWriteFileTool",
    "GNS3ProjectListFilesTool",
    "GNS3CreateDrawingTool",
    "GNS3DeleteDrawingTool",
    "GNS3GetDrawingsTool",
    "GNS3GetNodesTool",
    "GNS3UpdateDrawingTool",
    "get_gns3_connector",
    "get_gns3_connector_with_llm_config",
    "get_gns3_server_host",
    "add_file_to_index",
    "get_file_list",
]
