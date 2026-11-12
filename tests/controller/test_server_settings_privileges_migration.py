import pytest
import sqlalchemy as sa
from alembic import command, config
from fastapi import FastAPI

from gns3server.db.models import Base
from gns3server.db.tasks import connect_to_db

PRIVILEGES = ("Server.Audit", "Server.Modify")


def _alembic_config():
    cfg = config.Config()
    cfg.set_main_option("script_location", "gns3server:db_migrations")
    return cfg


def _remove_server_privileges(connection):
    # simulate a database created before the settings API seeded the privileges
    connection.exec_driver_sql(
        "DELETE FROM privilege_role_map WHERE privilege_id IN"
        " (SELECT privilege_id FROM privileges WHERE name IN ('Server.Audit', 'Server.Modify'))"
    )
    connection.exec_driver_sql("DELETE FROM privileges WHERE name IN ('Server.Audit', 'Server.Modify')")


@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.asyncio
async def test_server_settings_privileges_are_backfilled_on_startup(tmp_path, monkeypatch, versioned):
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        _remove_server_privileges(connection)
        if versioned:
            cfg = _alembic_config()
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "f3a7c1e9b5d2")
        # else: unversioned database with llm_model_configs already created by
        # the code, upgraded through the manual startup chain
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            for name in PRIVILEGES:
                count = await connection.scalar(
                    sa.text("SELECT COUNT(*) FROM privileges WHERE name = :name"), {"name": name}
                )
                assert count == 1, f"{name} was not backfilled exactly once"
            attached = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM privilege_role_map m"
                    " JOIN privileges p ON p.privilege_id = m.privilege_id"
                    " JOIN roles r ON r.role_id = m.role_id"
                    " WHERE p.name IN :names AND r.name = 'Administrator'"
                ).bindparams(sa.bindparam("names", expanding=True)),
                {"names": list(PRIVILEGES)},
            )
            assert attached == 2, "the Administrator role does not hold both privileges"
    finally:
        await app.state._db_engine.dispose()
