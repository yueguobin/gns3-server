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
Declarative lab topologies for the e2e scenarios.

A lab spec is a YAML file in ``tests/e2e/topologies/`` written in a
**containerlab-shaped dialect** — the parts of the clab format that describe
structure are borrowed verbatim, the parts that describe how containerlab
runs containers are not, because a GNS3 lab is deployed differently:

* borrowed as-is: the ``name`` + ``topology.{defaults, kinds, nodes,
  links}`` skeleton, the node > kind > defaults resolution order, the short
  link form (``endpoints: ["r1:eth0", "r2:eth0"]]``) and the long one
  (``{node, interface, ipv4, ipv6}`` per endpoint — addresses belong to a
  link's side, not to a node);
* extended: a ``kind`` vocabulary that names the e2e's node families (the
  registry below bundles each family's image pin, node properties, boot
  criterion, config channel and ping parser) and a per-node ``gns3:`` extras
  block for family properties;
* not a clab file: no clab kind, image reference or runtime would mean
  anything here, and ``containerlab deploy`` cannot run these files.

The dialect rejects unknown keys at load time — a typo in a topology fails
before anything is deployed, not half-way through.

Deploying is **phased** on purpose (``deploy`` → ``start`` → ``boot`` →
``configure``): the construction sequence of a lab is itself under test in
several scenarios (the kernel datapath wires a link created while the nodes
are stopped), so the materializer never hides a phase the scenario wants to
assert between.

One rule keeps the tests honest: **this library is a fixture, never a
wrapper around the interfaces under test.** Netem, filters, markers,
suspend, captures and every other REST call the scenario exercises stays a
bare ``compute.call`` in the test file — the library only owns topology
plumbing and measurement helpers, so a server-side regression always shows
up as the raw response it produced.
"""

import ipaddress
import os
import re

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from tests.e2e import harness

TOPOLOGIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topologies")

# Node names double as short-form endpoint hosts ("r1:eth0"), so a colon
# would break the split; anything else the API accepts as a node name is fine.
_NODE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# Spec models (the dialect)
# ---------------------------------------------------------------------------


class _SpecModel(BaseModel):
    """Every spec model rejects unknown keys, like clab's own JSON schema
    does (``additionalProperties: false``): a misspelled key must fail at
    load with the offender named, not deploy half a lab."""

    model_config = ConfigDict(extra="forbid")


class Gns3Extras(_SpecModel):
    """The GNS3-only extension block of a node — nested under ``gns3:`` so
    the clab-shaped keys above it stay clab-shaped. Everything here is
    passed to the family's node creation."""

    adapters: int | None = None


class NodeSpec(_SpecModel):
    """One node. Only the structure lives here; the family behavior (image
    pin, boot criterion, config channel) comes from the kind registry."""

    kind: str = ""
    image: str | None = None
    gns3: Gns3Extras = Gns3Extras()


class EndpointSpec(_SpecModel):
    """One side of a link: the node, its interface, and the addresses the
    interface carries (with their network — a bare address is ambiguous and
    rejected). The materializer applies them through the family's config
    channel and the scenarios ping them."""

    node: str
    interface: str
    ipv4: ipaddress.IPv4Interface | None = None
    ipv6: ipaddress.IPv6Interface | None = None

    @field_validator("ipv4", "ipv6")
    @classmethod
    def _prefix_required(cls, value, info):
        # pydantic accepts a bare address as a /32 (or /128) network — no
        # scenario ever wants that, so demand the prefix explicitly
        max_prefix = 32 if info.field_name == "ipv4" else 128
        if value is not None and value.network.prefixlen == max_prefix:
            raise ValueError(
                f"the {info.field_name} address needs its prefix length (a /{max_prefix} network is never intended)"
            )
        return value


class LinkSpec(_SpecModel):
    """A point-to-point link. The short form (two ``"node:interface"``
    strings) is accepted alongside the long form used for addressed
    endpoints."""

    endpoints: list[EndpointSpec]

    @field_validator("endpoints", mode="before")
    @classmethod
    def _short_form(cls, value):
        if not isinstance(value, list):
            return value
        expanded = []
        for endpoint in value:
            if isinstance(endpoint, str):
                node, separator, interface = endpoint.partition(":")
                if not separator or not node or not interface:
                    raise ValueError(f"endpoint {endpoint!r} is not 'node:interface'")
                expanded.append({"node": node, "interface": interface})
            else:
                expanded.append(endpoint)
        return expanded

    @model_validator(mode="after")
    def _a_pair(self):
        if len(self.endpoints) != 2:
            raise ValueError(f"a link has exactly two endpoints, got {len(self.endpoints)}")
        return self


