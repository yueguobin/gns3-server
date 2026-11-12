"""add distribution_records table

Revision ID: b8e2c6d4a9f1
Revises: ed99f4cfc26f
Create Date: 2026-11-12 10:00:00.000000

"""

import uuid

import sqlalchemy as sa
from alembic import op

import gns3server.db.models.base as models

# revision identifiers, used by Alembic.
revision = "b8e2c6d4a9f1"
down_revision = "ed99f4cfc26f"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table(
        "distribution_records",
        sa.Column("distribution_id", models.GUID(), nullable=False),
        sa.Column("project_id", models.GUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("distribution_id"),
    )
    op.create_index("ix_distribution_records_project_id", "distribution_records", ["project_id"])

    # grant the "User" role to the "Users" group on the cross-project
    # distribution listing, like the other default resource paths (the
    # after_create seeding only runs on a new database)
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO acl (ace_id, ace_type, path, propagate, allowed, role_id, group_id)"
            " SELECT :ace_id, 'group', '/distributions', 1, 1,"
            " (SELECT role_id FROM roles WHERE name = 'User'),"
            " (SELECT user_group_id FROM user_groups WHERE name = 'Users')"
            " WHERE NOT EXISTS ("
            " SELECT 1 FROM acl WHERE path = '/distributions'"
            " AND group_id = (SELECT user_group_id FROM user_groups WHERE name = 'Users'))"
        ),
        {"ace_id": uuid.uuid4().hex},
    )


def downgrade() -> None:

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM acl WHERE path = '/distributions' AND ace_type = 'group'"
            " AND group_id = (SELECT user_group_id FROM user_groups WHERE name = 'Users')"
        )
    )
    op.drop_index("ix_distribution_records_project_id", table_name="distribution_records")
    op.drop_table("distribution_records")
