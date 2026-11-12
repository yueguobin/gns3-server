"""Add the Server.Audit and Server.Modify privileges.

The server settings API (GET/PUT /v3/settings) is gated by the Server.Audit
and Server.Modify privileges. They were only added to the seed list that runs
when the privileges table is first created, so databases created before that
change have no such rows. The superadmin privilege list returned by
GET /access/users/me/privileges comes straight from that table, and the web
UI hides the server settings entry when the rows are missing. Backfill both
privileges and attach them to the built-in "Administrator" role to match new
databases.

Revision ID: a43d55900514
Revises: f3a7c1e9b5d2
"""

import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "a43d55900514"
down_revision = "f3a7c1e9b5d2"
branch_labels = None
depends_on = None

log = logging.getLogger(__name__)

# keep in sync with create_default_roles in gns3server/db/models/privileges.py
PRIVILEGES = (
    ("Server.Audit", "View server settings"),
    ("Server.Modify", "Update server settings"),
)


def upgrade():
    """
    Insert the privileges when missing and attach them to the "Administrator"
    role. Administrators keep every privilege, exactly like on a new database.
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
                " WHERE p.name = :name AND r.name = 'Administrator'"
                " AND NOT EXISTS ("
                " SELECT 1 FROM privilege_role_map m WHERE m.privilege_id = p.privilege_id AND m.role_id = r.role_id)"
            ),
            {"name": name},
        )
        log.info(f"Added the '{name}' privilege and attached it to {result.rowcount} 'Administrator' role(s)")


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
