"""add mcp_tool_whitelist table

Revision ID: c3e7f1a9b5d2
Revises: b8e2c6d4a9f1
Create Date: 2026-11-13 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

import gns3server.db.models.base as models

# revision identifiers, used by Alembic.
revision = "c3e7f1a9b5d2"
down_revision = "b8e2c6d4a9f1"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # The table may already exist on unversioned databases created from
    # Base.metadata.create_all (replayed by the manual startup chain).
    if sa.inspect(op.get_bind()).has_table("mcp_tool_whitelist"):
        return

    op.create_table(
        "mcp_tool_whitelist",
        sa.Column("user_group_id", models.GUID(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["user_group_id"], ["user_groups.user_group_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_group_id", "tool_name"),
    )


def downgrade() -> None:

    op.drop_table("mcp_tool_whitelist")
