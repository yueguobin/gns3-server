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
Prompt Loader for GNS3-Copilot

This module provides utilities for loading system prompts.
Can be extended to support multiple prompt variants based on
environment variables (e.g., ENGLISH_LEVEL).

This module is part of the GNS3-Copilot project.
GitHub: https://github.com/yueguobin/gns3-copilot
"""

import logging
import os

from .base_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def load_system_prompt() -> str:
    """
    Load the system prompt for GNS3-Copilot.

    In the future, this can be extended to support multiple prompt variants
    based on environment variables (e.g., ENGLISH_LEVEL).

    Returns:
        str: The system prompt string.
    """
    # For now, just return the base system prompt
    # Future enhancement: Load different prompts based on ENGLISH_LEVEL env var
    # english_level = os.getenv("ENGLISH_LEVEL", "native")
    return SYSTEM_PROMPT
