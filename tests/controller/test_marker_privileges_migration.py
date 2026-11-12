import pytest
import sqlalchemy as sa
from alembic import command, config
from fastapi import FastAPI

from gns3server.db.models import Base
from gns3server.db.tasks import connect_to_db

PRIVILEGES = ("Link.Marker", "Project.Marker")
ROLE_NAMES = ("Administrator", "User", "Lab member")


def _alembic_config():
    cfg = config.Config()
    cfg.set_main_option("script_location", "gns3server:db_migrations")
    return cfg


def _remove_marker_privileges(connection):
    # simulate a database created before the marker write endpoints had
    # their own privileges
    connection.exec_driver_sql(
        "DELETE FROM privilege_role_map WHERE privilege_id IN"
        " (SELECT privilege_id FROM privileges WHERE name IN ('Link.Marker', 'Project.Marker'))"
    )
    connection.exec_driver_sql("DELETE FROM privileges WHERE name IN ('Link.Marker', 'Project.Marker')")


@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.asyncio
async def test_marker_privileges_are_backfilled_on_startup(tmp_path, monkeypatch, versioned):
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        _remove_marker_privileges(connection)
        if versioned:
            cfg = _alembic_config()
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "a43d55900514")
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
            for role in ROLE_NAMES:
                attached = await connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM privilege_role_map m"
                        " JOIN privileges p ON p.privilege_id = m.privilege_id"
                        " JOIN roles r ON r.role_id = m.role_id"
                        " WHERE p.name IN :names AND r.name = :role"
                    ).bindparams(sa.bindparam("names", expanding=True)),
                    {"names": list(PRIVILEGES), "role": role},
                )
                assert attached == 2, f"the '{role}' role does not hold both marker privileges"
    finally:
        await app.state._db_engine.dispose()
