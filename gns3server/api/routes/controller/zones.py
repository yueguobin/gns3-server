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

"""
API routes for zones.
"""

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from typing import List
from uuid import UUID

from gns3server.controller import Controller
from gns3server.controller.controller_error import ControllerError
from gns3server.db.repositories.rbac import RbacRepository
from gns3server import schemas

from .dependencies.database import get_repository
from .dependencies.rbac import has_privilege

responses = {404: {"model": schemas.ErrorMessage, "description": "Project or zone not found"}}

router = APIRouter(responses=responses)


def _check_drawing_binding(project, drawing_id, zone_id=None) -> None:
    """
    A drawing used as the visual representation of a zone must exist and
    cannot be bound to another zone.
    """

    project.get_drawing(str(drawing_id))
    for other_zone in project.zones.values():
        if other_zone.drawing_id == str(drawing_id) and other_zone.id != zone_id:
            raise ControllerError(
                f"Drawing {drawing_id} is already the visual representation of zone {other_zone.id}"
            )


@router.get(
    "",
    response_model=List[schemas.Zone],
    response_model_exclude_unset=True,
    dependencies=[Depends(has_privilege("Zone.Audit"))]
)
async def get_zones(project_id: UUID) -> List[schemas.Zone]:
    """
    Return the list of all zones for a given project.

    Required privilege: Zone.Audit
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    if project.status == "closed":
        # allow to retrieve zones from a closed project
        return project.zones.values()
    return [z.asdict() for z in project.zones.values()]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Zone,
    response_model_exclude_unset=True,
    dependencies=[Depends(has_privilege("Zone.Allocate"))]
)
async def create_zone(project_id: UUID, zone_data: schemas.ZoneCreate) -> schemas.Zone:
    """
    Create a new zone.

    Required privilege: Zone.Allocate
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone_properties = jsonable_encoder(zone_data, exclude_unset=True)
    if zone_properties.get("drawing_id"):
        _check_drawing_binding(project, zone_properties["drawing_id"])
    zone = await project.add_zone(**zone_properties)
    return zone.asdict()


@router.get(
    "/{zone_id}",
    response_model=schemas.Zone,
    response_model_exclude_unset=True,
    dependencies=[Depends(has_privilege("Zone.Audit"))]
)
async def get_zone(project_id: UUID, zone_id: UUID) -> schemas.Zone:
    """
    Return a zone.

    Required privilege: Zone.Audit
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    return zone.asdict()


@router.get(
    "/{zone_id}/topology",
    response_model=schemas.ZoneTopology,
    response_model_exclude_unset=True,
    dependencies=[Depends(has_privilege("Zone.Audit"))]
)
async def get_zone_topology(project_id: UUID, zone_id: UUID) -> schemas.ZoneTopology:
    """
    Return the sub-topology of a zone: its member nodes, the links internal
    to the zone and the links crossing the zone boundary (with the node on
    the far side inlined in remote_node). A link between two zones is a
    boundary link for both of them.

    Required privilege: Zone.Audit
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    member_ids = set(zone.node_ids)

    nodes = []
    missing_node_ids = []
    for node_id in zone.node_ids:
        node = project.nodes.get(node_id)
        if node is None:
            # tolerate stale references: report them instead of failing
            missing_node_ids.append(node_id)
        else:
            nodes.append(node.asdict())

    links = []
    boundary_links = []
    for link in project.links.values():
        endpoint_ids = {n.id for n in link.nodes}
        if not endpoint_ids.intersection(member_ids):
            continue  # link entirely outside of the zone
        if endpoint_ids.issubset(member_ids):
            links.append(link.asdict())
        else:
            remote_node = next(n for n in link.nodes if n.id not in member_ids)
            boundary_links.append({**link.asdict(), "remote_node": remote_node.asdict()})

    return {
        "zone": zone.asdict(),
        "nodes": nodes,
        "links": links,
        "boundary_links": boundary_links,
        "missing_node_ids": missing_node_ids,
    }


@router.put(
    "/{zone_id}",
    response_model=schemas.Zone,
    response_model_exclude_unset=True,
    dependencies=[Depends(has_privilege("Zone.Modify"))]
)
async def update_zone(project_id: UUID, zone_id: UUID, zone_data: schemas.ZoneUpdate) -> schemas.Zone:
    """
    Update a zone. Node IDs, when present, replace the member list wholesale.

    Required privilege: Zone.Modify
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    zone_properties = jsonable_encoder(zone_data, exclude_unset=True)
    if zone_properties.get("drawing_id"):
        _check_drawing_binding(project, zone_properties["drawing_id"], zone_id=str(zone.id))
    await zone.update(**zone_properties)
    return zone.asdict()


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Zone.Allocate"))]
)
async def delete_zone(
        project_id: UUID,
        zone_id: UUID,
        rbac_repo: RbacRepository = Depends(get_repository(RbacRepository))
) -> None:
    """
    Delete a zone. The member nodes themselves are not touched.

    Required privilege: Zone.Allocate
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    await project.delete_zone(str(zone_id))
    await rbac_repo.delete_all_ace_starting_with_path(f"/zones/{zone_id}")