class TopologySpec(_SpecModel):
    defaults: NodeSpec = NodeSpec()
    kinds: dict[str, NodeSpec] = {}
    nodes: dict[str, NodeSpec]
    links: list[LinkSpec]

    @field_validator("nodes")
    @classmethod
    def _sane_names(cls, value):
        for name in value:
            if not _NODE_NAME_RE.match(name):
                raise ValueError(f"node name {name!r} may not contain a colon or be empty")
        if not value:
            raise ValueError("a topology needs at least one node")
        return value

    @model_validator(mode="after")
    def _wired_correctly(self):
        """Every endpoint names an existing node, and no interface is wired
        twice — the second wire would silently replace the first link on the
        port, so it is a spec bug and must fail at load."""
        seen = set()
        for link in self.links:
            for endpoint in link.endpoints:
                if endpoint.node not in self.nodes:
                    raise ValueError(f"endpoint names unknown node {endpoint.node!r}")
                wired = (endpoint.node, endpoint.interface)
                if wired in seen:
                    raise ValueError(f"{endpoint.node}:{endpoint.interface} is wired twice")
                seen.add(wired)
        return self


class LabSpec(_SpecModel):
    name: str
    topology: TopologySpec


def load(name):
    """Load and validate a lab spec: *name* is a file under
    ``tests/e2e/topologies/`` with or without the ``.yml``, or a path.
    Returns the ``LabSpec``; every problem raises with the file named."""

    path = name
    if not os.path.isfile(path):
        if not path.endswith((".yml", ".yaml")):
            path += ".yml"
        path = os.path.join(TOPOLOGIES_DIR, path)
    if not os.path.isfile(path):
        raise AssertionError(f"no lab spec for {name!r} (looked at {path!r})")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    try:
        return LabSpec.model_validate(raw)
    except ValidationError as e:
        raise AssertionError(f"{path} is not a valid lab spec:\n{e}") from e


# ---------------------------------------------------------------------------
# Kind registry — the node-family driver bundles
# ---------------------------------------------------------------------------


class Kind:
    """Everything the materializer cannot know about a node family, in one
    place: which image (registry-pinned, self-bootstrapping), which node
    properties, how a guest's boot completion is recognized, how addresses
    are applied and measured, and the family's host-side quirks. A new
    family is a new entry in ``KINDS`` — the scenarios and the materializer
    stay family-agnostic."""

    # compute capabilities that must hold or deploy() skips the scenario,
    # e.g. ``{"ubridge_tap": True}``.
    requires: dict = {}

    def ensure_image(self, server):
        """The family's image, bootstrapped on demand (download, steal-copy,
        pull...). Returns the reference the server knows it by — or None for
        the image-less families (the switch, VPCS)."""
        raise NotImplementedError

    def create(self, server, project_id, name, spec, image):
        """Create the node through the API; returns the node dict. *server*
        (not just its compute): families resolve per-image extras through it
        (dynamips' idle-PC)."""
        raise NotImplementedError

    def pre_start(self, server, node, spec, interfaces):
        """Hook before the node starts — for families whose address config
        must exist before boot (the Docker interfaces file). Default: nothing."""

    def adapter_port(self, interface):
        """The (adapter_number, port_number) an endpoint interface name
        addresses on this family — the naming and numbering differ per
        emulator (eth0, f1/0, Ethernet0/0, ...)."""
        raise NotImplementedError

    def boot(self, server, project_id, node, image, interfaces):
        """Open the guest channel and wait for the guest to be up; returns
        the channel (a console driver on the serial families, a daemon exec
        channel on the container ones — or None for a family with no guest
        to drive). The criterion is the family's own (a banner, a prompt
        shape, an applied address), not a timer — and it must hold before
        any host-side state is asserted, so the datapath is settled when
        ``boot`` returns."""
        raise NotImplementedError

    def post_boot(self, server, node, spec, interfaces):
        """Host-side quirks right after boot (e.g. keeping NetworkManager
        away from the family's anchor devices). Default: nothing."""

    def configure(self, channel, interfaces, name):
        """Apply the endpoint addresses — idempotent, so a scenario can
        re-run it after a restart or an admin-down. *interfaces* maps the
        interface name to ``(ipv4, ipv6)`` (either may be None); *name* is
        the node's spec name (the IOS families make it the guest hostname)."""
        raise NotImplementedError

    def ping(self, channel, target, **kwargs):
        raise NotImplementedError

    def wait_ping(self, channel, target, **kwargs):
        raise NotImplementedError

    def ping_ok(self, result):
        """Whether a ping/wait_ping result of this family means "fully
        reached" — the families' result dicts differ (success vs loss)."""
        raise NotImplementedError


