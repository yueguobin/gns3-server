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
#

import uuid

import logging

log = logging.getLogger(__name__)


class Zone:
    """
    A zone is a named group of nodes, used to work on one part of a big
    topology. Zones are pure data: they are not used by the network
    emulation and never sent to computes. Membership is an explicit list
    of node IDs, optionally shown on the scene by a bound drawing.
    """

    def __init__(self, project, zone_id=None, name=None, description=None, color=None,
                 node_ids=None, drawing_id=None, parent_zone_id=None):
        self._project = project
        if zone_id is None:
            self._id = str(uuid.uuid4())
        else:
            self._id = zone_id
        self._name = name
        self._description = description
        self._color = color
        self._node_ids = list(node_ids) if node_ids else []
        self._drawing_id = drawing_id
        self._parent_zone_id = parent_zone_id

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, val):
        self._description = val

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, val):
        self._color = val

    @property
    def node_ids(self):
        return self._node_ids

    @node_ids.setter
    def node_ids(self, val):
        self._node_ids = list(val) if val else []

    @property
    def drawing_id(self):
        return self._drawing_id

    @drawing_id.setter
    def drawing_id(self, val):
        self._drawing_id = val

    @property
    def parent_zone_id(self):
        return self._parent_zone_id

    @parent_zone_id.setter
    def parent_zone_id(self, val):
        self._parent_zone_id = val

    async def update(self, **kwargs):
        """
        Update the zone.

        :param kwargs: Zone properties
        """

        for prop in kwargs:
            if prop == "zone_id":
                pass  # No good reason to change a zone_id
            elif getattr(self, prop) != kwargs[prop]:
                setattr(self, prop, kwargs[prop])
        self._project.emit_notification("zone.updated", self.asdict())
        self._project.dump()

    def asdict(self, topology_dump=False):
        """
        :param topology_dump: Filter to keep only properties require for saving on disk
        """

        if topology_dump:
            return {
                "zone_id": self._id,
                "name": self._name,
                "description": self._description,
                "color": self._color,
                "node_ids": self._node_ids,
                "drawing_id": self._drawing_id,
                "parent_zone_id": self._parent_zone_id,
            }
        return {
            "project_id": self._project.id,
            "zone_id": self._id,
            "name": self._name,
            "description": self._description,
            "color": self._color,
            "node_ids": self._node_ids,
            "drawing_id": self._drawing_id,
            "parent_zone_id": self._parent_zone_id,
        }

    def __repr__(self):
        return f"<gns3server.controller.Zone {self._id}>"
