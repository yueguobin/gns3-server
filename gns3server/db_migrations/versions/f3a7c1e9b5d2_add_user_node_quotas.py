"""add per-user and per-group node quotas

Revision ID: f3a7c1e9b5d2
Revises: a7c2e9f4b8d1
Create Date: 2026-11-11 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a7c1e9b5d2"
down_revision = "a7c2e9f4b8d1"
branch_labels = None
depends_on = None

_USER_COLUMNS = ("max_nodes", "max_running_nodes")
_GROUP_COLUMNS = ("default_max_nodes", "default_max_running_nodes")


def upgrade() -> None:

    # The columns may already exist on unversioned databases created from
    # Base.metadata.create_all (replayed by the manual startup chain).
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    group_columns = {column["name"] for column in inspector.get_columns("user_groups")}

    for column in _USER_COLUMNS:
        if column not in user_columns:
            op.add_column("users", sa.Column(column, sa.Integer(), nullable=True))
    for column in _GROUP_COLUMNS:
        if column not in group_columns:
            op.add_column("user_groups", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:

    for column in _USER_COLUMNS:
        op.drop_column("users", column)
    for column in _GROUP_COLUMNS:
        op.drop_column("user_groups", column)