def _eth_adapter(interface, family):
    """The adapter number an endpoint interface name addresses (the port is
    always 0 — one NIC per adapter on the ethN-named families; the IOS
    families name interfaces the guest's way and parse their own)."""

    match = re.match(r"eth(\d+)$", interface)
    if not match:
        raise ValueError(f"{family} interfaces are eth0, eth1, ... — not {interface!r}")
    return int(match.group(1))


class FrrQemuKind(Kind):
    """The gns3-registry FRR appliance qcow2 on the local qemu binary: a
    real Alpine Linux behind the server's telnet console. The pinned boot
    transcript is fixed — the console auto-logins into vtysh and prints the
    FRRouting greeting, so the banner is both the boot-success marker and an
    identity tripwire (a wrong image in the cache fails in seconds). An
    image override (``GNS3_E2E_QEMU_IMAGE`` or the spec's ``image:``) skips
    the pin and with it the banner."""

    requires = {"ubridge_tap": True}
    BANNER_RE = re.compile(r"Hello, this is FRRouting")
    # the appliance boots ide and needs little memory — both make the boot
    # faster than the create defaults (virtio disk frontend, 512 MB)
    RAM = 256
    DISK_INTERFACE = "ide"

    def ensure_image(self, server):
        return harness.ensure_qemu_image(server)

    def create(self, server, project_id, name, spec, image):
        return server.compute.create_qemu_node(
            project_id,
            name,
            image,
            adapters=spec.gns3.adapters or 2,
            ram=self.RAM,
            hda_disk_interface=self.DISK_INTERFACE,
        )

    def adapter_port(self, interface):
        return _eth_adapter(interface, "frr-qemu"), 0

    def boot(self, server, project_id, node, image, interfaces):
        console = harness.shell_console(server, project_id, node["node_id"])
        banner = self.BANNER_RE if image == harness.QEMU_IMAGE else None
        console.boot_wait(timeout=300, banner=banner)
        return console

    def post_boot(self, server, node, spec, interfaces):
        # NetworkManager can release an NM-managed TAP from its bridge after
        # (re-)enslavement (docs/bugs/networkmanager-tap-release.md); take
        # every anchor of the node out of its reach for the rest of the run
        # (one TAP per adapter, wired or not).
        harness.unmanage_from_networkmanager(
            *(harness.qemu_anchor_name(node["node_id"], adapter) for adapter in range(spec.gns3.adapters or 2))
        )

    def configure(self, console, interfaces, name):
        for interface, (v4, v6) in sorted(interfaces.items()):
            harness.configure_linux(
                console,
                eth_ip=str(v4) if v4 else None,
                eth_ipv6=str(v6) if v6 else None,
                eth_if=interface,
            )

    def ping(self, console, target, **kwargs):
        return harness.linux_ping(console, target, **kwargs)

    def wait_ping(self, console, target, **kwargs):
        return harness.wait_linux_ping(console, target, **kwargs)

    def ping_ok(self, result):
        return result["success"] == 100


class DockerChannel:
    """The container families' guest channel: the Docker daemon socket plus
    the container id. There is no console to parse — exec through the daemon
    is scriptable both ways; every request opens its own socket connection,
    so there is nothing to close."""

    def __init__(self, daemon, container_id):
        self.daemon = daemon
        self.container_id = container_id

    def exec(self, cmd, **kwargs):
        return self.daemon.exec(self.container_id, cmd, **kwargs)

    def close(self):
        pass


