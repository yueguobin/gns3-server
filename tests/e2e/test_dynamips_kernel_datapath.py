#
# Copyright (C) 2026 GNS3 Technologies Inc.
#
# This program is free software and is redistributed under the same terms as gns3-server.
# See the LICENSE file for licensing information.
#

"""
Live end-to-end test for the Dynamips kernel datapath (pytest marker
``e2e``): two real c7200 routers on a real IOS image, one Ethernet link on
the kernel path and one serial link on the relay, driven through the
controller REST API and the IOS consoles. The topology is the shared
dumbbell spec (``topologies/dynamips-dumbbell.yml``) materialized by
``tests/e2e/lab.py`` — the ios-dynamips kind owns the image pin, the
idle-PC, the boot criterion and the address baseline, so this file is only
the scenario: the API steps under test and their assertions. Real ICMP
proves the datapath:

* the link reports ``kernel_datapath`` and the per-link kernel bridge on
  this host has exactly the two anchor TAPs enslaved (kernel objects, not
  server bookkeeping);
* a ``delay 100`` filter shows up as netem on the anchors and the measured
  RTT rises by ~2x100 ms; clearing it resets the qdiscs and the RTT;
* suspend drives the anchor administratively down and the pings stop;
* capture writes a pcap full of ICMP frames;
* a serial link between the same routers stays on the relay and still
  pings (the relay regression net);
* deleting / re-creating the link, and stopping / starting a router, leave
  the wiring consistent;
* deleting the project leaves no anchors or bridges behind.

``test_dynamips_relay_control`` is the negative control: the same topology
on an isolated relay-configured instance wires nothing into the kernel — no
per-link bridge, nothing enslaved — and still pings, so the kernel objects
above can only come from the kernel datapath. (The anchors themselves exist
on both: they are the adapter's port interfaces, created by node start
whenever the tap module is available, exactly like QEMU's TAPs.)

Every Ethernet checkpoint runs dual-stack (the routers carry a ULA v6
address next to their v4 one and each checkpoint pings both families); the
serial leg stays v4-only — it is HDLC on the relay, not an Ethernet wire.
"""

import re
import time

import pytest

from tests.e2e import harness, lab

pytestmark = pytest.mark.e2e

# f1/0 of the spec's link — (slot 1, port 0) of the Ethernet PA; the serial
# leg the scenario wires by hand is (slot 2, port 0).
ETH = (1, 0)
SERIAL = (2, 0)


def _eth_shutdown(console, shut):
    console.run("conf t")
    console.run("interface f1/0")
    console.run("shutdown" if shut else "no shutdown")
    console.run("end")


