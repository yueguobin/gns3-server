"""add distribution_records table

Revision ID: b8e2c6d4a9f1
Revises: ed99f4cfc26f
Create Date: 2026-11-12 10:00:00.000000

"""

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


def downgrade() -> None:

    op.drop_index("ix_distribution_records_project_id", table_name="distribution_records")
    op.drop_table("distribution_records")