class UbuntuDockerKind(Kind):
    """The standard Docker node on the digest-pinned gns3/ubuntu image: the
    guest is driven through the Docker daemon socket the server itself uses
    — no console. The v4 addresses ride the node's persistent interfaces
    file, written before start the way a GNS3 user configures a Docker node
    and applied by the container's init.sh; the v6 globals cannot (the
    daemon leaves the interface disable_ipv6=1 on bridge networks), so they
    are brought up by hand after every container start."""

    def ensure_image(self, server):
        return harness.ensure_docker_image(server)

    def create(self, server, project_id, name, spec, image):
        return server.compute.create_docker_node(project_id, name, image, adapters=spec.gns3.adapters or 1)

    def pre_start(self, server, node, spec, interfaces):
        for interface, (v4, _v6) in sorted(interfaces.items()):
            if v4 is None:
                raise AssertionError(
                    f"{node['name']}: the docker family wires ethX through the interfaces file, "
                    f"which is IPv4-only — endpoint {interface} needs an ipv4"
                )
            harness.configure_docker_interfaces(
                node,
                str(v4.ip),
                netmask=str(v4.network.netmask),
                adapter=_eth_adapter(interface, "ubuntu-docker"),
            )

    def adapter_port(self, interface):
        return _eth_adapter(interface, "ubuntu-docker"), 0

    def boot(self, server, project_id, node, image, interfaces):
        # the container exists from node creation on, so the id resolves in
        # any state; this family's boot criterion is init.sh having applied
        # the interfaces file (the v4 on the wire) — waiting it here leaves
        # the host-side datapath (veth carrier, bridge port states) settled
        # before any scenario asserts on it
        daemon = harness.DockerDaemon()
        container_id = daemon.container_id(f"GNS3.{node['name']}.{node['project_id']}")
        assert container_id, f"container for {node['name']} not found on the Docker daemon"
        node["container_id"] = container_id
        channel = DockerChannel(daemon, container_id)
        for interface, (v4, _v6) in sorted(interfaces.items()):
            harness.docker_wait_address(
                daemon, container_id, str(v4.ip), adapter=_eth_adapter(interface, "ubuntu-docker")
            )
        return channel

    def configure(self, channel, interfaces, name):
        # the v4 wait is the reconfigure path (after a container restart
        # init.sh re-applies the file); on the first pass boot already
        # waited it and the check is a fast no-op
        for interface, (v4, v6) in sorted(interfaces.items()):
            adapter = _eth_adapter(interface, "ubuntu-docker")
            harness.docker_wait_address(channel.daemon, channel.container_id, str(v4.ip), adapter=adapter)
            if v6 is not None:
                harness.docker_bring_up_ipv6(channel.daemon, channel.container_id, str(v6.ip), adapter=adapter)
                harness.docker_wait_address(channel.daemon, channel.container_id, str(v6.ip), adapter=adapter)

    def ping(self, channel, target, **kwargs):
        return harness.docker_ping(channel.daemon, channel.container_id, target, **kwargs)

    def wait_ping(self, channel, target, **kwargs):
        return harness.docker_wait_ping(channel.daemon, channel.container_id, target, **kwargs)

    def ping_ok(self, result):
        return result["loss"] == 0


class IosKind(Kind):
    """The IOS console families (dynamips routers, IOU): one driver, one
    address baseline (``configure_ios`` — idempotent, so a restart's
    reconfigure is safe), one IOS ping parser. Only the image pin, the node
    creation and the interface naming differ per family."""

    # the family's anchor-name helper (a harness function) — set by subclasses
    _anchor_name = None
    # an IOS boot is slow; the kind's wait covers the whole family
    BOOT_TIMEOUT = 360

    def boot(self, server, project_id, node, image, interfaces):
        console = harness.ios_console(server, project_id, node["node_id"])
        console.boot_wait(timeout=self.BOOT_TIMEOUT)
        return console

    def post_boot(self, server, node, spec, interfaces):
        # the NM quirk (see FrrQemuKind.post_boot) — the wired interfaces'
        # anchors only, the addresses the family's scenarios re-attach
        harness.unmanage_from_networkmanager(
            *(self._anchor_name(node["node_id"], *self.adapter_port(interface)) for interface in interfaces)
        )

    def configure(self, console, interfaces, name):
        for interface, (v4, v6) in sorted(interfaces.items()):
            harness.configure_ios(
                console,
                name.upper(),
                eth_ip=str(v4.ip) if v4 else None,
                eth_ipv6=f"{v6.ip}/{v6.network.prefixlen}" if v6 else None,
                eth_if=interface,
                eth_netmask=str(v4.network.netmask) if v4 else "255.255.255.0",
            )

    def ping(self, console, target, **kwargs):
        return harness.ping(console, target, **kwargs)

    def wait_ping(self, console, target, **kwargs):
        return harness.wait_ping(console, target, **kwargs)

    def ping_ok(self, result):
        return result["success"] == 100