def test_dynamips_kernel_datapath():
    server = harness.live_server(kernel=True)
    compute = server.compute

    labi = lab.deploy("dynamips-dumbbell", server, project_name="dyn-e2e")
    pid = labi.project_id
    t1 = t2 = None
    try:
        r1_id, r2_id = labi["r1"].node_id, labi["r2"].node_id
        t1 = harness.anchor_name(r1_id, *ETH)
        t2 = harness.anchor_name(r2_id, *ETH)
        r1_v6 = labi["r1"].address(family=6)
        r2_v4 = labi["r2"].address()
        r2_v6 = labi["r2"].address(family=6)

        # The link was created while both routers were stopped: the kernel
        # NIO is bound with no anchors in existence yet and attached by node
        # start (the deferred-wiring path).
        link = labi.link("r1", "r2")
        lid = link["link_id"]
        bridge = harness.link_bridge_name(lid)
        assert link["kernel_datapath"] is True, link
        assert not harness.tap_exists(t1), "anchors must not exist before start"

        print(".. starting routers and waiting for IOS boots")
        labi.start()
        labi.boot()
        c1, c2 = labi["r1"].channel, labi["r2"].channel

        # Kernel objects: anchors exist and the per-link bridge has exactly
        # the two of them enslaved.
        assert harness.tap_exists(t1) and harness.tap_exists(t2), (t1, t2)
        assert harness.bridge_members(bridge) == sorted([t1, t2]), harness.bridge_members(bridge)

        # L2-anchor spec §E.1: anchors and the per-link bridge carry no L3
        # identity (skipped on a uBridge without `link l2only` — the spec's
        # degradation), and both ports are FORWARDING — the silent-failure
        # guard against a bridge device left DOWN.
        if harness.l2only_supported():
            harness.assert_pure_l2(t1)
            harness.assert_pure_l2(t2)
            harness.assert_pure_l2(bridge)
        else:
            print(".. uBridge without link l2only: skipping the §E.1 assertions")
        harness.assert_forwarding(t1)
        harness.assert_forwarding(t2)

        labi.configure()
        out = c1.run("show ip int brief")
        assert re.search(r"FastEthernet1/0\s+10\.1\.1\.1\s+\S+\s+\S+\s+up\s+up", out), out
        out = c1.run("show ipv6 interface brief")
        # IOS prints v6 addresses upper-case (and on their own line): match
        # the literal case-insensitively
        assert r1_v6.upper() in out.upper(), out
        print(".. both routers configured, pinging over the kernel link")
        baseline = labi["r1"].wait_ping(r2_v4)
        assert baseline["success"] == 100, baseline["raw"]
        baseline6 = labi["r1"].wait_ping(r2_v6)
        assert baseline6["success"] == 100, baseline6["raw"]

        # L2-anchor spec §E.2: shut the guest interfaces (silencing IOS's own
        # CDP/keepalives — the only legitimate speakers on the segment) and
        # demand the host side stays silent for 5 s: without the hardening
        # the host's own MLD/DAD noise floods the link (6 frames / 2 s).
        if harness.l2only_supported():
            for console in (c1, c2):
                _eth_shutdown(console, shut=True)
            harness.assert_idle_silence(t1, t2, bridge)
            for console in (c1, c2):
                _eth_shutdown(console, shut=False)
            assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
            assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        # delay 100: netem on both anchors (each impairs one direction),
        # one-way ~100 ms => RTT grows by ~200 ms — netem is family-blind,
        # both families ride the same qdisc
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"filters": {"delay": [100]}})
        assert "netem" in harness.qdiscs(t1) and "netem" in harness.qdiscs(t2), (
            harness.qdiscs(t1),
            harness.qdiscs(t2),
        )
        delayed = labi["r1"].wait_ping(r2_v4)
        assert delayed["success"] == 100, delayed["raw"]
        delayed6 = labi["r1"].wait_ping(r2_v6)
        assert delayed6["success"] == 100, delayed6["raw"]
        print(f"..   delay 100: v4 {baseline['avg']}->{delayed['avg']} ms, v6 {baseline6['avg']}->{delayed6['avg']} ms")
        assert delayed["avg"] >= 150, (baseline, delayed)
        # The v6 twin is asserted from the capture's own timestamps, not from
        # the guest's report: the dynamips-emulated classic IOS under-reports
        # its ping ipv6 RTT by ~40 % of a delayed round trip (reproducible:
        # report ~125-135 ms while a pcap on the anchor shows the v6 echo
        # request->reply taking the same ~230 ms as v4 — the wire is correct,
        # the reporter is not; the pings' order does not matter).
        capture = compute.call("POST", f"/projects/{pid}/links/{lid}/capture/start", {"data_link_type": "DLT_EN10MB"})
        labi["r1"].ping(r2_v6)
        time.sleep(1)
        compute.call("POST", f"/projects/{pid}/links/{lid}/capture/stop")
        wire6 = harness.pcap_icmp_rtt(capture["capture_file_path"], "86dd")
        print(f"..   delay 100 (capture): v6 wire round trip {wire6:.0f} ms")
        assert wire6 is not None and wire6 >= 60, wire6
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"filters": {}})
        assert "netem" not in harness.qdiscs(t1), harness.qdiscs(t1)
        fast = labi["r1"].wait_ping(r2_v4)
        assert fast["success"] == 100 and fast["avg"] < harness.FAST_RTT_MS, fast
        fast6 = labi["r1"].wait_ping(r2_v6)
        assert fast6["success"] == 100 and fast6["avg"] < harness.FAST_RTT_MS, fast6

        # suspend: anchor admin-down, traffic dead; resume restores it
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"suspend": True})
        assert not harness.tap_up(t1)
        dead = labi["r1"].ping(r2_v4, repeat=3)
        assert dead["success"] == 0, dead["raw"]
        dead6 = labi["r1"].ping(r2_v6, repeat=3)
        assert dead6["success"] == 0, dead6["raw"]
        compute.call("PUT", f"/projects/{pid}/links/{lid}", {"suspend": False})
        assert harness.tap_up(t1)
        assert labi["r1"].wait_ping(r2_v4)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6)["success"] == 100

        # capture: AF_PACKET on the anchor writes a real pcap — both
        # families inside the window, both ethertypes on the wire
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

        # serial link between the same routers: per-port exclusion keeps it
        # on the relay, where the real traffic still crosses
        serial = compute.create_link(pid, (r1_id, *SERIAL), (r2_id, *SERIAL))
        assert serial["kernel_datapath"] is False, serial
        harness.configure_ios(c1, "R1", serial_ip="10.2.2.1", clock=True)
        harness.configure_ios(c2, "R2", serial_ip="10.2.2.2")
        relay_ping = labi["r1"].wait_ping("10.2.2.2")
        assert relay_ping["success"] == 100, relay_ping["raw"]
        compute.call("DELETE", f"/projects/{pid}/links/{serial['link_id']}")

        # delete / re-create the kernel link: anchors survive, the bridge
        # goes and comes back
        compute.call("DELETE", f"/projects/{pid}/links/{lid}")
        assert harness.bridge_members(bridge) is None
        assert harness.tap_exists(t1) and harness.tap_exists(t2)
        link = compute.create_link(pid, (r1_id, *ETH), (r2_id, *ETH))
        lid = link["link_id"]
        bridge = harness.link_bridge_name(lid)
        assert link["kernel_datapath"] is True, link
        assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        # stop / start keeps the whole wiring (the Dynamips hypervisor
        # outlives ``vm stop``); the restarted router just reboots and is
        # reconfigured
        print(".. stopping and restarting R1")
        compute.call("POST", f"/projects/{pid}/nodes/{r1_id}/stop")
        assert harness.tap_exists(t1)
        assert harness.bridge_members(bridge) == sorted([t1, t2])
        compute.call("POST", f"/projects/{pid}/nodes/{r1_id}/start")
        c1 = labi["r1"].boot_wait()
        assert harness.bridge_members(bridge) == sorted([t1, t2])
        labi["r1"].reconfigure()
        assert labi["r1"].wait_ping(r2_v4, attempts=5)["success"] == 100
        assert labi["r1"].wait_ping(r2_v6, attempts=5)["success"] == 100

        labi.close_channels()
    except BaseException:
        harness.release(server, pid, failed=True)
        raise
    harness.release(server, pid, failed=False)

    # deleting the project closes the nodes: anchors and bridges go with them
    assert harness.wait_until(lambda: not harness.tap_exists(t1) and not harness.tap_exists(t2), timeout=15), (
        t1,
        t2,
    )
    assert harness.wait_until(lambda: harness.bridge_members(bridge) is None, timeout=10), bridge


