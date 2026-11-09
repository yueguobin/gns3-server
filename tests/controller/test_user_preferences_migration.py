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
async def test_user_preferences_table_is_added_on_upgrade(tmp_path, monkeypatch, versioned):
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        # simulate a database from before the user preferences existed
        connection.exec_driver_sql("DROP TABLE user_preferences")
        if versioned:
            cfg = _alembic_config()
            cfg.attributes["connection"] = connection
            command.stamp(cfg, "c8d4b6e2f913")
        # else: unversioned database with llm_model_configs already created by
        # the code, upgraded through the manual startup chain
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            assert await connection.run_sync(lambda conn: sa.inspect(conn).has_table("user_preferences"))
            # the table is usable: the admin user can hold a preferences document
            admin_id = await connection.scalar(sa.text("SELECT user_id FROM users WHERE username = 'admin'"))
            await connection.execute(
                sa.text("INSERT INTO user_preferences (user_id, preferences) VALUES (:id, '{}')"),
                {"id": admin_id},
            )
            row = await connection.scalar(sa.text("SELECT preferences FROM user_preferences"))
            assert row == "{}"
            await connection.commit()
    finally:
        await app.state._db_engine.dispose()


@pytest.mark.asyncio
async def test_existing_user_preferences_table_survives_the_startup_chain(tmp_path, monkeypatch):
    # unversioned database already created from current code (create_all made
    # the table): the manual startup chain replays the migration and must
    # leave the existing document alone
    path = tmp_path / "controller.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        Base.metadata.create_all(connection)
        admin_id = connection.execute(sa.text("SELECT user_id FROM users WHERE username = 'admin'")).scalar_one()
        connection.execute(
            sa.text("INSERT INTO user_preferences (user_id) VALUES (:id)"),
            {"id": admin_id},
        )
        connection.commit()
    engine.dispose()

    monkeypatch.setenv("GNS3_DATABASE_URI", f"sqlite+aiosqlite:///{path}")
    app = FastAPI()
    await connect_to_db(app)
    try:
        async with app.state._db_engine.connect() as connection:
            count = await connection.scalar(sa.text("SELECT COUNT(*) FROM user_preferences"))
            assert count == 1
    finally:
        await app.state._db_engine.dispose()
