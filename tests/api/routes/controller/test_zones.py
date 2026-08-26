# -*- coding: utf-8 -*-
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

import pytest
import pytest_asyncio

from typing import List, Tuple
from unittest.mock import MagicMock
from fastapi import FastAPI, status
from httpx import AsyncClient

from tests.utils import AsyncioMagicMock

from gns3server.controller.project import Project
from gns3server.controller.compute import Compute
from gns3server.controller.node import Node
from gns3server.controller.ports.ethernet_port import EthernetPort

pytestmark = pytest.mark.asyncio


class TestZonesRoutes:

    @pytest_asyncio.fixture
    async def nodes(self, compute: Compute, project: Project) -> Tuple[Node, Node, Node]:
        """
        Three nodes A, B, C — each with two free Ethernet ports
        """

        response = MagicMock()
        response.json = {"console": 2048}
        compute.post = AsyncioMagicMock(return_value=response)

        nodes = []
        for name in ("A", "B", "C"):
            node = await project.add_node(compute, name, None, node_type="qemu")
            node._ports = [EthernetPort("E0", 0, 0, 0), EthernetPort("E1", 0, 0, 1)]
            nodes.append(node)
        return tuple(nodes)

    @pytest_asyncio.fixture
    async def links(self, project: Project, nodes: Tuple[Node, Node, Node]) -> List:
        """
        A fully meshed A-B, A-C, B-C
        """

        node_a, node_b, node_c = nodes

        async def add_link(node1, port1, node2, port2):
            link = await project.add_link(dump=False)
            await link.add_node(node1, 0, port1, dump=False, batch=True)
            await link.add_node(node2, 0, port2, dump=False, batch=True)
            return link

        link_ab = await add_link(node_a, 0, node_b, 0)
        link_ac = await add_link(node_a, 1, node_c, 0)
        link_bc = await add_link(node_b, 1, node_c, 1)
        return [link_ab, link_ac, link_bc]

    async def test_create_zone(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        params = {
            "name": "site-A",
            "description": "Branch site A",
            "color": "#4A90D9",
            "node_ids": []
        }
        response = await client.post(app.url_path_for("create_zone", project_id=project.id), json=params)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["zone_id"] is not None
        assert response.json()["name"] == "site-A"
        assert response.json()["color"] == "#4A90D9"

    async def test_create_zone_invalid_color(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "site-A", "color": "red"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_create_zone_empty_name(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": ""}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_get_zone(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "site-A", "node_ids": []}
        )
        zone_id = response.json()["zone_id"]
        response = await client.get(app.url_path_for("get_zone", project_id=project.id, zone_id=zone_id))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "site-A"

    async def test_get_unknown_zone(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.get(
            app.url_path_for("get_zone", project_id=project.id, zone_id="5b1d6b32-5a1d-4c3d-9c3e-1f2a9c3e5d7f")
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_update_zone(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "site-A", "node_ids": []}
        )
        zone_id = response.json()["zone_id"]
        response = await client.put(
            app.url_path_for("update_zone", project_id=project.id, zone_id=zone_id),
            json={"name": "site-B", "color": "#FF5722"}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "site-B"
        assert response.json()["color"] == "#FF5722"

    async def test_zone_list(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        await client.post(app.url_path_for("create_zone", project_id=project.id), json={"name": "site-A"})
        response = await client.get(app.url_path_for("get_zones", project_id=project.id))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

        # test listing zones from a closed project
        await project.close(ignore_notification=True)
        response = await client.get(app.url_path_for("get_zones", project_id=project.id))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    async def test_delete_zone(self, app: FastAPI, client: AsyncClient, project: Project) -> None:

        response = await client.post(app.url_path_for("create_zone", project_id=project.id), json={"name": "site-A"})
        zone_id = response.json()["zone_id"]
        response = await client.delete(app.url_path_for("delete_zone", project_id=project.id, zone_id=zone_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        response = await client.get(app.url_path_for("get_zone", project_id=project.id, zone_id=zone_id))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_drawing_binding_conflict(
            self,
            app: FastAPI,
            client: AsyncClient,
            project: Project
    ) -> None:
        """
        A drawing can be the visual representation of at most one zone
        """

        response = await client.post(
            app.url_path_for("create_drawing", project_id=project.id),
            json={"svg": "<svg><rect width=\"10\" height=\"10\"/></svg>"}
        )
        drawing_id = response.json()["drawing_id"]

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z1", "drawing_id": drawing_id}
        )
        assert response.status_code == status.HTTP_201_CREATED

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z2", "drawing_id": drawing_id}
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_zone_topology(
            self,
            app: FastAPI,
            client: AsyncClient,
            project: Project,
            nodes: Tuple[Node, Node, Node],
            links: List
    ) -> None:
        """
        zone1 = {A, B}: internal link A-B, boundary links to C
        zone2 = {B, C}: internal link B-C, boundary links to A
        The cross-zone links A-C and B-C must appear in both zones' results
        """

        node_a, node_b, node_c = nodes

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z1", "node_ids": [node_a.id, node_b.id]}
        )
        zone1_id = response.json()["zone_id"]
        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z2", "node_ids": [node_b.id, node_c.id]}
        )
        zone2_id = response.json()["zone_id"]

        response = await client.get(
            app.url_path_for("get_zone_topology", project_id=project.id, zone_id=zone1_id)
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["zone"]["zone_id"] == zone1_id
        assert {n["node_id"] for n in data["nodes"]} == {node_a.id, node_b.id}
        # only A-B is internal to zone1
        assert len(data["links"]) == 1
        assert {n["node_id"] for n in data["links"][0]["nodes"]} == {node_a.id, node_b.id}
        # A-C and B-C cross the boundary, C is the far end of both
        assert len(data["boundary_links"]) == 2
        assert {bl["remote_node"]["node_id"] for bl in data["boundary_links"]} == {node_c.id}
        assert data["missing_node_ids"] == []

        response = await client.get(
            app.url_path_for("get_zone_topology", project_id=project.id, zone_id=zone2_id)
        )
        data = response.json()
        assert {n["node_id"] for n in data["nodes"]} == {node_b.id, node_c.id}
        assert len(data["links"]) == 1
        assert {n["node_id"] for n in data["links"][0]["nodes"]} == {node_b.id, node_c.id}
        # A-C and B-C from zone2's point of view: A is the far end of both
        assert len(data["boundary_links"]) == 2
        assert {bl["remote_node"]["node_id"] for bl in data["boundary_links"]} == {node_a.id}

    async def test_zone_topology_stale_node(
            self,
            app: FastAPI,
            client: AsyncClient,
            project: Project
    ) -> None:
        """
        A member which no longer exists is reported in missing_node_ids, not an error
        """

        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z1", "node_ids": ["9f1d6b32-5a1d-4c3d-9c3e-1f2a9c3e5d7f"]}
        )
        zone_id = response.json()["zone_id"]
        response = await client.get(
            app.url_path_for("get_zone_topology", project_id=project.id, zone_id=zone_id)
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["nodes"] == []
        assert data["missing_node_ids"] == ["9f1d6b32-5a1d-4c3d-9c3e-1f2a9c3e5d7f"]

    async def test_zone_delete_node_shrinks_membership(
            self,
            app: FastAPI,
            client: AsyncClient,
            project: Project,
            compute: Compute,
            nodes: Tuple[Node, Node, Node]
    ) -> None:
        """
        Deleting a member node removes it from its zones (the zone itself survives)
        """

        node_a, node_b, _ = nodes
        response = await client.post(
            app.url_path_for("create_zone", project_id=project.id),
            json={"name": "z1", "node_ids": [node_a.id, node_b.id]}
        )
        zone_id = response.json()["zone_id"]

        node_a.destroy = AsyncioMagicMock()
        response = await client.delete(
            app.url_path_for("delete_node", project_id=project.id, node_id=node_a.id)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = await client.get(app.url_path_for("get_zone", project_id=project.id, zone_id=zone_id))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["node_ids"] == [node_b.id]
