#
# Copyright (C) 2026 GNS3 Technologies Inc.
# This program is free software and is redistributed under the same terms as gns3-server.
# See the LICENSE file for licensing information.
#

"""
Live end-to-end test for the QEMU node's kernel datapath (pytest marker
``e2e``): two real FRR routers (the gns3-registry FRR appliance's qcow2 run
by the local qemu binary, a real Linux behind the server's telnet console),
driven through the controller REST API. The topology is the shared dumbbell
spec (``topologies/qemu-dumbbell.yml``) materialized by ``tests/e2e/lab.py``
— the frr-qemu kind owns the image pin, the boot criterion and the address
baseline, so this file is only the scenario: the API steps under test and
their assertions.

QEMU is the node type whose guest leg *is* the anchor: uBridge creates one
persistent TAP per adapter before launching and hands it to this user, and
QEMU opens it by ifname as its netdev
(``-netdev tap,ifname=...,script=no,downscript=no,vnet_hdr=off``) — no userspace hop, no
port bridge, the anchor is the NIC's host side.

* two QEMU nodes on one compute report ``kernel_datapath`` when the
  compute's uBridge can create persistent TAPs (``ubridge_tap``); the
  anchors (``gq`` TAPs, one per adapter) exist from node start, before any
  link — and the per-link bridge enslaves exactly the two of them;
* real ICMP crosses the [QEMU netdev ↔ TAP] anchor;
* the L2-anchor spec §E.2 silence window with the guests shut (the anchors
  here are QEMU's own netdevs);
* a ``delay 100`` filter lands as netem on both anchors, RTT grows ~200 ms;
* suspend admin-downs the anchor (the e1000 loses carrier) and kills the
  traffic; resume restores;
* a capture on the kernel link writes a real pcap;
* link delete releases the anchor from the bridge and it survives (the
  running VM holds it open) — re-creating the link re-enslaves it and the
  traffic returns;
* node stop deletes every anchor of the node together with the orphan
  bridges; a restart recreates the TAPs and rewires the link from the NIO;
* deleting the project leaves no anchors and no bridges behind.

``test_qemu_relay_control`` is the negative control on an isolated
relay-configured instance: the anchors still exist (a QEMU node creates its
adapter TAPs at start whenever uBridge can), but nothing is enslaved — the
relay attaches the anchor itself as an AF_PACKET endpoint, so it stays up
and carrying while the link rides the uBridge relay. This differs from
IOU's relay, where the fabric socket carries the traffic and the anchors
sit idle: QEMU has no other leg, the TAP is the netdev either way.

Every checkpoint runs dual-stack: the FRR guests carry a ULA v6 address
next to their v4 one and each checkpoint pings both families.
"""

import time

import pytest

from tests.e2e import harness, lab

pytestmark = pytest.mark.e2e

# One NIC per adapter, port number always 0: adapter 0 is eth0.
ETH = (0, 0)
GUEST_ETH_IF = "eth0"


def _eth_shutdown(console, shut):
    """Down/up the guest's eth0 — the only legitimate speaker on the link
    segment (the guest's own chatter) — for §E.2's silence window; the
    address stays configured and answers once it is back."""
    console.run(f"ip link set {GUEST_ETH_IF} {'down' if shut else 'up'}")


