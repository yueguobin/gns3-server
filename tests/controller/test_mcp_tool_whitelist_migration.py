#
# Copyright (C) 2026 GNS3 Technologies Inc.
# Author: YueGuobin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""
The mcp_tool_whitelist table must appear on upgrade (versioned and
unversioned databases alike) and stay usable.
"""

import pytest
import sqlalchemy as sa
from alembic import command, config
from fastapi import FastAPI

from gns3server.db.models import Base
from gns3server.db.tasks import connect_to_db


def _alembic_config():
    cfg = config.Config()
    cfg.set_main_option("script_location", "gns3server:db_migrations")
    return cfg


@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.asyncio
async def test_mcp_tool_whitelist_table_is_added_on_upgrade(tmp_path, monkeypatch, versioned):
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        # simulate a database from before the whitelist existed
        connection.exec_driver_sql("DROP TABLE mcp_tool_whitelist")
        if versioned:
            cfg = _alembic_config()
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "b8e2c6d4a9f1")
        # else: unversioned database with mcp_tool_whitelist already created
        # by the code, upgraded through the manual startup chain
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            assert await connection.run_sync(lambda conn: sa.inspect(conn).has_table("mcp_tool_whitelist"))
            # the table is usable: a group can hold whitelisted tool names
            admin_id = await connection.scalar(sa.text("SELECT user_id FROM users WHERE username = 'admin'"))
            group_id = await connection.scalar(sa.text("SELECT user_group_id FROM user_groups LIMIT 1"))
            await connection.execute(
                sa.text(
                    "INSERT INTO mcp_tool_whitelist (user_group_id, tool_name) VALUES (:group_id, 'server_version')"
                ),
                {"group_id": group_id},
            )
            count = await connection.scalar(sa.text("SELECT COUNT(*) FROM mcp_tool_whitelist"))
            assert count == 1
            # unused, keeps the fixture honest about the seeded admin
            assert admin_id is not None
            await connection.commit()
    finally:
        await app.state._db_engine.dispose()
