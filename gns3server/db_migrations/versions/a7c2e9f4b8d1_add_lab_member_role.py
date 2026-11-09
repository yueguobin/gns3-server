"""Add the built-in "Lab member" role.

A project can be duplicated to another user (distribution): the copy is owned
by that user and its owner ACE carries a reduced role, so the recipient can
use the lab (console, power management, capture, restore a snapshot) without
being able to modify the topology. The built-in "Lab member" role is the
default role for those copies.

The role only receives privileges scoped to a project path, which is all an
ACE on /projects/<project_id> can reach.

Revision ID: a7c2e9f4b8d1
Revises: d4f1b8c2a6e3
"""

import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "a7c2e9f4b8d1"
down_revision = "d4f1b8c2a6e3"
branch_labels = None
depends_on = None

log = logging.getLogger(__name__)

# keep in sync with add_privileges_to_default_roles in gns3server/db/models/privileges.py
ROLE_NAME = "Lab member"
ROLE_DESCRIPTION = "Role for users who received a distributed lab project"
ROLE_PRIVILEGES = (
    "Project.Allocate",
    "Project.Audit",
    "Snapshot.Audit",
    "Snapshot.Restore",
    "Node.Audit",
    "Node.Console",
    "Node.PowerMgmt",
    "Link.Audit",
    "Link.Capture",
    "Drawing.Audit",
)


def upgrade():
    """
    Insert the role when missing and attach its privileges. A role already
    bearing the name keeps its identity; the privileges are attached when
    missing, exactly like for the built-in roles on a new database.
    """

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO roles (role_id, name, description, is_builtin)"
            " SELECT :role_id, :name, :description, 1"
            " WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = :name)"
        ),
        {"role_id": uuid.uuid4().hex, "name": ROLE_NAME, "description": ROLE_DESCRIPTION},
    )
    result = connection.execute(
        sa.text(
            "INSERT INTO privilege_role_map (privilege_id, role_id)"
            " SELECT p.privilege_id, r.role_id FROM privileges p, roles r"
            " WHERE r.name = :role AND p.name IN :privileges"
            " AND NOT EXISTS ("
            " SELECT 1 FROM privilege_role_map m WHERE m.privilege_id = p.privilege_id AND m.role_id = r.role_id)"
        ).bindparams(sa.bindparam("privileges", expanding=True)),
        {"role": ROLE_NAME, "privileges": list(ROLE_PRIVILEGES)},
    )
    log.info(f"Added the '{ROLE_NAME}' role with {result.rowcount} privilege(s)")


def downgrade():
    """
    Remove the role. The privilege_role_map rows follow the foreign key
    cascade; ACEs referencing the role are left to the administrator.
    """

    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM roles WHERE name = :name"), {"name": ROLE_NAME})
    log.info(f"Removed the '{ROLE_NAME}' role")
