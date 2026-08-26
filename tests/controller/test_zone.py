#!/usr/bin/env python
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

from unittest.mock import MagicMock
import pytest
import uuid
import json

from tests.utils import AsyncioMagicMock

from gns3server.controller.zone import Zone
from gns3server.controller.drawing import Drawing


@pytest.fixture
def zone(project):

    return Zone(project, None, name="site-A")


def test_init_without_uuid(project):

    zone = Zone(project, None, name="test")
    assert zone.id is not None


def test_init_with_uuid(project):

    id = str(uuid.uuid4())
    zone = Zone(project, id, name="test")
    assert zone.id == id


def test_json(project):

    zone = Zone(
        project, None,
        name="site-A",
        description="Branch site A",
        color="#4A90D9",
        node_ids=["node1", "node2"],
        drawing_id="drawing1",
    )
    assert zone.asdict() == {
        "project_id": project.id,
        "zone_id": zone.id,
        "name": "site-A",
        "description": "Branch site A",
        "color": "#4A90D9",
        "node_ids": ["node1", "node2"],
        "drawing_id": "drawing1",
        "parent_zone_id": None,
    }
    assert zone.asdict(topology_dump=True) == {
        "zone_id": zone.id,
        "name": "site-A",
        "description": "Branch site A",
        "color": "#4A90D9",
        "node_ids": ["node1", "node2"],
        "drawing_id": "drawing1",
        "parent_zone_id": None,
    }


def test_node_ids_defensive_copy(project):
    """
    Mutating the list passed at init or to the setter must not leak into the zone
    """

    ids = ["node1"]
    zone = Zone(project, None, name="test", node_ids=ids)
    ids.append("node2")
    assert zone.node_ids == ["node1"]

    ids = ["node1"]
    zone.node_ids = ids
    ids.append("node2")
    assert zone.node_ids == ["node1"]


@pytest.mark.asyncio
async def test_update(zone, project, controller):

    controller._notification = AsyncioMagicMock()
    project.dump = MagicMock()

    await zone.update(name="site-B", node_ids=["node3"])
    assert zone.name == "site-B"
    assert zone.node_ids == ["node3"]
    args, kwargs = controller._notification.project_emit.call_args
    assert args[0] == "zone.updated"
    assert args[1]["name"] == "site-B"
    assert args[1]["node_ids"] == ["node3"]
    assert project.dump.called


@pytest.mark.asyncio
async def test_delete_node_removes_zone_membership(controller, project, compute):

    response = MagicMock()
    response.json = {"console": 2048}
    compute.post = AsyncioMagicMock(return_value=response)

    node = await project.add_node(compute, "n1", None, node_type="qemu")
    zone = await project.add_zone(name="z1", node_ids=[node.id])
    node.destroy = AsyncioMagicMock()

    await project.delete_node(node.id)
    assert zone.node_ids == []
    assert zone.id in project._zones  # the zone itself survives


@pytest.mark.asyncio
async def test_delete_drawing_unbinds_zone(project):

    drawing = Drawing(project)
    project._drawings = {drawing.id: drawing}
    zone = await project.add_zone(name="z1", drawing_id=drawing.id)

    await project.delete_drawing(drawing.id)
    assert zone.drawing_id is None
    assert zone.id in project._zones  # the zone survives as pure data


@pytest.mark.asyncio
async def test_zone_persisted_in_topology_file(controller, project):

    node_id = str(uuid.uuid4())
    zone = await project.add_zone(name="site-A", node_ids=[node_id], color="#4A90D9")
    with open(project._topology_file()) as f:
        topology = json.load(f)
    assert topology["topology"]["zones"] == [zone.asdict(topology_dump=True)]


@pytest.mark.asyncio
async def test_set_node_zones(controller, project, compute):
    """
    Node-side write-through: replace the node's memberships across zones,
    no-op when nothing changes, 404 on unknown zone
    """

    response = MagicMock()
    response.json = {"console": 2048}
    compute.post = AsyncioMagicMock(return_value=response)

    from gns3server.controller.controller_error import ControllerNotFoundError

    node = await project.add_node(compute, "n1", None, node_type="qemu")
    z1 = await project.add_zone(name="z1")
    z2 = await project.add_zone(name="z2")

    controller._notification = AsyncioMagicMock()
    project.dump = MagicMock()

    await project.set_node_zones(node, [z1.id])
    assert z1.node_ids == [node.id]
    assert z2.node_ids == []

    # move to z2: added there, removed from z1, both notified
    await project.set_node_zones(node, [z2.id])
    assert z1.node_ids == []
    assert z2.node_ids == [node.id]
    notified = [args[0] for args, _ in controller._notification.project_emit.call_args_list]
    assert notified.count("zone.updated") == 3  # first move adds to one zone, second moves across two

    # no-op: no dump, no notification
    project.dump.reset_mock()
    controller._notification.project_emit.reset_mock()
    await project.set_node_zones(node, [z2.id])
    assert not project.dump.called
    assert not controller._notification.project_emit.called

    # unknown zone -> 404
    with pytest.raises(ControllerNotFoundError):
        await project.set_node_zones(node, [str(uuid.uuid4())])


@pytest.mark.asyncio
async def test_zone_subtree(project):
    """
    Subtree walk: union of members, descendant list, cycle guard
    """

    n1, n2, n3, n4 = (str(uuid.uuid4()) for _ in range(4))
    parent = await project.add_zone(name="parent", node_ids=[n1])
    child = await project.add_zone(name="child", node_ids=[n2], parent_zone_id=parent.id)
    grandchild = await project.add_zone(name="grandchild", node_ids=[n3], parent_zone_id=child.id)
    other = await project.add_zone(name="other", node_ids=[n4])

    node_ids, descendants = project.zone_subtree(parent)
    assert node_ids == {n1, n2, n3}
    assert set(descendants) == {child.id, grandchild.id}

    node_ids, descendants = project.zone_subtree(other)
    assert node_ids == {n4}
    assert descendants == []

    # hand-wired cycle (e.g. hand-edited .gns3) must not hang the walk
    other.parent_zone_id = parent.id
    parent.parent_zone_id = other.id
    node_ids, _ = project.zone_subtree(parent)
    assert n4 in node_ids
