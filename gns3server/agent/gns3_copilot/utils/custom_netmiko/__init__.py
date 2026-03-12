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
Custom Netmiko drivers for GNS3-emulated network devices.

This package contains custom Netmiko drivers optimized for GNS3
emulation environments where devices may have non-standard
authentication or behavior patterns.

Supported Drivers:
- huawei_ce: HuaweiTelnetCE for CloudEngine devices (no authentication)

Usage:
    from gns3server.agent.gns3_copilot.utils import custom_netmiko

    # Auto-registers all drivers on import
    from netmiko import ConnectHandler

    device = {
        "device_type": "huawei_telnet_ce",
        "host": "127.0.0.1",
        "port": 5000,
    }

    with ConnectHandler(**device) as conn:
        output = conn.send_command("display version")
"""

import logging

logger = logging.getLogger(__name__)

# Import all custom drivers (auto-registers them with Netmiko)
try:
    from . import huawei_ce  # noqa: F401
except Exception as e:
    logger.warning(f"Failed to import Huawei CE driver: {e}", exc_info=True)

__all__ = ["huawei_ce"]