def test_qemu_kernel_datapath():
    server = harness.live_server(kernel=True)

    # the lab spec creates the nodes and the link while both are stopped:
    # the kernel NIO is bound with no anchors in existence yet and wired by
    # node start (the deferred-wiring path)
    labi = lab.deploy("qemu-dumbbell", server, project_name="qemu-e2e")
    compute = server.compute
    pid = labi.project_id
    a1 = a2 = None
    try:
        n1_id, n2_id = labi["r1"].node_id, labi["r2"].node_id
        a1 = harness.qemu_anchor_name(n1_id, *ETH)
        a2 = harness.qemu_anchor_name(n2_id, *ETH)
        r1_v6 = labi["r1"].address(family=6)
        r2_v4 = labi["r2"].address()
        r2_v6 = labi["r2"].address(family=6)

        link = labi.link("r1", "r2")
        lid = link["link_id"]
        bridge = harness.link_bridge_name(lid)
        assert link["kernel_datapath"] is True, link
        assert not harness.tap_exists(a1), "anchors must not exist before start"

        print(f".. starting FRR routers on {labi['r1'].image} (a real Linux boot)")
        labi.start()
        labi.boot()
        c1, c2 = labi["r1"].channel, labi["r2"].channel

        # Kernel objects: one persistent TAP per adapter (both adapters of
        # router 1, the addressed one of router 2), and the per-link bridge
        # has exactly the two addressed ports.
        for adapter in range(2):
            name = harness.qemu_anchor_name(n1_id, adapter)
            assert harness.tap_exists(name), name
        assert harness.tap_exists(a2), a2
        assert harness.bridge_members(bridge) == sorted([a1, a2]), harness.bridge_members(bridge)

        # L2-anchor spec §E.1: anchors and the per-link bridge carry no L3
        # identity (skipped on a uBridge without `link l2only`), and both
        # ports are FORWARDING — the silent-failure guard.
        if harness.l2only_supported():
            harness.assert_pure_l2(a1)
            harness.assert_pure_l2(a2)
            harness.assert_pure_l2(bridge)
        else:
            print(".. uBridge without link l2only: skipping the §E.1 assertions")
        harness.assert_forwarding(a1)
        harness.assert_forwarding(a2)

        # addresses from the spec, baseline reachability from the library
        labi.configure()
        out = c1.run(f"ip -o addr show dev {GUEST_ETH_IF}")
        assert "10.1.1.1/24" in out, out
        assert f"{r1_v6}/64" in out, out
        print(".. both routers configured, pinging through the anchor TAPs")
        baseline = labi["r1"].wait_ping(r2_v4)
        assert baseline["success"] == 100, baseline["raw"]
        baseline6 = labi["r1"].wait_ping(r2_v6)
        assert baseline6["success"] == 100, baseline6["raw"]

        # L2-anchor spec §E.2: with the guests shut the anchors (QEMU's own
        # netdevs) and the per-link bridge stay silent for 5 s.
        if harness.l2only_supported():
            for console in (c1, c2):
                _eth_shutdown(console, shut=True)
            harness.assert_idle_silence(a1, a2, bridge)
            for console in (c1, c2):
                _eth_shutdown(console, shut=False)
            # a Linux interface admin-down discards its IPv6 global
            # addresses (keep_addr_on_down defaults to 0) while IPv4 keeps
            # them — re-apply the idempotent baseline before the v6
            # checkpoint, the same way the node-restart path below does
            labi["r1"].reconfigure()
            labi["r2"].reconfigure()
            assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
            assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100
        else:
            print(".. uBridge without link l2only: skipping the §E.2 assertion")

        # delay 100: netem on both anchors (each impairs one direction),
        # one-way ~100 ms => RTT grows by ~200 ms
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"filters": {"delay": [100]}})
        assert "netem" in harness.qdiscs(a1) and "netem" in harness.qdiscs(a2), (
            harness.qdiscs(a1),
            harness.qdiscs(a2),
        )
        delayed = labi["r1"].wait_ping(r2_v4)
        assert delayed["success"] == 100, delayed["raw"]
        assert delayed["avg"] >= 150, (baseline, delayed)
        delayed6 = labi["r1"].wait_ping(r2_v6)
        assert delayed6["success"] == 100, delayed6["raw"]
        assert delayed6["avg"] >= 150, (baseline6, delayed6)
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"filters": {}})
        assert "netem" not in harness.qdiscs(a1), harness.qdiscs(a1)
        fast = labi["r1"].wait_ping(r2_v4)
        assert fast["success"] == 100 and fast["avg"] < harness.FAST_RTT_MS, fast
        fast6 = labi["r1"].wait_ping(r2_v6)
        assert fast6["success"] == 100 and fast6["avg"] < harness.FAST_RTT_MS, fast6

        # suspend: anchor admin-down — the e1000 loses carrier, the bridge
        # port is disabled and nothing crosses; resume restores
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"suspend": True})
        assert not harness.tap_up(a1)
        dead = labi["r1"].ping(r2_v4, repeat=3)
        assert dead["success"] == 0, dead["raw"]
        dead6 = labi["r1"].ping(r2_v6, repeat=3)
        assert dead6["success"] == 0, dead6["raw"]
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"suspend": False})
        assert harness.tap_up(a1)
        assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        # capture: on the anchor, a real pcap — both families inside the window
        capture = compute.call("POST", f"/projects/{pid}/links/{lid}/capture/start", {"data_link_type": "DLT_EN10MB"})
        labi["r1"].ping(r2_v4)
        labi["r1"].ping(r2_v6)
        time.sleep(1)
        compute.call("POST", f"/projects/{pid}/links/{lid}/capture/stop")
        path = capture["capture_file_path"]
        count, ethertypes = harness.pcap_records(path)
        assert count >= 8, f"{path}: {count} records"
        assert "0800" in ethertypes, (path, ethertypes)
        assert "86dd" in ethertypes, (path, ethertypes)

        # delete / re-create the kernel link: the anchor leaves the bridge
        # but survives (the running VM holds it open — this is QEMU's own
        # netdev), and re-creating re-enslaves it without touching the VM.
        compute.call("DELETE", f"/projects/{pid}/links/{lid}")
        assert harness.bridge_members(bridge) is None
        assert harness.tap_exists(a1) and harness.tap_exists(a2)
        link = compute.create_link(pid, (n1_id, *ETH), (n2_id, *ETH))
        lid = link["link_id"]
        bridge = harness.link_bridge_name(lid)
        assert link["kernel_datapath"] is True, link
        assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        # node stop: QEMU exits and uBridge deletes every anchor of the
        # node together with the orphan bridges (a stopped node must not
        # litter the host with gq devices); a restart recreates the TAPs
        # and rewires the link from the NIO that outlived it.
        print(".. stopping and restarting router 1")
        compute.call("POST", f"/projects/{pid}/nodes/{n1_id}/stop")
        second = harness.qemu_anchor_name(n1_id, 1)
        assert harness.wait_until(lambda: not harness.tap_exists(a1) and not harness.tap_exists(second), timeout=15), (
            a1,
            second,
        )
        # the per-link bridge lost this end's port; it may be gone entirely
        # (both endpoints delete it, last one wins)
        assert harness.bridge_members(bridge) in (None, [a2]), harness.bridge_members(bridge)
        compute.call("POST", f"/projects/{pid}/nodes/{n1_id}/start")
        c1 = labi["r1"].boot_wait()
        assert harness.tap_exists(a1)
        assert harness.bridge_members(bridge) == sorted([a1, a2]), harness.bridge_members(bridge)
        labi["r1"].reconfigure()
        assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        labi.close_channels()
    except BaseException:
        harness.release(server, pid, failed=True)
        raise
    harness.release(server, pid, failed=False)

    # deleting the project closed the nodes: anchors and bridges go with them
    assert harness.wait_until(lambda: not harness.tap_exists(a1) and not harness.tap_exists(a2), timeout=15), (
        a1,
        a2,
    )


