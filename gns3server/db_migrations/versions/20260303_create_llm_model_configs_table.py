"""create llm_model_configs table

Revision ID: 20260303_create_llm_model_configs
Revises: 7ceeddd9c9a8
Create Date: 2026-03-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260303_create_llm_model_configs'
down_revision = '7ceeddd9c9a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create llm_model_configs table
    op.create_table(
        'llm_model_configs',
        sa.Column('config_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=True),
        sa.Column('group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('user_groups.user_group_id', ondelete='CASCADE'), nullable=True),
        sa.Column('is_default', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND group_id IS NULL) OR "
            "(user_id IS NULL AND group_id IS NOT NULL)",
            name='single_owner_check'
        ),
        sa.UniqueConstraint(
            'user_id', 'is_default',
            name='unique_user_default',
            deferrable=True, initially='deferred',
            postgresql_where=sa.text("is_default = TRUE AND user_id IS NOT NULL")
        ),
        sa.UniqueConstraint(
            'group_id', 'is_default',
            name='unique_group_default',
            deferrable=True, initially='deferred',
            postgresql_where=sa.text("is_default = TRUE AND group_id IS NOT NULL")
        ),
    )

    # Create indexes for efficient queries
    op.create_index('idx_llm_model_configs_user_id', 'llm_model_configs', ['user_id'])
    op.create_index('idx_llm_model_configs_group_id', 'llm_model_configs', ['group_id'])
    op.create_index('idx_llm_model_configs_config', 'llm_model_configs', ['config'], postgresql_using='gin')


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_llm_model_configs_config', table_name='llm_model_configs')
    op.drop_index('idx_llm_model_configs_group_id', table_name='llm_model_configs')
    op.drop_index('idx_llm_model_configs_user_id', table_name='llm_model_configs')

    # Drop table
    op.drop_table('llm_model_configs')