def test_dynamips_relay_control():
    """Negative control: the same topology with ``enable_kernel_datapath =
    false`` (an isolated instance) wires nothing into the kernel — no
    per-link bridge, no enslavement — and still pings over the relay.

    Anchors DO exist here (a Dynamips router creates its port TAPs at start
    whenever the uBridge tap module is available — they are the adapter's
    interfaces, exactly like QEMU's); the server configuration only decides
    whether links are attached to them."""
    server = harness.live_server(kernel=False)

    labi = lab.deploy("dynamips-dumbbell", server, project_name="dyn-e2e-relay", gate_caps=False)
    pid = labi.project_id
    t1 = None
    try:
        r1_id, r2_id = labi["r1"].node_id, labi["r2"].node_id
        t1 = harness.anchor_name(r1_id, *ETH)
        r2_v4 = labi["r2"].address()
        r2_v6 = labi["r2"].address(family=6)

        link = labi.link("r1", "r2")
        lid = link["link_id"]
        assert link["kernel_datapath"] is False, link

        print(".. starting routers and waiting for IOS boots (relay)")
        labi.start()
        labi.boot()

        # no per-link kernel bridge on the relay: nothing is enslaved, the
        # anchor (if present) is just an idle port interface
        assert harness.bridge_members(harness.link_bridge_name(lid)) is None
        if harness.tap_exists(t1):
            assert not harness.tap_up(t1), "an unattached relay anchor should sit down"
            if harness.l2only_supported():
                # the L2 hardening is a creation-time property, not a
                # datapath one: relay anchors are pure L2 too
                harness.assert_pure_l2(t1)

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

    assert harness.wait_until(lambda: not harness.tap_exists(t1), timeout=15), t1
