import pytest
import sqlalchemy as sa
from alembic import command, config
from fastapi import FastAPI

from gns3server.db.models import Base
from gns3server.db.tasks import connect_to_db

LAB_MEMBER_PRIVILEGES = {
    "Project.Allocate",
    "Project.Audit",
    "Snapshot.Audit",
    "Snapshot.Restore",
    "Node.Audit",
    "Node.Console",
    "Node.PowerMgmt",
    "Link.Audit",
    "Link.Capture",
    "Drawing.Audit",
}


def _alembic_config():
    cfg = config.Config()
    cfg.set_main_option("script_location", "gns3server:db_migrations")
    return cfg


async def _role_privileges(connection, role_name: str) -> set:
    rows = await connection.execute(
        sa.text(
            "SELECT p.name FROM privileges p"
            " JOIN privilege_role_map m ON m.privilege_id = p.privilege_id"
            " JOIN roles r ON r.role_id = m.role_id WHERE r.name = :name"
        ),
        {"name": role_name},
    )
    return {row[0] for row in rows}


@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.asyncio
async def test_lab_member_role_is_added_on_upgrade(tmp_path, monkeypatch, versioned):
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        # simulate a database from before the role existed
        connection.execute(
            sa.text(
                "DELETE FROM privilege_role_map WHERE role_id = (SELECT role_id FROM roles WHERE name = 'Lab member')"
            )
        )
        connection.execute(sa.text("DELETE FROM roles WHERE name = 'Lab member'"))
        if versioned:
            cfg = _alembic_config()
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "d4f1b8c2a6e3")
        # else: unversioned database with llm_model_configs already created by
        # the code, upgraded through the manual startup chain
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            is_builtin = await connection.scalar(sa.text("SELECT is_builtin FROM roles WHERE name = 'Lab member'"))
            assert is_builtin == 1
            assert await _role_privileges(connection, "Lab member") == LAB_MEMBER_PRIVILEGES
    finally:
        await app.state._db_engine.dispose()


@pytest.mark.asyncio
async def test_existing_lab_member_role_keeps_identity_and_gains_missing_privileges(tmp_path, monkeypatch):
    # unversioned database already created from current code, where an
    # administrator customized the role: it must not become builtin again and
    # the missing privileges are attached
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        connection.execute(sa.text("UPDATE roles SET is_builtin = 0 WHERE name = 'Lab member'"))
        connection.execute(
            sa.text(
                "DELETE FROM privilege_role_map WHERE role_id ="
                " (SELECT role_id FROM roles WHERE name = 'Lab member')"
                " AND privilege_id NOT IN"
                " (SELECT privilege_id FROM privileges WHERE name = 'Project.Audit')"
            )
        )
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            is_builtin = await connection.scalar(sa.text("SELECT is_builtin FROM roles WHERE name = 'Lab member'"))
            assert is_builtin == 0
            assert await _role_privileges(connection, "Lab member") == LAB_MEMBER_PRIVILEGES
    finally:
        await app.state._db_engine.dispose()
