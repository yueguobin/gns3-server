"""
FlowNet-Lab Public Model Package

This package provides reusable public models and utilities for GNS3 network automation tasks.
It contains common functionality that can be shared across different tools and modules.

Main modules:
- get_gns3_device_port: Device port information retrieval from GNS3 topology
- parse_tool_content: Tool execution result parsing and formatting utilities

Author: Guobin Yue
"""

# Import main utility functions
from .get_gns3_device_port import get_device_ports_from_topology
from .parse_tool_content import format_tool_response, parse_tool_content

# Dynamic version management
try:
    from importlib.metadata import version

    __version__ = version("gns3-copilot")
except Exception:
    __version__ = "unknown"

__author__ = "Guobin Yue"
__description__ = "AI-powered network automation assistant for GNS3"
__url__ = "https://github.com/yueguobin/gns3-copilot"


# Export main utility functions
__all__ = [
    "get_device_ports_from_topology",
    "parse_tool_content",
    "format_tool_response",
]
