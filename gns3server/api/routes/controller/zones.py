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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from typing import List
from uuid import UUID

from gns3server.utils.asyncio.pool import Pool

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


def _check_parent_zone(project, parent_zone_id, zone_id=None) -> None:
    """
    A parent zone must exist, cannot be the zone itself and cannot be one of
    its descendants (that would create a cycle).
    """

    parent = project.get_zone(str(parent_zone_id))
    if zone_id and parent.id == str(zone_id):
        raise ControllerError(f"Zone {zone_id} cannot be its own parent")
    if zone_id:
        ancestor = parent
        while ancestor is not None:
            if ancestor.id == str(zone_id):
                raise ControllerError(f"Zone {zone_id} cannot be a parent of one of its ancestors")
            ancestor = project.zones.get(ancestor.parent_zone_id) if ancestor.parent_zone_id else None


def _zone_member_nodes(project, zone, recursive: bool):
    """
    The node IDs a zone covers — its own members, plus the members of all
    descendant zones when recursive. Returns (member_ids, sub_zone_ids).
    """

    if not recursive:
        return set(zone.node_ids), []
    return project.zone_subtree(zone)


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
    if zone_properties.get("parent_zone_id"):
        _check_parent_zone(project, zone_properties["parent_zone_id"])
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
async def get_zone_topology(
        project_id: UUID,
        zone_id: UUID,
        recursive: bool = Query(False, description="Fold member nodes of all descendant zones in")
) -> schemas.ZoneTopology:
    """
    Return the sub-topology of a zone: its member nodes, the links internal
    to the zone and the links crossing the zone boundary (with the node on
    the far side inlined in remote_node). A link between two zones is a
    boundary link for both of them.

    With recursive=true the members of all descendant zones are folded in
    (sub_zone_ids lists them).

    Required privilege: Zone.Audit
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    member_ids, sub_zone_ids = _zone_member_nodes(project, zone, recursive)

    nodes = []
    missing_node_ids = []
    for node_id in member_ids:
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
        "sub_zone_ids": sub_zone_ids,
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
    if zone_properties.get("parent_zone_id"):
        _check_parent_zone(project, zone_properties["parent_zone_id"], zone_id=str(zone.id))
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


@router.post(
    "/{zone_id}/nodes",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Zone.Modify"))]
)
async def add_node_to_zone(project_id: UUID, zone_id: UUID, member: schemas.ZoneMember) -> None:
    """
    Add a single node to a zone. Idempotent: adding an existing member is a no-op.

    Required privilege: Zone.Modify
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    project.get_node(str(member.node_id))  # 404 if the node doesn't exist
    if str(member.node_id) not in zone.node_ids:
        zone.node_ids = zone.node_ids + [str(member.node_id)]
        project.dump()
        project.emit_notification("zone.updated", zone.asdict())


@router.delete(
    "/{zone_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Zone.Modify"))]
)
async def remove_node_from_zone(project_id: UUID, zone_id: UUID, node_id: UUID) -> None:
    """
    Remove a single node from a zone. Idempotent; the node itself is not
    touched. Also usable to clean up stale member references.

    Required privilege: Zone.Modify
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    if str(node_id) in zone.node_ids:
        zone.node_ids = [nid for nid in zone.node_ids if nid != str(node_id)]
        project.dump()
        project.emit_notification("zone.updated", zone.asdict())


async def _zone_lifecycle(project, zone, recursive: bool, action: str) -> None:
    """
    Run a lifecycle action (start/stop/suspend) on the nodes of a zone,
    mirroring the project-level bulk endpoints.
    """

    member_ids, _ = _zone_member_nodes(project, zone, recursive)
    nodes = [
        n for nid in member_ids
        if (n := project.nodes.get(nid)) is not None and not n.is_always_running()
    ]
    if not nodes:
        return
    pool = Pool(concurrency=10)
    for node in nodes:
        pool.append(getattr(node, action))
    await pool.join()


@router.post(
    "/{zone_id}/nodes/start",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Node.PowerMgmt"))]
)
async def start_zone_nodes(
        project_id: UUID,
        zone_id: UUID,
        recursive: bool = Query(False, description="Also start nodes of descendant zones")
) -> None:
    """
    Start all nodes in a zone.

    Required privilege: Node.PowerMgmt
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    try:
        await _zone_lifecycle(project, zone, recursive, "start")
    except HTTPException as e:
        if e.status_code != status.HTTP_405_METHOD_NOT_ALLOWED:
            raise


@router.post(
    "/{zone_id}/nodes/stop",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Node.PowerMgmt"))]
)
async def stop_zone_nodes(
        project_id: UUID,
        zone_id: UUID,
        recursive: bool = Query(False, description="Also stop nodes of descendant zones")
) -> None:
    """
    Stop all nodes in a zone.

    Required privilege: Node.PowerMgmt
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    try:
        await _zone_lifecycle(project, zone, recursive, "stop")
    except HTTPException as e:
        if e.status_code != status.HTTP_405_METHOD_NOT_ALLOWED:
            raise


@router.post(
    "/{zone_id}/nodes/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Node.PowerMgmt"))]
)
async def suspend_zone_nodes(
        project_id: UUID,
        zone_id: UUID,
        recursive: bool = Query(False, description="Also suspend nodes of descendant zones")
) -> None:
    """
    Suspend all nodes in a zone.

    Required privilege: Node.PowerMgmt
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    try:
        await _zone_lifecycle(project, zone, recursive, "suspend")
    except HTTPException as e:
        if e.status_code != status.HTTP_405_METHOD_NOT_ALLOWED:
            raise


@router.post(
    "/{zone_id}/nodes/reload",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_privilege("Node.PowerMgmt"))]
)
async def reload_zone_nodes(
        project_id: UUID,
        zone_id: UUID,
        recursive: bool = Query(False, description="Also reload nodes of descendant zones")
) -> None:
    """
    Reload (stop then start) all nodes in a zone.

    Required privilege: Node.PowerMgmt
    """

    project = await Controller.instance().get_loaded_project(str(project_id))
    zone = project.get_zone(str(zone_id))
    try:
        await _zone_lifecycle(project, zone, recursive, "stop")
        await _zone_lifecycle(project, zone, recursive, "start")
    except HTTPException as e:
        if e.status_code != status.HTTP_405_METHOD_NOT_ALLOWED:
            raise
