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
Tool evidence store for GNS3-Copilot (Phase 2: evidence externalization).

Full tool outputs are evidence: too valuable to throw away, too large to
keep in the message history. This module stores them in a table of the
per-project checkpoint database and replaces them in the ToolMessage with
a bounded view (head + tail + per-key summary for dict results) that
carries an evidence id the model can retrieve through the get_evidence
tool.

tool_node is a synchronous graph node, so this store uses its own
synchronous sqlite3 connection (with busy_timeout, WAL is already enabled
on the database by the checkpointer setup) instead of the async
checkpointer connection.
"""

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from gns3server.agent.gns3_copilot.gns3_client.context_helpers import (
    get_current_evidence_db_path,
)

logger = logging.getLogger(__name__)

# Serialized outputs at or below this size stay inline in the ToolMessage
# (no evidence row, unchanged behaviour)
EVIDENCE_INLINE_MAX_CHARS = 4000

# Head and tail kept in the bounded view for large outputs
EVIDENCE_VIEW_HEAD_CHARS = 2048
EVIDENCE_VIEW_TAIL_CHARS = 2048

# One evidence row never grows past this; larger content is stored
# truncated with a flag
EVIDENCE_MAX_CHARS = 2_000_000

# Per-key summary line budget for dict-shaped outputs (first lines of
# each top-level value, e.g. one status line per device)
EVIDENCE_VIEW_MAX_KEYS = 20
EVIDENCE_VIEW_KEY_CHARS = 160

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_evidence (
    evidence_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    tool_call_id TEXT,
    tool_name TEXT NOT NULL,
    created_at TIMESTAMP,
    content TEXT,
    size_chars INTEGER,
    truncated BOOLEAN DEFAULT 0,
    meta TEXT DEFAULT '{}'
)
"""


