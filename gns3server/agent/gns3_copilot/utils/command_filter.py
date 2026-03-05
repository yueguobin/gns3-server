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
# Copyright (C) 2025 Guobin Yue
# Author: Guobin Yue
#
# Project Home: https://github.com/yueguobin/gns3-copilot
#

"""
Command filter module for GNS3-Copilot.

This module provides functionality to filter out dangerous or long-running
commands that may cause issues with tool execution timeouts or device console
availability.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_gns3_copilot_root() -> Path:
    """Get the root directory of the GNS3-Copilot project."""
    # Get the directory containing this file
    current_file = Path(__file__).resolve()
    # Go up to the gns3_copilot directory (utils parent)
    return current_file.parent.parent

# Default forbidden commands (fallback if file not found)
DEFAULT_FORBIDDEN_COMMANDS = [
    "traceroute",
    "tracepath",
    "tracert",
    "ping -f",
    "debug",
    "test",
]

# Cache for forbidden commands to avoid repeated file reads
_forbidden_commands_cache: list[str] | None = None


def _get_forbidden_commands_file_path() -> Path:
    """Get the path to the forbidden commands configuration file."""
    return _get_gns3_copilot_root() / "config" / "forbidden_commands.txt"


def _load_forbidden_commands() -> list[str]:
    """
    Load forbidden commands from the configuration file.

    Returns:
        List of forbidden command patterns. If the file cannot be read,
        returns the default list.
    """
    global _forbidden_commands_cache

    # Return cached value if available
    if _forbidden_commands_cache is not None:
        return _forbidden_commands_cache

    file_path = _get_forbidden_commands_file_path()

    try:
        if not file_path.exists():
            logger.warning(
                "Forbidden commands file not found: %s. Using default list.",
                file_path,
            )
            _forbidden_commands_cache = DEFAULT_FORBIDDEN_COMMANDS.copy()
            return _forbidden_commands_cache

        with open(file_path, "r", encoding="utf-8") as f:
            forbidden_commands = []
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                forbidden_commands.append(line.lower())

        if not forbidden_commands:
            logger.warning("No forbidden commands found in %s. Using default list.", file_path)
            _forbidden_commands_cache = DEFAULT_FORBIDDEN_COMMANDS.copy()
        else:
            logger.info(
                "Loaded %d forbidden command patterns from %s",
                len(forbidden_commands),
                file_path,
            )
            _forbidden_commands_cache = forbidden_commands

        return _forbidden_commands_cache

    except Exception as e:
        logger.error(
            "Error reading forbidden commands file %s: %s. Using default list.",
            file_path,
            e,
        )
        _forbidden_commands_cache = DEFAULT_FORBIDDEN_COMMANDS.copy()
        return _forbidden_commands_cache


def reload_forbidden_commands() -> None:
    """
    Reload the forbidden commands list from the configuration file.

    This clears the cache and forces a reload from the file on the next
    call to filter_forbidden_commands() or get_forbidden_commands().

    Use this after modifying the forbidden_commands.txt file to apply
    changes without restarting the GNS3 server.
    """
    global _forbidden_commands_cache
    _forbidden_commands_cache = None
    logger.info("Forbidden commands cache cleared. Will reload on next access.")


def get_forbidden_commands() -> list[str]:
    """
    Get the current list of forbidden command patterns.

    Returns:
        List of forbidden command patterns (lowercase).
    """
    return _load_forbidden_commands()


def is_command_forbidden(command: str) -> bool:
    """
    Check if a single command is forbidden.

    Args:
        command: The command string to check.

    Returns:
        True if the command matches a forbidden pattern, False otherwise.
    """
    forbidden_commands = _load_forbidden_commands()
    command_lower = command.strip().lower()

    for forbidden_pattern in forbidden_commands:
        if command_lower.startswith(forbidden_pattern):
            return True

    return False


def filter_forbidden_commands(
    commands: list[str],
) -> tuple[list[str], dict[str, str]]:
    """
    Filter out forbidden commands from a list of commands.

    Args:
        commands: List of command strings to filter.

    Returns:
        A tuple of (allowed_commands, blocked_commands_info):
        - allowed_commands: List of commands that are not forbidden.
        - blocked_commands_info: Dict mapping blocked commands to their reasons.
    """
    allowed_commands: list[str] = []
    blocked_commands_info: dict[str, str] = {}

    for command in commands:
        if is_command_forbidden(command):
            # Find which pattern matched
            forbidden_commands = _load_forbidden_commands()
            command_lower = command.strip().lower()
            matched_pattern = None

            for pattern in forbidden_commands:
                if command_lower.startswith(pattern):
                    matched_pattern = pattern
                    break

            reason = (
                f"Command '{command}' is not allowed because it matches the "
                f"forbidden pattern '{matched_pattern}'. "
                f"This command may run longer than the tool timeout or leave "
                f"the device console unavailable for subsequent commands."
            )
            blocked_commands_info[command] = reason
        else:
            allowed_commands.append(command)

    if blocked_commands_info:
        logger.info(
            "Filtered %d command(s): %s",
            len(blocked_commands_info),
            list(blocked_commands_info.keys()),
        )

    return allowed_commands, blocked_commands_info
