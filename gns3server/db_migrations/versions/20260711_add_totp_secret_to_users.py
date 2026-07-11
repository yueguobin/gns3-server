"""add totp_secret to users

Revision ID: 20260711_add_totp_secret_to_users
Revises: f0b0de2a9
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20260711_add_totp_secret_to_users'
down_revision = 'f0b0de2a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: on fresh databases Base.metadata.create_all already creates
    # the column, so only add it for existing databases that lack it.
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = [column['name'] for column in inspector.get_columns('users')]
    if 'totp_secret' not in existing_columns:
        op.add_column('users', sa.Column('totp_secret', sa.String(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = [column['name'] for column in inspector.get_columns('users')]
    if 'totp_secret' in existing_columns:
        op.drop_column('users', 'totp_secret')
