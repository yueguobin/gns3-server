"""Add the Link.Marker and Project.Marker privileges.

The marker write endpoints (per-link markers and project-level marker
definitions) used to be gated by Link.Modify and Project.Modify. They now
have their own privileges, so a user can manage markers without holding
topology-write privileges: the built-in "Lab member" role (users who
received a distributed lab project) gets both marker privileges but still
no Link.Modify or Project.Modify.

Backfill both privileges on databases created before this change and attach
them to the "Administrator", "User" and "Lab member" roles to match new
databases. Custom roles that only hold Link.Modify or Project.Modify do not
gain the new privileges: an administrator has to add them by hand.

Revision ID: ed99f4cfc26f
Revises: a43d55900514
"""

import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "ed99f4cfc26f"
down_revision = "a43d55900514"
branch_labels = None
depends_on = None

log = logging.getLogger(__name__)

# keep in sync with create_default_roles in gns3server/db/models/privileges.py
PRIVILEGES = (
    ("Link.Marker", "Manage traffic markers on a link"),
    ("Project.Marker", "Manage project-level marker definitions"),
)
ROLE_NAMES = ("Administrator", "User", "Lab member")


def upgrade():
    """
    Insert the privileges when missing and attach them to the built-in roles
    that should hold them. Roles already bearing the privileges keep them.
    """

    connection = op.get_bind()
    for name, description in PRIVILEGES:
        connection.execute(
            sa.text(
                "INSERT INTO privileges (privilege_id, name, description)"
                " SELECT :privilege_id, :name, :description"
                " WHERE NOT EXISTS (SELECT 1 FROM privileges WHERE name = :name)"
            ),
            {"privilege_id": uuid.uuid4().hex, "name": name, "description": description},
        )
        result = connection.execute(
            sa.text(
                "INSERT INTO privilege_role_map (privilege_id, role_id)"
                " SELECT p.privilege_id, r.role_id FROM privileges p, roles r"
                " WHERE p.name = :name AND r.name IN :roles"
                " AND NOT EXISTS ("
                " SELECT 1 FROM privilege_role_map m WHERE m.privilege_id = p.privilege_id AND m.role_id = r.role_id)"
            ).bindparams(sa.bindparam("roles", expanding=True)),
            {"name": name, "roles": list(ROLE_NAMES)},
        )
        log.info(f"Added the '{name}' privilege and attached it to {result.rowcount} role(s)")


def downgrade():
    """
    Remove the role attachments, then the privileges. Custom roles an
    administrator built around them are left as they are.
    """

    connection = op.get_bind()
    for name, _description in PRIVILEGES:
        connection.execute(
            sa.text(
                "DELETE FROM privilege_role_map WHERE privilege_id ="
                " (SELECT privilege_id FROM privileges WHERE name = :name)"
            ),
            {"name": name},
        )
        connection.execute(sa.text("DELETE FROM privileges WHERE name = :name"), {"name": name})
        log.info(f"Removed the '{name}' privilege")
