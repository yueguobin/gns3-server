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
Prompt Loader for GNS3-Copilot

This module provides utilities for loading system prompts.
Supports multiple prompt variants based on LLM model configuration.

Available Modes (controlled by config.copilot_mode in llm_model_configs):
- "teaching_assistant" (default): Teaching assistant mode - diagnostics only,
  no configuration
- "lab_automation_assistant": Full lab automation assistant mode - diagnostics
  and configuration enabled

"""

import logging

from .teaching_assistant_prompt import TEACHING_ASSISTANT_PROMPT
from .lab_automation_assistant_prompt import LAB_AUTOMATION_ASSISTANT_PROMPT

logger = logging.getLogger(__name__)


def load_system_prompt(llm_config: dict | None = None) -> str:
    """
    Load the system prompt for GNS3-Copilot.

    The prompt mode is controlled by the `copilot_mode` field in the LLM
    model config:
    - "teaching_assistant" (default): Teaching assistant mode - diagnostics
      only, no configuration
    - "lab_automation_assistant": Full lab automation assistant mode -
      diagnostics and configuration enabled

    Args:
        llm_config: LLM model configuration dictionary (flattened structure
                   from get_user_llm_config_full)

    Returns:
        str: The system prompt string.
    """
    if not llm_config:
        logger.info(
            "No LLM config provided, using default TEACHING_ASSISTANT "
            "prompt mode"
        )
        return TEACHING_ASSISTANT_PROMPT

    # llm_config is a flattened dict with copilot_mode at the top level
    # Example: {"provider": "...", "model": "...", "copilot_mode": "...", ...}
    mode = llm_config.get("copilot_mode", "teaching_assistant").lower()

    if mode == "lab_automation_assistant":
        logger.info(
            "Using LAB_AUTOMATION_ASSISTANT prompt mode (diagnostics + "
            "configuration)"
        )
        return LAB_AUTOMATION_ASSISTANT_PROMPT
    else:
        logger.info("Using TEACHING_ASSISTANT prompt mode (diagnostics only)")
        return TEACHING_ASSISTANT_PROMPT