class IosDynamipsKind(IosKind):
    """The registry-pinned c7200 IOS image on the local dynamips: a real
    router behind the server's telnet console. The serial PA rides along in
    slot 2 even though a spec never wires it — the relay-leg scenarios wire
    a serial link by hand (serial bays never anchor, that exclusion is part
    of what they test), and the PA must be in the box for that."""

    requires = {"ubridge_tap": True}
    # slot 0 is the fixed IO slot; the Ethernet PA goes in slot 1 (two FE
    # ports), the serial PA in slot 2 (four ports)
    SLOTS = {"slot1": "PA-2FE-TX", "slot2": "PA-4T+"}
    INTERFACE_RE = re.compile(r"f(\d+)/(\d+)$")
    _anchor_name = staticmethod(harness.anchor_name)

    def ensure_image(self, server):
        return harness.ensure_dynamips_image(server)

    def create(self, server, project_id, name, spec, image):
        # without an idle-PC a router busy-waits a full CPU core for the
        # whole scenario — detected once per image, cached (see harness)
        idlepc = harness.dynamips_idlepc(server, image)
        return server.compute.create_dynamips_router(project_id, name, image, self.SLOTS, idlepc=idlepc)

    def adapter_port(self, interface):
        match = self.INTERFACE_RE.match(interface)
        if not match:
            raise ValueError(f"ios-dynamips interfaces are f1/0, f1/1, ... — not {interface!r}")
        return int(match.group(1)), int(match.group(2))


class IouKind(IosKind):
    """The registry-pinned L3 IOU image executed by the local compute: real
    IOS on the server's telnet console, no host interface of its own — the
    guest leg is the IOL fabric socket, and the anchors are one persistent
    TAP per Ethernet bay/unit (the interface names are the guest's own:
    Ethernet0/0 is bay 0, unit 0)."""

    requires = {"ubridge_iol_tap": True, "ubridge_tap": True}
    INTERFACE_RE = re.compile(r"[Ee]thernet(\d+)/(\d+)$")
    _anchor_name = staticmethod(harness.iou_anchor_name)

    def ensure_image(self, server):
        return harness.ensure_iou_image(server)

    def create(self, server, project_id, name, spec, image):
        return server.compute.create_iou_node(project_id, name, image)

    def adapter_port(self, interface):
        match = self.INTERFACE_RE.match(interface)
        if not match:
            raise ValueError(f"iou interfaces are Ethernet0/0, Ethernet0/1, ... — not {interface!r}")
        return int(match.group(1)), int(match.group(2))


class EthernetSwitchKind(Kind):
    """The builtin Ethernet switch (a Linux kernel bridge on this host): no
    image, no guest, no console — there is nothing to boot, configure or
    ping, and ``boot`` returns no channel. Its ports come from
    ``gns3.adapters`` (access VLAN 1 each, named the switch's own way); the
    VLAN-programming scenarios PUT their own ports_mapping on top."""

    def ensure_image(self, server):
        return None

    def create(self, server, project_id, name, spec, image):
        ports = spec.gns3.adapters or 2
        return server.compute.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {
                "compute_id": "local",
                "name": name,
                "node_type": "ethernet_switch",
                "properties": {
                    "ports_mapping": [
                        {"name": f"Ethernet{number}", "port_number": number, "type": "access", "vlan": 1}
                        for number in range(ports)
                    ]
                },
            },
        )

    def adapter_port(self, interface):
        match = re.fullmatch(r"[Ee]thernet(\d+)", interface)
        if not match:
            raise ValueError(f"ethernet-switch interfaces are Ethernet0, Ethernet1, ... — not {interface!r}")
        return 0, int(match.group(1))

    def boot(self, server, project_id, node, image, interfaces):
        return None  # nothing to drive: the switch bridge exists from creation

    def configure(self, channel, interfaces, name):
        pass  # no guest — the wiring is the node's whole behavior


