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
GNS3-Copilot evidence retrieval tool (Phase 2: evidence externalization).

When a tool output is too large for the conversation history, the
ToolMessage carries a bounded view with an evidence_id instead of the full
content. This tool reads the stored full output back, one window at a
time, so the model can pull details on demand without dragging megabytes
through the context.
"""

import json
import logging
from typing import Any

from langchain.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

from gns3server.agent.gns3_copilot.agent.evidence_store import get_store
from gns3server.agent.gns3_copilot.gns3_client.context_helpers import (
    get_current_evidence_db_path,
)

logger = logging.getLogger(__name__)

# Window limits: enough to read a device configuration or a slice of a
# packet capture in one call, small enough that one retrieval cannot
# recreate the problem evidence storage solves. The default window must
# also stay below EVIDENCE_INLINE_MAX_CHARS so a retrieved window is not
# itself externalized again.
MAX_WINDOW_CHARS = 32768
DEFAULT_WINDOW_CHARS = 3000


class GetEvidenceTool(BaseTool):
    """
    A LangChain tool that retrieves stored tool output by evidence id.

    **Input**:
    A JSON object with evidence_id (string), optional offset and limit
    (integers, characters).
    Example:
        {"evidence_id": "abc123", "offset": 0, "limit": 3000}

    **Output**:
    {"evidence_id": ..., "content": "<window of the stored output>",
     "offset": ..., "returned_chars": ..., "has_more": ...}
    """

    name: str = "get_evidence"
    description: str = """
    Read the full stored output of a previous tool call. When a tool
    result appears truncated, it contains an evidence_id and a note
    pointing here. Input: JSON with evidence_id (string), optional
    offset (integer, characters, default 0) and limit (integer,
    characters, default 3000, max 32768) to page through large outputs.
    Returns a content window plus offset, returned_chars and has_more
    for paging. Read only the windows you need.
    """

    def _run(
        self,
        tool_input: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        try:
            input_data = json.loads(tool_input)
            if not isinstance(input_data, dict):
                return {"error": "Input must be a JSON object with an evidence_id field."}
            evidence_id = input_data.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                return {"error": "evidence_id must be a non-empty string."}

            def _int_arg(name: str, default: int) -> int:
                value = input_data.get(name, default)
                if isinstance(value, str) and value.strip().isdigit():
                    value = int(value.strip())
                if not isinstance(value, int) or isinstance(value, bool):
                    return default
                return value

            offset = max(0, _int_arg("offset", 0))
            limit = min(MAX_WINDOW_CHARS, max(1, _int_arg("limit", DEFAULT_WINDOW_CHARS)))

            db_path = get_current_evidence_db_path()
            if not db_path:
                return {"error": "Evidence storage is not available for this session."}
            row = get_store(db_path).get(evidence_id)
            if row is None:
                return {"error": f"No stored evidence with evidence_id '{evidence_id}'."}

            content = row["content"]
            window = content[offset : offset + limit]
            logger.debug(
                "Evidence %s read: offset=%d, returned=%d of %d chars",
                evidence_id,
                offset,
                len(window),
                len(content),
            )
            return {
                "evidence_id": evidence_id,
                "tool_name": row["tool_name"],
                "offset": offset,
                "returned_chars": len(window),
                "size_chars": len(content),
                "stored_truncated": row["truncated"],
                "has_more": offset + len(window) < len(content),
                "content": window,
            }

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON input: %s", e)
            return {"error": f"Invalid JSON input: {e}"}
        except Exception as e:
            logger.error("Evidence retrieval failed: %s", e)
            return {"error": f"Evidence retrieval failed: {e!s}"}
