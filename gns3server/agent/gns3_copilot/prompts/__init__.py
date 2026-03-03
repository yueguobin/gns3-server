"""
Prompts module for GNS3 Copilot.

This package contains system prompts and prompt loading utilities for
the GNS3 Copilot AI agent.
"""

from .base_prompt import SYSTEM_PROMPT
from .prompt_loader import load_system_prompt
from .title_prompt import TITLE_PROMPT

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
    "SYSTEM_PROMPT",
    "TITLE_PROMPT",
    "load_system_prompt",
]