class VpcsKind(Kind):
    """The local vpcs binary behind the server's TCP console: the family
    with no image at all (the binary comes from the server's own config).
    Its addresses ride the guest's own ``ip`` command and are re-applied
    after every start — the process forgets everything. IPv4 only: the v6
    command shape is untested, so a spec's v6 is refused instead of silently
    misconfigured."""

    requires = {"ubridge_tap": True, "vpcs_tap": True}

    def ensure_image(self, server):
        return None

    def create(self, server, project_id, name, spec, image):
        return server.compute.create_vpcs_node(project_id, name)

    def adapter_port(self, interface):
        return _eth_adapter(interface, "vpcs"), 0

    def boot(self, server, project_id, node, image, interfaces):
        # the anchor is born with the node start; the console answers as
        # soon as the vpcs daemon accepts the connection — the first
        # command's prompt-wait is the boot criterion
        for interface in interfaces:
            anchor = harness.vpcs_anchor_name(node["node_id"], *self.adapter_port(interface))
            assert harness.wait_until(lambda exists=anchor: harness.tap_exists(exists), timeout=15), anchor
        return harness.vpcs_console(server, project_id, node["node_id"])

    def post_boot(self, server, node, spec, interfaces):
        # the NM quirk (see FrrQemuKind.post_boot); the restart paths
        # re-attach the anchor under a fresh device
        harness.unmanage_from_networkmanager(
            *(harness.vpcs_anchor_name(node["node_id"], *self.adapter_port(interface)) for interface in interfaces)
        )

    def configure(self, console, interfaces, name):
        console.run(f"set pcname {name.upper()}")
        for interface, (v4, v6) in sorted(interfaces.items()):
            if v6 is not None:
                raise AssertionError("the vpcs family is IPv4-only in the e2e (the v6 command shape is untested)")
            if v4 is None:
                raise AssertionError(f"{name}:{interface} needs an ipv4 — the family cannot ping without one")
            out = console.run(f"ip {v4.ip}/{v4.network.prefixlen}")
            assert str(v4.ip) in out, out

    def ping(self, console, target, **kwargs):
        return harness.vpcs_ping(console, target, **kwargs)

    def wait_ping(self, console, target, **kwargs):
        return harness.wait_vpcs_ping(console, target, **kwargs)

    def ping_ok(self, result):
        return result["success"] == 100


KINDS = {
    "frr-qemu": FrrQemuKind(),
    "ubuntu-docker": UbuntuDockerKind(),
    "ios-dynamips": IosDynamipsKind(),
    "iou": IouKind(),
    "ethernet-switch": EthernetSwitchKind(),
    "vpcs": VpcsKind(),
}


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


class NodeHandle:
    """One deployed node: its API dict, the resolved kind and image, and —
    once ``boot()`` ran — the guest channel (a console driver on the serial
    families, a daemon exec channel on the container ones). The helpers
    stay thin; the scenario's own steps call the API directly."""

    def __init__(self, name, spec, node, kind, image, server, project_id, interfaces):
        self.name = name
        self.spec = spec
        self.node = node
        self.kind = kind
        self.image = image
        self.server = server
        self.project_id = project_id
        # {interface: (ipv4, ipv6)} derived from the link endpoints
        self.interfaces = interfaces
        self.channel = None

    @property
    def node_id(self):
        return self.node["node_id"]

    def address(self, interface=None, family=4):
        """The configured address of *interface* without the prefix length —
        the form ping targets want. *interface* defaults to the node's first
        wired one (the interface names are family-specific, `eth0` no more
        than `f1/0`, so the default cannot be a literal); a multi-interface
        node names the interface explicitly."""
        if interface is None:
            if not self.interfaces:
                raise KeyError(f"node {self.name!r} has no wired interfaces at all")
            interface = next(iter(self.interfaces))
        if interface not in self.interfaces:
            raise KeyError(f"node {self.name!r} has no wired interface {interface!r}")
        v4, v6 = self.interfaces[interface]
        address = v4 if family == 4 else v6
        if address is None:
            raise KeyError(f"{self.name}:{interface} has no IPv{family} address")
        return str(address.ip)

    def start(self):
        """Start this node alone — the single-node variant of the phase API
        (a restart after a stop)."""
        self.kind.pre_start(self.server, self.node, self.spec, self.interfaces)
        self.server.compute.call("POST", f"/projects/{self.project_id}/nodes/{self.node_id}/start")

    def boot_wait(self):
        """(Re-)wait for the guest boot and re-open the channel — after a
        node restart, when the server-side console is a fresh socket (or the
        container was recreated)."""
        if self.channel is not None:
            self.channel.close()
        self.channel = self.kind.boot(self.server, self.project_id, self.node, self.image, self.interfaces)
        return self.channel

    def refresh(self):
        """Re-fetch the node dict and re-open the channel after the project
        was reopened on a restarted server (the compute-side state was
        rebuilt; a container id may have changed)."""
        self.node = self.server.compute.node(self.project_id, self.node_id)
        if self.channel is not None:
            self.boot_wait()
        return self

    def reconfigure(self):
        """Re-apply the address baseline (idempotent by design): after a
        node restart, or after any guest action that dropped the addresses
        (a Linux admin-down discards the IPv6 globals)."""
        self.kind.configure(self.channel, self.interfaces, self.name)

    def ping(self, target, **kwargs):
        return self.kind.ping(self.channel, target, **kwargs)

    def wait_ping(self, target, **kwargs):
        return self.kind.wait_ping(self.channel, target, **kwargs)


