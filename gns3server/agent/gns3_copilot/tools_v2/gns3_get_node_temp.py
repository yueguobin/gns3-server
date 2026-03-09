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

GNS3 template retrieval tool for device discovery.

Provides functionality to retrieve all available device templates
from a GNS3 server, including template names, IDs, and types.
"""

import json
import logging
from pprint import pprint
from typing import Any

from langchain.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

from gns3server.agent.gns3_copilot.gns3_client import get_gns3_connector

# Configure logging
logger = logging.getLogger(__name__)


class GNS3TemplateTool(BaseTool):
    """
    LangChain tool to retrieve available device templates from GNS3 server.
    Connects to GNS3 server and extracts name, template_id, and template_type.

    **Input:**
    No input required. Connects to GNS3 server at default URL.

    **Output:**
    Dict with list of dicts (name, template_id, template_type).
    If error, returns dict with error message.
    """

    name: str = "get_gns3_templates"
    description: str = """
    Retrieves available device templates from GNS3 server.
    Returns dict with list of dicts (name, template_id, template_type).
    No input required.
    If connection fails, returns dict with error message.
    """

    def _run(
        self,
        tool_input: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        """
        Connects to GNS3 server and retrieves available device templates.

        Args:
            tool_input: Optional input (not used).
            run_manager: LangChain run manager (unused).

        Returns:
            dict: Dict with templates list or error message.
        """
        try:
            # Initialize Gns3Connector using factory function
            logger.info("Connecting to GNS3 server...")
            gns3_server = get_gns3_connector()

            if gns3_server is None:
                logger.error("Failed to create GNS3 connector")
                return {
                    "error": (
                        "Failed to connect to GNS3 server. "
                        "Please check your configuration."
                    )
                }

            # Retrieve all available templates
            templates = gns3_server.get_templates()
            # Extract name, template_id, and template_type
            template_info = [
                {
                    "name": template.get("name", "N/A"),
                    "template_id": template.get("template_id", "N/A"),
                    "template_type": template.get("template_type", "N/A"),
                }
                for template in templates
            ]

            # Return JSON-formatted result with full logging
            result = {"templates": template_info}
            logger.info(
                "Template retrieval completed. Total: %d. Result: %s",
                len(template_info),
                json.dumps(result, indent=2, ensure_ascii=False),
            )
            return result

        except Exception as e:
            logger.error(
                "Failed to connect to GNS3 server or retrieve templates: %s", e
            )
            return {"error": f"Failed to retrieve templates: {str(e)}"}


if __name__ == "__main__":
    # Test's tool locally
    tool = GNS3TemplateTool()
    result = tool._run("")
    pprint(result)
