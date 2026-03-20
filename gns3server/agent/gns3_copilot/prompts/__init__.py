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
# Copyright (C) 2025 Yue Guobin (岳国宾)
# Author: Yue Guobin (岳国宾)
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""
Prompts Module for GNS3-Copilot

This package contains system prompts and prompt loading utilities for
the GNS3-Copilot AI agent.

Available prompts:
- teaching_assistant_prompt: Teaching assistant mode (diagnostics only)
- lab_automation_assistant_prompt: Lab automation mode (diagnostics + config)

"""

from .teaching_assistant_prompt import TEACHING_ASSISTANT_PROMPT
from .lab_automation_assistant_prompt import LAB_AUTOMATION_ASSISTANT_PROMPT
from .prompt_loader import load_system_prompt
from .title_prompt import TITLE_PROMPT

# Dynamic version management
try:
    from importlib.metadata import version

    __version__ = version("gns3-copilot")
except Exception:
    __version__ = "unknown"

__author__ = "Yue Guobin (岳国宾)"
__description__ = "AI-powered network automation assistant for GNS3"
__url__ = "https://github.com/yueguobin/gns3-copilot"

__all__ = [
    "TEACHING_ASSISTANT_PROMPT",
    "LAB_AUTOMATION_ASSISTANT_PROMPT",
    "TITLE_PROMPT",
    "load_system_prompt",
]