class LabInstance:
    """A materialized lab: the project, the created nodes and links. Nothing
    runs until the phases are called — in order or with assertions in
    between, whichever the scenario needs."""

    def __init__(self, spec, server, project, handles, links, link_specs):
        self.spec = spec
        self.server = server
        self.project = project
        self.handles = handles
        # the created link dicts, parallel to their specs
        self.links = links
        self._link_specs = link_specs

    @property
    def project_id(self):
        return self.project["project_id"]

    def __getitem__(self, name):
        return self.handles[name]

    def link(self, a, b):
        """The link dict connecting nodes *a* and *b* (the first one if a
        pair is wired more than once)."""
        for link, link_spec in zip(self.links, self._link_specs, strict=True):
            if {link_spec.endpoints[0].node, link_spec.endpoints[1].node} == {a, b}:
                return link
        raise KeyError(f"no link between {a!r} and {b!r}")

    def start(self):
        """Start every node (spec order). Families whose address config
        must precede boot get their pre-start hook here."""
        for handle in self.handles.values():
            handle.start()

    def boot(self):
        """Wait for every guest's boot, then apply the family's post-boot
        host-side quirks. The waits are serial like the scenarios were —
        each console's transcript is the debug record."""
        for handle in self.handles.values():
            if handle.channel is None:
                handle.boot_wait()
        for handle in self.handles.values():
            handle.kind.post_boot(self.server, handle.node, handle.spec, handle.interfaces)

    def configure(self):
        """Apply the endpoint addresses on every node, then wait for each
        link's baseline reachability (both address families): the first
        addressed endpoint of a link pings the other addressed ones. After
        this returns, a link with no impairment pings clean."""
        for handle in self.handles.values():
            handle.reconfigure()
        for link_spec in self._link_specs:
            # only endpoints that carry an address take part (a link to a
            # switch has none on its switch side — the baseline of such a
            # topology is cross-link and stays the scenario's own assert)
            addressed = [e for e in link_spec.endpoints if e.ipv4 is not None or e.ipv6 is not None]
            if len(addressed) < 2:
                continue
            source = self.handles[addressed[0].node]
            # baseline waits tolerate the boot transient generously (~40 s):
            # under parallel load the relay's second uBridge can lag well
            # behind its container, and a v6 ND resolution has been observed
            # stalling ~20 s with the pipe provably healthy before and after
            # — the impairment asserts later in a scenario stay strict
            for endpoint in addressed[1:]:
                if endpoint.ipv4 is not None:
                    baseline = source.wait_ping(str(endpoint.ipv4.ip), attempts=8)
                    assert source.kind.ping_ok(baseline), baseline
                if endpoint.ipv6 is not None:
                    baseline6 = source.wait_ping(str(endpoint.ipv6.ip), attempts=8)
                    assert source.kind.ping_ok(baseline6), baseline6

    def close_channels(self):
        for handle in self.handles.values():
            if handle.channel is not None:
                handle.channel.close()
                handle.channel = None


