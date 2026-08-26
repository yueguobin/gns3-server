"""add zone privileges to existing database

Revision ID: f51a8c2e3d97
Revises: c7e4a9f1d2b6
Create Date: 2026-08-26

"""
from alembic import op
import sqlalchemy as sa
from uuid import uuid4

# revision identifiers, used by Alembic.
revision = 'f51a8c2e3d97'
down_revision = 'c7e4a9f1d2b6'
branch_labels = None
depends_on = None

privileges_table = sa.table(
    'privileges',
    sa.column('privilege_id', sa.String),
    sa.column('name', sa.String),
    sa.column('description', sa.String),
)

roles_table = sa.table(
    'roles',
    sa.column('role_id', sa.String),
    sa.column('name', sa.String),
)

privilege_role_map = sa.table(
    'privilege_role_map',
    sa.column('privilege_id', sa.String),
    sa.column('role_id', sa.String),
)


def upgrade() -> None:
    conn = op.get_bind()

    # Insert new Zone privileges if they don't already exist
    new_privileges = [
        {"name": "Zone.Allocate", "description": "Create or delete a zone"},
        {"name": "Zone.Audit", "description": "View a zone"},
        {"name": "Zone.Modify", "description": "Update a zone"},
    ]

    privilege_ids = {}
    for priv in new_privileges:
        result = conn.execute(
            sa.select(privileges_table.c.privilege_id).where(
                privileges_table.c.name == priv["name"]
            )
        ).fetchone()

        if result:
            privilege_ids[priv["name"]] = result[0]
        else:
            priv_id = str(uuid4())
            conn.execute(
                privileges_table.insert().values(
                    privilege_id=priv_id,
                    name=priv["name"],
                    description=priv["description"],
                )
            )
            privilege_ids[priv["name"]] = priv_id

    # Add all Zone privileges to the User role
    user_role = conn.execute(
        sa.select(roles_table.c.role_id).where(
            roles_table.c.name == "User"
        )
    ).fetchone()

    if user_role:
        user_role_id = user_role[0]
        for priv_name in ("Zone.Allocate", "Zone.Audit", "Zone.Modify"):
            conn.execute(
                privilege_role_map.insert().values(
                    privilege_id=privilege_ids[priv_name],
                    role_id=user_role_id,
                )
            )

    # Add Zone.Audit to the Auditor role
    auditor_role = conn.execute(
        sa.select(roles_table.c.role_id).where(
            roles_table.c.name == "Auditor"
        )
    ).fetchone()

    if auditor_role:
        conn.execute(
            privilege_role_map.insert().values(
                privilege_id=privilege_ids["Zone.Audit"],
                role_id=auditor_role[0],
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    for role_name in ("User", "Auditor"):
        role = conn.execute(
            sa.select(roles_table.c.role_id).where(
                roles_table.c.name == role_name
            )
        ).fetchone()

        if role:
            for priv_name in ("Zone.Allocate", "Zone.Audit", "Zone.Modify"):
                priv = conn.execute(
                    sa.select(privileges_table.c.privilege_id).where(
                        privileges_table.c.name == priv_name
                    )
                ).fetchone()
                if priv:
                    conn.execute(
                        privilege_role_map.delete().where(
                            privilege_role_map.c.privilege_id == priv[0],
                            privilege_role_map.c.role_id == role[0],
                        )
                    )

    for priv_name in ("Zone.Allocate", "Zone.Audit", "Zone.Modify"):
        conn.execute(
            privileges_table.delete().where(
                privileges_table.c.name == priv_name
            )
        )
