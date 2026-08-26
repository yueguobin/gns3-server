#
# Copyright (C) 2026 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

from .links import Link
from .nodes import Node


class ZoneBase(BaseModel):
    """
    Zone data.

    A zone is a named group of nodes used to work on one part of a big
    topology (e.g. "core", "access", "branch site A"). Unlike node tags,
    zones have an identity, their own lifecycle and can carry a visual
    representation. Membership is an explicit list of node IDs: moving
    a node on the scene never changes its zone.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=1024)
    color: Optional[str] = Field(
        None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Zone color, e.g. '#4A90D9'",
    )
    node_ids: Optional[List[UUID]] = Field(
        None,
        description="Node IDs belonging to this zone. A node may belong to several zones",
    )
    drawing_id: Optional[UUID] = Field(
        None,
        description=(
            "Optional drawing (rectangle, ellipse...) used as the visual "
            "representation of this zone. The drawing is just the picture, "
            "membership stays in node_ids"
        ),
    )


class ZoneCreate(ZoneBase):

    name: str = Field(..., min_length=1, max_length=64)
    node_ids: List[UUID] = Field(default_factory=list)


class ZoneUpdate(ZoneBase):

    pass


class Zone(ZoneBase):

    zone_id: UUID
    project_id: Optional[UUID] = None
    name: str
    node_ids: List[UUID] = Field(default_factory=list)


class ZoneBoundaryLink(Link):
    """
    A link with one endpoint inside the zone and one endpoint outside.

    The full node outside the zone is inlined in remote_node so a client
    (or an AI agent) gets everything in a single response.
    """

    remote_node: Node


class ZoneTopology(BaseModel):
    """
    The sub-topology of a zone: member nodes, links internal to the zone
    and links crossing the zone boundary. A link between two zones is a
    boundary link for both of them.
    """

    zone: Zone
    nodes: List[Node] = Field(default_factory=list, description="Nodes belonging to the zone")
    links: List[Link] = Field(default_factory=list, description="Links with both endpoints inside the zone")
    boundary_links: List[ZoneBoundaryLink] = Field(
        default_factory=list,
        description="Links with exactly one endpoint inside the zone, remote_node is the far end",
    )
    missing_node_ids: List[UUID] = Field(
        default_factory=list,
        description="Zone members which no longer exist in the project (stale references)",
    )