def test_qemu_relay_control():
    """
    Negative control: the same topology with ``enable_kernel_datapath =
    false`` (an isolated instance) wires nothing into the kernel — no
    per-link bridge, no enslavement — and still pings.

    The anchors DO exist and carry: a QEMU node creates its adapter TAPs at
    start whenever uBridge can (the netdev needs them), and on the relay
    the anchor itself becomes the uBridge relay's AF_PACKET endpoint — up
    and forwarding into the relay bridge. The server configuration only
    decides whether a *link* enslaves them.
    """

    server = harness.live_server(kernel=False)

    labi = lab.deploy("qemu-dumbbell", server, project_name="qemu-relay-e2e")
    pid = labi.project_id
    a1 = None
    try:
        n1_id = labi["r1"].node_id
        a1 = harness.qemu_anchor_name(n1_id, *ETH)
        r2_v4 = labi["r2"].address()
        r2_v6 = labi["r2"].address(family=6)

        link = labi.link("r1", "r2")
        assert link["kernel_datapath"] is False, link

        print(".. starting FRR routers and waiting for the Linux boots (relay)")
        labi.start()
        labi.boot()

        # no kernel wiring: nobody enslaved the anchors, the per-link
        # bridge does not exist — but the anchor is up and carrying as the
        # relay's AF_PACKET endpoint
        assert harness.bridge_members(harness.link_bridge_name(link["link_id"])) is None
        assert harness.tap_exists(a1), a1
        assert harness.tap_up(a1), a1
        if harness.l2only_supported():
            # the L2 hardening is a creation-time property, not a datapath
            # one: relay anchors are pure L2 too
            harness.assert_pure_l2(a1)
        labi.configure()
        relay_ping = labi["r1"].wait_ping(r2_v4)
        assert relay_ping["success"] == 100, relay_ping["raw"]
        relay_ping6 = labi["r1"].wait_ping(r2_v6)
        assert relay_ping6["success"] == 100, relay_ping6["raw"]

        labi.close_channels()
    except BaseException:
        harness.release(server, pid, failed=True)
        raise
    harness.release(server, pid, failed=False)

    # deleting the project closed the nodes: the adapter TAPs go with them
    assert harness.wait_until(lambda: not harness.tap_exists(a1), timeout=15), a1