def _resolve_kinds(spec, name):
    """Map each node to ``(kind_name, kind, node_spec)`` — the clab way:
    the node's own kind, then the kinds section, then defaults."""

    resolved = {}
    for node_name, node_spec in spec.topology.nodes.items():
        kind_name = node_spec.kind or spec.topology.defaults.kind
        if not kind_name:
            raise AssertionError(f"{name}: node {node_name!r} has no kind (node, kinds or defaults must set one)")
        if kind_name not in KINDS:
            raise AssertionError(f"{name}: node {node_name!r} uses unknown kind {kind_name!r} (known: {sorted(KINDS)})")
        resolved[node_name] = (kind_name, KINDS[kind_name], node_spec)
    return resolved


def _resolve_images(spec, server, resolved):
    """The image each node runs: an explicit one (node > kinds > defaults)
    is used as-is, like an override; without one each family pins and
    bootstraps its own — once per kind, not per node."""

    images = {}
    pinned = {}
    for node_name, (kind_name, kind, _node_spec) in resolved.items():
        explicit = _resolved_image(spec, node_name)
        if explicit is not None:
            images[node_name] = explicit
        else:
            if kind_name not in pinned:
                pinned[kind_name] = kind.ensure_image(server)
            images[node_name] = pinned[kind_name]
    return images


def deploy(name, server, project_name=None, gate_caps=True):
    """Materialize a lab spec (``load`` semantics for *name*) against
    *server*: resolve the kinds, gate on their required capabilities (skip
    the scenario where they are missing — unless *gate_caps* is False, the
    relay control twins' setting: they ride the relay whatever the compute's
    uBridge can anchor, and enforce what they need through their own
    asserts), ensure the images, create the project, the nodes and the
    links. Returns a ``LabInstance`` with nothing started — call ``start``,
    ``boot`` and ``configure`` (with the scenario's assertions in between
    where the construction itself is under test, as the deferred kernel
    wiring is)."""

    spec = load(name)
    compute = server.compute
    resolved = _resolve_kinds(spec, name)

    # gate on the capabilities the families need, before anything is created
    if gate_caps:
        caps = compute.capabilities()
        for kind in {entry[1] for entry in resolved.values()}:
            for capability, expected in kind.requires.items():
                if caps.get(capability) is not expected:
                    pytest.skip(
                        f"this compute cannot run kind {type(kind).__name__} ({capability}={caps.get(capability)})"
                    )

    images = _resolve_images(spec, server, resolved)
    project = compute.create_project(project_name or spec.name)
    try:
        # the per-node address map derived from the link endpoints: it
        # drives the pre-start hook and configure(); the node name is the
        # spec key uppercased, the way the scenarios have always named
        # their nodes
        interfaces = {node_name: {} for node_name in spec.topology.nodes}
        for link_spec in spec.topology.links:
            for endpoint in link_spec.endpoints:
                interfaces[endpoint.node][endpoint.interface] = (endpoint.ipv4, endpoint.ipv6)
        handles = {}
        for node_name, (_kind_name, kind, node_spec) in resolved.items():
            node = kind.create(server, project["project_id"], node_name.upper(), node_spec, images[node_name])
            handles[node_name] = NodeHandle(
                node_name,
                node_spec,
                node,
                kind,
                images[node_name],
                server,
                project["project_id"],
                interfaces[node_name],
            )
        links = []
        for link_spec in spec.topology.links:
            wired = []
            for endpoint in link_spec.endpoints:
                kind = resolved[endpoint.node][1]
                wired.append((handles[endpoint.node].node_id, *kind.adapter_port(endpoint.interface)))
            links.append(compute.create_link(project["project_id"], *wired))
    except BaseException:
        try:
            compute.delete_project(project["project_id"])
        except Exception as cleanup_error:  # keep the original failure visible
            print(f"!! could not delete project {project['project_id']}: {cleanup_error}")
        raise
    return LabInstance(spec, server, project, handles, links, spec.topology.links)


def _resolved_image(spec, node_name):
    """The spec's explicit image for *node_name* — node, then the kinds
    section, then defaults — or None (the family's pinned image is then
    bootstrapped and used)."""

    node_spec = spec.topology.nodes[node_name]
    kind_spec = spec.topology.kinds.get(node_spec.kind or spec.topology.defaults.kind)
    for candidate in (node_spec.image, kind_spec.image if kind_spec else None, spec.topology.defaults.image):
        if candidate is not None:
            return candidate
    return None
