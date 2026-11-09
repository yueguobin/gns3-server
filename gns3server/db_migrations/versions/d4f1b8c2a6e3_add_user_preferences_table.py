"""add user_preferences table

Revision ID: d4f1b8c2a6e3
Revises: c8d4b6e2f913
Create Date: 2026-11-09 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

import gns3server.db.models.base as models

# revision identifiers, used by Alembic.
revision = "d4f1b8c2a6e3"
down_revision = "c8d4b6e2f913"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # The table may already exist on unversioned databases created from
    # Base.metadata.create_all (replayed by the manual startup chain).
    if sa.inspect(op.get_bind()).has_table("user_preferences"):
        return

    op.create_table(
        "user_preferences",
        sa.Column("user_id", models.GUID(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:

    op.drop_table("user_preferences")