class ToolEvidenceStore:
    """
    Synchronous SQLite store for full tool outputs.

    One instance owns one connection to one checkpoint database. Sync
    graph nodes may run in different executor threads, so every access
    goes through a lock.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.Error:
            # WAL is a database-level persistent pragma set by the async
            # checkpointer setup; failing here (for example a locked
            # database) is not fatal for a plain insert
            logger.debug("Could not set WAL mode on the evidence connection")
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_thread ON tool_evidence(thread_id)")
            self._conn.commit()

    def save(
        self,
        thread_id: str,
        tool_name: str,
        content: str,
        tool_call_id: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Store one evidence row.

        Content above EVIDENCE_MAX_CHARS is stored truncated with
        truncated=True. Returns the row metadata (evidence_id, size,
        truncated).
        """
        evidence_id = uuid4().hex
        truncated = len(content) > EVIDENCE_MAX_CHARS
        stored = content[:EVIDENCE_MAX_CHARS] if truncated else content
        with self._lock:
            self._conn.execute(
                "INSERT INTO tool_evidence "
                "(evidence_id, thread_id, tool_call_id, tool_name, created_at, content, size_chars, truncated, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    thread_id,
                    tool_call_id,
                    tool_name,
                    datetime.now(tz=UTC).isoformat(),
                    stored,
                    len(content),
                    truncated,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        return {"evidence_id": evidence_id, "size_chars": len(content), "truncated": truncated}

    def get(self, evidence_id: str) -> Optional[dict[str, Any]]:
        """Fetch one evidence row as a dict, or None when missing."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT evidence_id, thread_id, tool_call_id, tool_name, created_at, "
                "content, size_chars, truncated, meta FROM tool_evidence WHERE evidence_id = ?",
                (evidence_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "evidence_id": row[0],
            "thread_id": row[1],
            "tool_call_id": row[2],
            "tool_name": row[3],
            "created_at": row[4],
            "content": row[5],
            "size_chars": row[6],
            "truncated": bool(row[7]),
            "meta": json.loads(row[8] or "{}"),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# Module-level registry: one store per database path. The graph nodes have
# no dependency injection, so tool_node resolves the store through this
# registry from the request-scoped evidence path.
_stores: dict[str, ToolEvidenceStore] = {}
_registry_lock = threading.Lock()


def get_store(db_path: str) -> ToolEvidenceStore:
    """Get (or lazily create) the evidence store for a database path."""
    with _registry_lock:
        store = _stores.get(db_path)
        if store is None:
            store = ToolEvidenceStore(db_path)
            _stores[db_path] = store
        return store


def close_store(db_path: str) -> None:
    """Close and forget the store for a database path (project closed)."""
    with _registry_lock:
        store = _stores.pop(db_path, None)
    if store is not None:
        store.close()


def _first_line(value: Any) -> str:
    """First non-empty line of a value, truncated to the key budget."""
    for line in str(value).splitlines():
        line = line.strip()
        if line:
            return line[:EVIDENCE_VIEW_KEY_CHARS]
    return ""


def _summary_keys(observation: Any) -> Optional[dict[str, str]]:
    """
    Per-key summary lines for dict-shaped observations.

    Multi-device outputs are dicts keyed by device; one status line per
    key keeps the model oriented without the bulk. Returns None for any
    non-dict observation.
    """
    if not isinstance(observation, dict) or not observation:
        return None
    keys = {}
    for key in list(observation.keys())[:EVIDENCE_VIEW_MAX_KEYS]:
        keys[str(key)] = _first_line(observation[key])
    if len(observation) > EVIDENCE_VIEW_MAX_KEYS:
        keys["..."] = f"{len(observation) - EVIDENCE_VIEW_MAX_KEYS} more entries omitted"
    return keys


def externalize_tool_output(
    tool_name: str,
    serialized: str,
    observation: Any,
    thread_id: Optional[str],
    tool_call_id: Optional[str] = None,
) -> str:
    """
    Return the content for the ToolMessage.

    Small serialized outputs come back unchanged. Large ones are stored as
    evidence and replaced by a bounded view (head + tail + per-key summary
    for dict results) that carries the evidence id for retrieval through
    the get_evidence tool. When no evidence database is configured for the
    request, large outputs degrade to the bounded view without storage.
    """
    if len(serialized) <= EVIDENCE_INLINE_MAX_CHARS:
        return serialized

    db_path = get_current_evidence_db_path()
    evidence_id = None
    stored_truncated = False
    if db_path:
        try:
            row = get_store(db_path).save(
                thread_id=thread_id or "",
                tool_name=tool_name,
                content=serialized,
                tool_call_id=tool_call_id,
            )
            evidence_id = row["evidence_id"]
            stored_truncated = row["truncated"]
            logger.info(
                "Externalized tool output as evidence %s: tool=%s, chars=%d",
                evidence_id,
                tool_name,
                row["size_chars"],
            )
        except Exception as e:
            # Evidence storage must never break the tool loop
            logger.warning("Evidence storage failed, falling back to the bounded view only: %s", e)

    view: dict[str, Any] = {
        "note": "Tool output was too large for the conversation history and was truncated here."
        + (
            f" Call the get_evidence tool with evidence_id '{evidence_id}' to read the full stored output."
            if evidence_id
            else " The full output was not stored."
        ),
        "size_chars": len(serialized),
        "head": serialized[:EVIDENCE_VIEW_HEAD_CHARS],
        "tail": serialized[-EVIDENCE_VIEW_TAIL_CHARS:]
        if len(serialized) > EVIDENCE_VIEW_HEAD_CHARS + EVIDENCE_VIEW_TAIL_CHARS
        else "",
    }
    keys_summary = _summary_keys(observation)
    if keys_summary is not None:
        view["keys_summary"] = keys_summary
    if evidence_id:
        view["evidence_id"] = evidence_id
        view["stored_truncated"] = stored_truncated
    return json.dumps(view, ensure_ascii=False, indent=2)
