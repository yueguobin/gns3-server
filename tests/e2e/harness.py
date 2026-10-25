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

"""
Shared harness for live end-to-end tests (pytest marker ``e2e``).

These tests drive a **real** gns3-server process against real uBridge, real
kernel interfaces and real emulator binaries — things a unit-test run cannot
provide (privileges, images, a live kernel). They exist to verify what mocks
cannot: that kernel bridges actually enslave anchors, that tc impairments
actually shape traffic, that a datapath actually forwards. Run them with::

    pytest -m e2e tests/e2e -s

The harness targets an **already running server** when ``GNS3_E2E_URL`` is
set (``GNS3_E2E_USER`` / ``GNS3_E2E_PASSWORD`` default to admin/admin), and
otherwise starts an **isolated instance** — its own config dir, controller
DB, project paths and free port, all under a temporary directory that is
removed on exit. Either way every test creates its own project and deletes
it again (``GNS3_E2E_KEEP=1`` keeps the project for inspection).

Environment knobs:

* ``GNS3_E2E_URL`` — target server, e.g. ``http://127.0.0.1:3080/v3``;
  when unset, an isolated instance is started for each test.
* ``GNS3_E2E_USER`` / ``GNS3_E2E_PASSWORD`` — credentials for the target.
* ``GNS3_E2E_CACHE`` — the e2e's own cache directory (default
  ``~/.cache/gns3-e2e``): the isolated instances serve their images from
  there, filled on demand — public appliance images are downloaded into it,
  Cisco-licensed ones copied in when a registry-pinned build is found in
  the source images dir.
* ``GNS3_E2E_IMAGES`` — the source images directory for those
  Cisco-licensed builds (default ``~/GNS3/images``; read-only to the e2e).
* ``GNS3_E2E_IDLEPC`` — use this idle-PC value for the dynamips routers
  instead of detecting one (see ``dynamips_idlepc``; without an idle-PC each
  router burns a full CPU core for the whole scenario).
* ``GNS3_E2E_QEMU_IMAGE`` — the qcow2 the QEMU scenarios run (default the
  registry's FRR appliance image, fetched and md5-verified on a cache miss;
  see ``ensure_qemu_image``).
* ``GNS3_E2E_DOCKER_IMAGE`` — the image the Docker scenarios run (default
  ``gns3/ubuntu:resolute``, pinned by digest and pulled on a cache miss; see
  ``ensure_docker_image``).
* ``GNS3_E2E_DOCKER_SOCKET`` — the Docker daemon socket the Docker guest
  driver talks to (default ``/var/run/docker.sock`` — the same daemon the
  server uses).
* ``GNS3_E2E_KEEP=1`` — keep the project (and the isolated instance) when a
  test fails, and print their ids, for inspection.
"""

import contextlib
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from websockets.sync.client import connect as ws_connect

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# tc lives in /usr/sbin on most distributions; subprocesses do not always
# inherit a PATH that has it.
TC = shutil.which("tc", path=os.environ.get("PATH", "") + ":/usr/sbin:/sbin")
# Reading addresses with iproute2 needs no privileges; the L2 assertions
# below refuse to pass silently when it is missing.
IP = shutil.which("ip", path=os.environ.get("PATH", "") + ":/usr/sbin:/sbin")

# IOS prompt as the last thing on the stream: any hostname/mode shape.
PROMPT_RE = re.compile(r"[A-Za-z0-9\-_.()/]+[>#]\s*$")

# Test-only default credentials (every real deployment overrides them via
# GNS3_E2E_USER / GNS3_E2E_PASSWORD); a freshly started isolated instance
# seeds exactly these.
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"

# The e2e's own cache — the isolated instances' images directory lives here
# (next to the idle-PC cache), deliberately NOT in the user's images dir: a
# test run must neither read whatever ambient images a host happens to have
# nor write into it. Public appliance images are downloaded into it on a
# miss; Cisco-licensed ones (which cannot be fetched) are copied in when a
# registry-pinned build is found in the source images dir. GNS3_E2E_CACHE
# moves the whole cache.
CACHE_DIR = os.environ.get("GNS3_E2E_CACHE", os.path.expanduser("~/.cache/gns3-e2e"))
CACHE_IMAGES = os.path.join(CACHE_DIR, "images")


def keep_on_failure():
    return os.environ.get("GNS3_E2E_KEEP") == "1"


# ---------------------------------------------------------------------------
# REST client
# ---------------------------------------------------------------------------


class Compute:
    """REST client for one server (controller API), token-authenticated."""

    def __init__(self, url, username=DEFAULT_USER, password=DEFAULT_PASSWORD):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.token = None

    def call(self, method, path, body=None, timeout=60):
        # S310: the base URL comes from the operator (GNS3_E2E_URL or the
        # isolated instance this harness just started), not untrusted input
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method.upper())  # noqa: S310
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                payload = resp.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise AssertionError(f"{method} {path} -> {e.code}: {detail}") from None

    def login(self):
        body = self.call("POST", "/access/users/authenticate", {"username": self.username, "password": self.password})
        self.token = body["access_token"]
        return self

    # -- common controller operations ------------------------------------

    def create_project(self, name="e2e"):
        return self.call("POST", "/projects", {"name": f"{name}-{int(time.time())}"})

    def create_dynamips_router(self, project_id, name, image, slots, platform="c7200", ram=512, idlepc=None):
        properties = {"platform": platform, "image": image, "ram": ram}
        if idlepc:
            properties["idlepc"] = idlepc
        properties.update(slots)
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {"compute_id": "local", "name": name, "node_type": "dynamips", "properties": properties},
        )

    def create_docker_node(self, project_id, name, image, adapters=1):
        """A standard Docker node (the veth datapath): the scenario addresses
        its eth0 from the host and pings through it."""
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {
                "compute_id": "local",
                "name": name,
                "node_type": "docker",
                "properties": {"image": image, "adapters": adapters, "console_type": "telnet"},
            },
        )

    def create_iou_node(self, project_id, name, image, ethernet_adapters=2, serial_adapters=2, ram=1024, nvram=256):
        """An IOU node: the real IOU binary running on this host, its IOS on
        the server's telnet console. The kernel scenario picks the image
        through ``iou_images`` (an L3 image — an L2 switching image does not
        take addresses on its switchports) and addresses Ethernet0/0."""
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {
                "compute_id": "local",
                "name": name,
                "node_type": "iou",
                "properties": {
                    "path": image,
                    "ethernet_adapters": ethernet_adapters,
                    "serial_adapters": serial_adapters,
                    "ram": ram,
                    "nvram": nvram,
                    # explicit ram/nvram, like the IOU appliance template
                    "use_default_iou_values": False,
                    "console_type": "telnet",
                },
            },
        )

    def create_iol_router(self, project_id, name, image, adapters=2):
        """An IOL runner container (iol-runner images), the appliance's
        template properties."""
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {
                "compute_id": "local",
                "name": name,
                "node_type": "docker",
                "properties": {
                    "image": image,
                    "adapters": adapters,
                    "console_type": "telnet",
                    "environment": "GNS3_IOL_RUNNER=1\nGNS3_IOL_STARTUP_CONFIG=iol-xe-base.txt",
                    "extra_volumes": ["/config"],
                },
            },
        )

    def create_qemu_node(
        self, project_id, name, image, adapters=2, adapter_type="e1000", ram=512, hda_disk_interface="virtio"
    ):
        """A QEMU VM node: the real qemu-system binary on this host running
        the image (a linked clone keeps the image pristine), the guest on the
        server's telnet console. The kernel scenario picks the image through
        ``qemu_images`` (the registry's FRR appliance qcow2 — the shell
        console driver drives it) and addresses its first adapter. The disk
        interface must be named: a raw node defaults to ``none``, which
        attaches no frontend device to the drive backend — the VM comes up
        diskless (the FRR appliance boots ide)."""
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {
                "compute_id": "local",
                "name": name,
                "node_type": "qemu",
                "properties": {
                    # a raw node carries no template, so the binary (and with
                    # it the platform) must be named explicitly
                    "qemu_path": "qemu-system-x86_64",
                    "hda_disk_image": image,
                    "hda_disk_interface": hda_disk_interface,
                    "adapter_type": adapter_type,
                    "adapters": adapters,
                    "ram": ram,
                    "linked_clone": True,
                    "console_type": "telnet",
                },
            },
        )

    def create_vpcs_node(self, project_id, name, startup_script=None):
        """A VPCS node: the real vpcs binary on this host behind the server's
        TCP console (the driver sends ``ip``/``ping`` like a user would). A
        kernel-datapath scenario additionally needs a build with ``-n``
        (no host auto-configuration) — see GNS3_E2E_VPCS and the ``vpcs_tap``
        capability."""
        properties = {"console_type": "telnet"}
        if startup_script is not None:
            properties["startup_script"] = startup_script
        return self.call(
            "POST",
            f"/projects/{project_id}/nodes",
            {"compute_id": "local", "name": name, "node_type": "vpcs", "properties": properties},
        )

    def create_link(self, project_id, a, b):
        return self.call(
            "POST",
            f"/projects/{project_id}/links",
            {
                "nodes": [
                    {"node_id": a[0], "adapter_number": a[1], "port_number": a[2]},
                    {"node_id": b[0], "adapter_number": b[1], "port_number": b[2]},
                ]
            },
        )

    def delete_project(self, project_id):
        self.call("DELETE", f"/projects/{project_id}")

    def node(self, project_id, node_id):
        return self.call("GET", f"/projects/{project_id}/nodes/{node_id}")

    def capabilities(self):
        return self.call("GET", "/computes/local").get("capabilities") or {}

    def dynamips_images(self):
        return [image["filename"] for image in self.call("GET", "/computes/local/dynamips/images")]

    def docker_images(self):
        return [image["image"] for image in self.call("GET", "/computes/local/docker/images")]

    def iou_images(self):
        return [image["filename"] for image in self.call("GET", "/computes/local/iou/images")]

    def qemu_images(self):
        return [image["filename"] for image in self.call("GET", "/computes/local/qemu/images")]


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

ISOLATED_CONFIG = """\
[Controller]
jwt_secret_key = 00000000000000000000000000000000000000000000000000000000000000e2
default_admin_username = admin
default_admin_password = admin

[Server]
host = 127.0.0.1
port = {port}
ubridge_path = {ubridge}
enable_kernel_datapath = {kernel}
report_errors = False
projects_path = {tmp}/projects
configs_path = {tmp}/configs
images_path = {images}
appliances_path = {tmp}/appliances
symbols_path = {tmp}/symbols

[Dynamips]
dynamips_path = {dynamips}
images_path = {images}
allocate_aux_console_ports = False
mmap_support = False
sparse_memory_support = False
ghost_ios_support = False

[VPCS]
vpcs_path = {vpcs}
"""


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    """A server under test: an external one, or a freshly started isolated
    instance (own config dir — the controller DB and every path follow it —
    under a temporary directory removed on stop)."""

    def __init__(self, compute, process=None, tmpdir=None):
        self.compute = compute
        self.process = process
        self.tmpdir = tmpdir

    @property
    def isolated(self):
        return self.process is not None

    def log_tail(self, lines=40):
        if not self.tmpdir:
            return ""
        path = os.path.join(self.tmpdir, "server.log")
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return "".join(f.readlines()[-lines:])

    def _stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def stop(self):
        self._stop_process()
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def restart(self, kernel=True):
        """Restart an isolated instance in place: stop the process — the
        temporary directory (config, controller DB, projects) survives — and
        start a new one on the same paths with the given kernel-datapath
        setting and a fresh port. This is how the reopen-upgrade scenario
        flips the datapath choice and reopens a project created on the
        relay."""
        if not self.isolated:
            raise AssertionError("restart() needs an isolated instance (the harness did not start one)")
        self._stop_process()
        self.process, self.compute = _spawn_isolated(self.tmpdir, kernel)
        return self


def _spawn_isolated(tmpdir, kernel):
    """Start one isolated instance inside *tmpdir* (its config is written
    there; a fresh free port each boot) and return ``(process, compute)``,
    logged in. Shared by the first boot and by ``Server.restart``."""
    ubridge = shutil.which("ubridge")
    dynamips = shutil.which("dynamips")
    if not ubridge:
        pytest.skip("ubridge is not in PATH (needed to start an isolated instance)")
    if not dynamips:
        pytest.skip("dynamips is not in PATH (needed to start an isolated instance)")
    # the instance serves images from the e2e cache, never the user's own
    # images dir (the Cisco scenarios fill it on demand from there)
    images = CACHE_IMAGES
    os.makedirs(images, exist_ok=True)

    os.makedirs(os.path.join(tmpdir, "projects"), exist_ok=True)
    port = _free_port()
    # GNS3_E2E_VPCS points at a vpcs build with -n (tap mode without host
    # auto-configuration) — what the kernel-datapath scenario needs. The
    # local fork build (where this feature is developed) is the default when
    # present; otherwise the stock binary in PATH keeps the relay scenarios
    # running (the kernel scenario skips itself on the vpcs_tap capability).
    vpcs = os.environ.get("GNS3_E2E_VPCS")
    if not vpcs:
        fork_build = os.path.expanduser("~/myCode/GNS3/vpcs/src/vpcs")
        vpcs = fork_build if os.path.isfile(fork_build) else (shutil.which("vpcs") or "vpcs")
    config = ISOLATED_CONFIG.format(
        port=port, ubridge=ubridge, dynamips=dynamips, images=images, tmp=tmpdir, kernel=kernel, vpcs=vpcs
    )
    config_path = os.path.join(tmpdir, "gns3_server.conf")
    with open(config_path, "w") as f:
        f.write(config)

    log = open(os.path.join(tmpdir, "server.log"), "a")
    # S603: fixed argv, this interpreter, no shell involvement
    argv = [sys.executable, "-m", "gns3server", "--config", config_path]
    if os.environ.get("GNS3_E2E_DEBUG"):
        argv.append("-d")  # debug logging — the uBridge command stream lands in server.log
    process = subprocess.Popen(  # noqa: S603
        argv,
        cwd=REPO_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process.log = log  # keep the file object alive with the process handle
    compute = Compute(f"http://127.0.0.1:{port}/v3")

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            # S310: the port is ours, the host loopback
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v3/version", timeout=2):
                break
        except Exception:
            if process.poll() is not None:
                raise AssertionError(
                    f"isolated server exited early:\n{open(os.path.join(tmpdir, 'server.log')).read()[-2000:]}"
                )
            time.sleep(0.3)
    else:
        raise AssertionError("isolated server did not come up within 60s")

    compute.login()
    # The controller's connection to its own local compute comes up
    # asynchronously; until it reports capabilities the compute counts as
    # disconnected and a project open is refused. Same wait as live_server.
    if not wait_until(lambda: (compute.capabilities() or {}).get("version"), timeout=45):
        raise AssertionError(f"{compute.url}: the controller's local compute did not report capabilities within 45s")
    return process, compute


def _start_isolated(kernel):
    tmpdir = tempfile.mkdtemp(prefix="gns3-e2e-")
    process, compute = _spawn_isolated(tmpdir, kernel)
    return Server(compute, process, tmpdir)


def live_server(kernel=True):
    """The server under test.

    With ``GNS3_E2E_URL`` set, that server is used for kernel mode (it must
    already be configured for it); everything else starts an isolated
    instance. Relay-mode tests always need an isolated instance — the
    datapath choice is a server configuration.

    Either way this waits for the controller's local compute to finish
    connecting: the connection's ``GET /capabilities`` runs the uBridge
    probes (several ubridge spawns, seconds), and until it completes the
    controller caches a default dict with every capability None — a test
    reading capabilities in that window would wrongly skip itself.
    """
    url = os.environ.get("GNS3_E2E_URL")
    if url and kernel:
        compute = Compute(
            url,
            os.environ.get("GNS3_E2E_USER", "admin"),
            os.environ.get("GNS3_E2E_PASSWORD", "admin"),
        ).login()
        server = Server(compute)
    else:
        server = _start_isolated(kernel)
    if not wait_until(lambda: (server.compute.capabilities() or {}).get("version"), timeout=45):
        raise AssertionError(
            f"{server.compute.url}: the controller's local compute did not report capabilities within 45s"
        )
    return server


def release(server, project_id, failed=False):
    """Delete the test project (unless it should be kept), then stop the
    isolated instance if this harness started one."""
    if failed and keep_on_failure():
        print(f"\n!! kept project {project_id} on {server.compute.url} for inspection")
    else:
        try:
            server.compute.delete_project(project_id)
        except Exception as e:  # keep the original failure visible
            print(f"!! could not delete project {project_id}: {e}")
    if server.isolated and not (failed and keep_on_failure()):
        server.stop()


# ---------------------------------------------------------------------------
# WebSocket notification collector
# ---------------------------------------------------------------------------


class WebSocketCollector:
    """Collects server notification messages from one WebSocket.

    The e2e tests are synchronous; this is a sync facade over ``websockets``'
    sync client: a background thread drains the socket into a list and the
    test polls :meth:`events` / :meth:`wait_events`. Messages are the
    server's ``{"action": ..., "event": ...}`` JSON objects.
    """

    def __init__(self, server, path, open_timeout=15):
        base = server.compute.url.replace("https", "wss", 1).replace("http", "ws", 1)
        self._ws = ws_connect(f"{base}{path}?token={server.compute.token}", open_timeout=open_timeout)
        self._messages = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        while not self._stop.is_set():
            try:
                raw = self._ws.recv(timeout=0.5)
            except TimeoutError:
                continue
            except Exception:
                break  # socket closed under us: stop draining
            try:
                self._messages.append(json.loads(raw))
            except ValueError:
                continue

    def messages(self, action=None):
        """Every message received so far, optionally only for one action."""
        messages = list(self._messages)
        if action is not None:
            messages = [m for m in messages if m.get("action") == action]
        return messages

    def events(self, action):
        """The ``event`` payload of every message carrying the action."""
        return [m.get("event") for m in self.messages(action)]

    def wait_events(self, action, count=1, timeout=10):
        """Poll until at least *count* events of the action arrived (or the
        timeout passes); returns whatever was collected either way."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            events = self.events(action)
            if len(events) >= count:
                return events
            time.sleep(0.2)
        return self.events(action)

    def close(self):
        self._stop.set()
        with contextlib.suppress(Exception):
            self._ws.close()
        self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Dynamips idle-PC (CPU)
# ---------------------------------------------------------------------------

# Detected values, keyed by image identity; the detection needs a throwaway
# boot, so it is worth caching across runs.
IDLEPC_CACHE_PATH = os.path.join(CACHE_DIR, "idlepc.json")


def dynamips_idlepc(server, image, platform="c7200", ram=512):
    """The idle-PC value the scenarios' dynamips routers should be created
    with — detected once per image and cached.

    Without one, dynamips busy-waits and burns a *full CPU core per router*
    for the whole scenario: the e2e creates raw nodes, and no template
    supplies an idle-PC. Detection goes through the controller's
    ``auto_idlepc`` endpoint — the GUI's idle-PC finder path: a throwaway
    project boots the image, candidate values are validated by measuring the
    actual process CPU (first candidate under 70 % wins) — and the result is
    cached in ``~/.cache/gns3-e2e/idlepc.json`` keyed by the image's
    checksum, so the cost is paid once per image, not once per run.

    ``GNS3_E2E_IDLEPC`` overrides detection and cache entirely. Any failure
    returns None: the scenarios then run without an idle-PC (and burn the
    cores) rather than fail on a CPU optimisation.
    """
    override = os.environ.get("GNS3_E2E_IDLEPC")
    if override:
        return override

    checksum = None
    for entry in server.compute.call("GET", "/computes/local/dynamips/images"):
        if entry["filename"] == image:
            checksum = entry.get("md5sum")
            break
    key = f"{image}:{checksum}" if checksum else image

    cache = {}
    try:
        with open(IDLEPC_CACHE_PATH) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        pass
    if cache.get(key):
        print(f".. idle-PC {cache[key]} for {image} (cached)")
        return cache[key]

    print(f".. detecting an idle-PC for {image} (once per image — this takes a few minutes)")
    try:
        result = server.compute.call(
            "POST",
            "/computes/local/dynamips/auto_idlepc",
            {"platform": platform, "image": image, "ram": ram},
            timeout=600,
        )
    except Exception as e:
        print(f".. idle-PC detection failed ({e}); the routers will burn a core each")
        return None
    idlepc = (result or {}).get("idlepc")
    if not idlepc:
        print(f".. no idle-PC value found for {image}; the routers will burn a core each")
        return None
    cache[key] = idlepc
    try:
        os.makedirs(os.path.dirname(IDLEPC_CACHE_PATH), exist_ok=True)
        # write-then-rename: parallel tests share this file, and a reader
        # must never see a half-written JSON (a lost update is fine — the
        # loser's detection simply re-runs next time)
        partial = IDLEPC_CACHE_PATH + ".part"
        with open(partial, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        os.replace(partial, IDLEPC_CACHE_PATH)
    except OSError as e:
        print(f".. could not write the idle-PC cache {IDLEPC_CACHE_PATH}: {e}")
    print(f".. idle-PC {idlepc} for {image} (cached for later runs)")
    return idlepc


# ---------------------------------------------------------------------------
# IOS console (dynamips telnet console)
# ---------------------------------------------------------------------------


class IOSConsole:
    """A deliberately dumb IOS console driver.

    ``run`` sends one line and returns *everything* received until the prompt
    is back and the stream has been quiet — no split between "consumed" and
    "remaining" buffers, so a caller can always parse the whole exchange.
    Pacing matters: the IOS console drops characters typed while it is busy
    (a long boot, the tail of a previous command), so every line goes out
    after the previous exchange has settled.
    """

    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(0.3)
        self.buf = ""

    def _read(self):
        """Drain whatever arrived; True when at least one byte was read."""
        got = False
        while True:
            try:
                data = self.sock.recv(65536)
            except TimeoutError:
                return got
            if not data:
                return got
            self.buf += data.decode(errors="replace")
            got = True

    def run(self, line, timeout=30, quiet=0.8):
        """Send one line; return the full exchange once the prompt is back
        and nothing new arrived for *quiet* seconds."""
        self.buf = ""
        self.sock.sendall((line + "\r").encode())
        deadline = time.time() + timeout
        last_growth = time.time()
        while time.time() < deadline:
            if self._read():
                last_growth = time.time()
            if PROMPT_RE.search(self.buf) and time.time() - last_growth > quiet:
                break
            time.sleep(0.05)
        out, self.buf = self.buf, ""
        return out

    def boot_wait(self, timeout=360, straight_prompt=False):
        """Wait until the IOS prompt is ready, answering the initial config
        dialog if it appears. The prompt only counts once the stream around
        it goes quiet — a boot banner still printing is not a prompt.

        ``straight_prompt`` accepts a quiet prompt without the "Press RETURN"
        sentinel — images that boot straight from a startup config into the
        CLI (IOL from its NVRAM) never print it."""
        answered = False
        deadline = time.time() + timeout
        self.buf = ""
        last_growth = time.time()
        while time.time() < deadline:
            if self._read():
                last_growth = time.time()
            if not answered and "initial configuration dialog" in self.buf:
                self.sock.sendall(b"no\r")
                answered = True
                last_growth = time.time()
            sentinel = straight_prompt or "Press RETURN" in self.buf or answered
            prompt_seen = sentinel and PROMPT_RE.search(self.buf)
            if prompt_seen and time.time() - last_growth > 1.2:
                self.buf = ""
                return
            if not prompt_seen and time.time() - last_growth > 1.5:
                # nudge the "Press RETURN" prompt along; never nudge an
                # already-visible prompt (the echo would restart the quiet
                # timer forever)
                self.sock.sendall(b"\r")
            time.sleep(0.1)
        raise AssertionError(f"IOS console did not reach a prompt; tail: {self.buf[-300:]!r}")

    def close(self):
        self.sock.close()


def ios_console(server, project_id, node_id):
    """The telnet console of a node running IOS (dynamips, IOU, IOL
    container): the server-side telnet endpoint around the emulator's own
    stdio — same driver for all of them."""
    node = server.compute.node(project_id, node_id)
    host = node["console_host"] if node["console_host"] not in ("0.0.0.0", "::") else "127.0.0.1"
    return IOSConsole(host, node["console"])


def vpcs_console(server, project_id, node_id):
    """The console of a VPCS node: the vpcs binary's own TCP daemon behind
    the server-side console — same dumb driver (its prompt ``PC1>`` matches
    the shared prompt regex)."""
    return ios_console(server, project_id, node_id)


def configure_ios(
    console, hostname, eth_ip=None, eth_ipv6=None, serial_ip=None, clock=False, eth_if="f1/0", serial_if="s2/0"
):
    """Baseline config on a freshly booted router: hostname, no console spam,
    optional interface addresses. ``eth_ipv6`` configures the same interface
    dual-stack (a /64 prefix); ipv6 unicast-routing is deliberately left off —
    the routers stay pure hosts, so no RAs go out and the link stays quiet
    (directly connected pings need no forwarding)."""
    console.run("enable")
    console.run("conf t")
    console.run(f"hostname {hostname}")
    console.run("no ip domain-lookup")
    # global form: console logging off in one step, no line sub-mode to lose
    # characters in
    console.run("no logging console")
    if eth_ip or eth_ipv6:
        console.run(f"interface {eth_if}")
        if eth_ip:
            console.run(f"ip address {eth_ip} 255.255.255.0")
        if eth_ipv6:
            console.run(f"ipv6 address {eth_ipv6}/64")
        console.run("no shutdown")
        console.run("exit")
    if serial_ip:
        console.run(f"interface {serial_if}")
        console.run(f"ip address {serial_ip} 255.255.255.0")
        if clock:
            console.run("clock rate 64000")
        console.run("no shutdown")
        console.run("exit")
    console.run("end")


# ---------------------------------------------------------------------------
# Linux shell console (the FRR qcow2 guest)
# ---------------------------------------------------------------------------

# The sentinel prompt the shell driver installs on the guest after login:
# the guest's own prompt shape (hostname, shell, or the vtysh CLI) is not
# knowable across images, but "the driver set the prompt itself" always is.
# The lookbehind keeps the echoed `export PS1=…GNS3E2E#` line from matching.
SHELL_PROMPT = "GNS3E2E#"
SHELL_PROMPT_RE = re.compile(r"(?<!=)GNS3E2E#\s*$")

# The FRR appliance's documented console credentials (its usage notes ship
# with the image: root/root).
GUEST_USER = "root"
GUEST_PASSWORD = "root"

# The guest's line editor (busybox ash) queries the cursor position with
# every prompt (ESC [6n) and processes no further input until the terminal
# answers (ESC [<row>;<col>R) — a driver that never answers never sees a
# quiet prompt, exactly the lesson the SR Linux console taught. The answer
# claims column 1: the editor only wants to know where its line starts.
CPR_QUERY = "\x1b[6n"
CPR_REPLY = b"\x1b[1;1R"


class ShellConsole:
    """A deliberately dumb Linux shell console driver — the shell twin of
    the IOS one: same send-and-settle flow, but it settles on the sentinel
    prompt it installed itself after login (see SHELL_PROMPT).

    ``run`` sends one line and returns everything received until that
    sentinel is back and the stream has been quiet. No state to track —
    every line is a fresh shell command.
    """

    def __init__(self, host, port, username=GUEST_USER, password=GUEST_PASSWORD):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(0.3)
        self.buf = ""
        self._cpr_answered = 0
        self._username = username
        self._password = password

    def _reset(self):
        """Clear the exchange buffer (and with it the CPR bookkeeping that
        counts against it)."""
        self.buf = ""
        self._cpr_answered = 0

    def _read(self):
        """Drain whatever arrived; True when at least one byte was read."""
        got = False
        while True:
            try:
                data = self.sock.recv(65536)
            except TimeoutError:
                return got
            if not data:
                return got
            self.buf += data.decode(errors="replace")
            got = True

    def _answer_cpr(self):
        """Answer every cursor-position query the guest's line editor has
        sent and is blocking on (see CPR_REPLY) — once each."""
        queries = self.buf.count(CPR_QUERY)
        for _ in range(queries - self._cpr_answered):
            self.sock.sendall(CPR_REPLY)
        self._cpr_answered = queries

    def run(self, line, timeout=30, quiet=0.8):
        """Send one line; return the full exchange once the sentinel prompt
        is back and nothing new arrived for *quiet* seconds."""
        return self._send_and_settle(line + "\r", timeout=timeout, quiet=quiet)

    def run_script(self, block, timeout=60, quiet=1.0):
        """Stage a multi-line block through the console as one burst (a
        heredoc body produces no prompt per line, so per-line ``run`` calls
        would each sit out their timeout inside it) and settle once. The
        block's newlines become carriage returns — what the console's tty
        expects of an entered line."""
        return self._send_and_settle(block.replace("\n", "\r") + "\r", timeout=timeout, quiet=quiet)

    def _send_and_settle(self, payload, timeout, quiet):
        self._reset()
        self.sock.sendall(payload.encode())
        deadline = time.time() + timeout
        last_growth = time.time()
        while time.time() < deadline:
            if self._read():
                last_growth = time.time()
            self._answer_cpr()
            if SHELL_PROMPT_RE.search(self.buf) and time.time() - last_growth > quiet:
                break
            time.sleep(0.05)
        out = self.buf
        self._reset()
        return out

    def boot_wait(self, timeout=300, banner=None):
        """Wait out the boot, log in, and install the sentinel prompt.

        Handles the shapes a minimal appliance guest can take, in whatever
        order they appear: a ``login:`` prompt (the credentials come from
        the constructor), a vtysh the image starts on the console (the
        FRRouting banner — the FRR appliance auto-logins straight into it),
        and a shell reached without either. Whenever the stream has gone
        quiet without the sentinel, the driver answers whichever of those
        is on the tail of the stream — or (re)installs the sentinel prompt,
        which makes an early miss harmless: text typed into a boot banner
        or a failed login simply re-prompts, and the loop answers that
        instead.

        ``banner`` pins the boot-success criterion to the guest's fixed
        transcript (the pinned-image scenarios pass the banner the image
        prints): the prompt only counts as ready when the banner was seen,
        so a wrong image sitting in the cache fails in seconds with "not
        the pinned guest" instead of a timeout.
        """
        sent_username = sent_password = left_vtysh = False
        deadline = time.time() + timeout
        self._reset()
        last_growth = time.time()
        while time.time() < deadline:
            if self._read():
                last_growth = time.time()
            self._answer_cpr()
            if SHELL_PROMPT_RE.search(self.buf) and time.time() - last_growth > 1.2:
                if banner is not None and not banner.search(self.buf):
                    raise AssertionError(
                        f"the console reached a prompt without the pinned boot banner {banner.pattern!r} — "
                        f"not the pinned guest image? tail: {self.buf[-300:]!r}"
                    )
                self._reset()
                return
            if time.time() - last_growth > 1.5:
                tail = self.buf[-120:]
                if not sent_username and re.search(r"login:\s*$", tail):
                    self.sock.sendall((self._username + "\r").encode())
                    sent_username = True
                elif sent_username and not sent_password and re.search(r"assword:\s*$", tail):
                    self.sock.sendall((self._password + "\r").encode())
                    sent_password = True
                elif not left_vtysh and "this is FRRouting" in self.buf:
                    # the console opened in the vtysh CLI (with or without a
                    # login in front of it) — leave it for the shell
                    self.sock.sendall(b"exit\r")
                    left_vtysh = True
                else:
                    self.sock.sendall(f"export PS1={SHELL_PROMPT}\r".encode())
                last_growth = time.time()
            time.sleep(0.1)
        raise AssertionError(f"Linux console did not reach the sentinel prompt; tail: {self.buf[-300:]!r}")

    def close(self):
        self.sock.close()


def shell_console(server, project_id, node_id):
    """The telnet console of a node running a plain Linux guest (the FRR
    qcow2): the server-side telnet endpoint around QEMU's own serial
    console."""
    node = server.compute.node(project_id, node_id)
    host = node["console_host"] if node["console_host"] not in ("0.0.0.0", "::") else "127.0.0.1"
    return ShellConsole(host, node["console"])


GUEST_BASELINE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "guest-baseline.sh")


def configure_linux(console, eth_ip=None, eth_ipv6=None, eth_if="eth0"):
    """Baseline config on a freshly booted Linux guest: stage the shared
    guest-baseline script (``tests/e2e/configs/``) through the console and
    run it with the interface and the addresses as arguments — one
    reviewed, idempotent artifact instead of ad-hoc commands, so a re-run
    after a node restart is safe. The guest stays a pure host — no routing
    daemon runs, so no RAs or hellos go out and the link stays quiet
    (directly connected pings need no forwarding)."""

    with open(GUEST_BASELINE_SCRIPT) as f:
        script = f.read().rstrip("\n")
    v4 = f"{eth_ip}/24" if eth_ip else ""
    v6 = f"{eth_ipv6}/64" if eth_ipv6 else ""
    console.run_script(f"sh -s -- {eth_if} {v4} {v6} <<'GNS3E2E'\n{script}\nGNS3E2E")


# "No impairment applied" RTT bound for the fast-path asserts of the
# kernel-datapath scenarios: an unimpaired link measures ~20-45 ms on the
# IOS-based nodes (4 ms-quantized RTT; host scheduling jitter has pushed
# three-packet averages to 56 measured), while the delayed regime those
# asserts contrast against is >= 150 ms. 100 separates the two with
# headroom for a blip.
FAST_RTT_MS = 100


def ping(console, target, repeat=3, timeout=1):
    """Run an IOS ping; returns {success, avg, raw} (success in percent).

    An IPv6 literal needs IOS's ``ping ipv6`` form; the summary lines the
    parsers read are the same shape for both families."""
    family = "ipv6 " if ":" in target else ""
    out = console.run(f"ping {family}{target} repeat {repeat} timeout {timeout}", timeout=repeat * timeout + 20)
    success = re.search(r"Success rate is (\d+) percent", out)
    rtt = re.search(r"round-trip min/avg/max = (\d+)/(\d+)/(\d+)", out)
    return {"success": int(success.group(1)) if success else 0, "avg": int(rtt.group(2)) if rtt else None, "raw": out}


def wait_ping(console, target, attempts=4, repeat=3, timeout=1):
    """ping until it fully succeeds (the first packets of a fresh adjacency
    are legitimately lost while the line protocol settles or ARP resolves);
    returns the last result either way."""
    result = None
    for _ in range(attempts):
        result = ping(console, target, repeat=repeat, timeout=timeout)
        if result["success"] == 100:
            return result
        time.sleep(1.5)
    return result


_PING_LOSS_RE = re.compile(r"(\d+)% packet loss")
_PING_RTT_RE = re.compile(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/[\d.]+ ms")
_PING_REPLY_RE = re.compile(r"\bicmp_seq=\d+")


def _ping_parse(output, count):
    """(loss percent, avg rtt or None) from iputils ping output — the
    Ubuntu containers and the FRR qcow2 guest all run iputils `ping`.

    The summary line can be lost if the exec/console stream truncates: with
    replies visible but no summary, derive the loss from the replies
    actually seen instead of reporting a phantom 100 %.
    """
    loss = _PING_LOSS_RE.search(output)
    if loss is not None:
        loss_pct = int(loss.group(1))
    else:
        replies = len(_PING_REPLY_RE.findall(output))
        loss_pct = round(100 * max(0, count - replies) / count) if replies else 100
    rtt = _PING_RTT_RE.search(output)
    return loss_pct, (float(rtt.group(1)) if rtt else None)


def linux_ping(console, target, repeat=3, timeout=1):
    """Run a Linux guest's ping (iputils — the FRR qcow2 guest); returns
    {success, avg, raw} (success in percent). A v6 literal needs no special
    form — the same command shape serves both families."""

    out = console.run(f"ping -c {repeat} -W {timeout} {target}", timeout=repeat * timeout + 20)
    loss, avg = _ping_parse(out, repeat)
    return {"success": 100 - loss, "avg": avg, "raw": out}


def wait_linux_ping(console, target, attempts=4, repeat=3, timeout=1):
    """The Linux twin of wait_ping: ping until it fully succeeds (the first
    exchange of a fresh adjacency is ARP/ND); returns the last result either
    way."""

    result = None
    for _ in range(attempts):
        result = linux_ping(console, target, repeat=repeat, timeout=timeout)
        if result["success"] == 100:
            return result
        time.sleep(1.5)
    return result


def vpcs_ping(console, target, count=5, timeout=1):
    """Run a VPCS ping; returns {success, avg, raw} (success in percent).
    The reply lines are ``<host> icmp_seq=<n> ttl=<t> time=<ms> ms`` in both
    families (VPCS prints the same shape for v4 and v6 targets)."""

    out = console.run(f"ping {target} -c {count} -w {int(timeout * 1000)}", timeout=count * timeout + 25)
    replies = re.findall(r"icmp_seq=\d+ ttl=\d+ time=([\d.]+) ms", out)
    return {
        "success": int(100 * len(replies) / count),
        "avg": round(sum(float(rtt) for rtt in replies) / len(replies), 1) if replies else None,
        "raw": out,
    }


def wait_vpcs_ping(console, target, attempts=4, count=5, timeout=1):
    """The VPCS twin of wait_ping: the first exchange of a fresh adjacency
    is ARP (a lost first ping is legitimate), so retry until it fully
    succeeds; returns the last result either way."""

    result = None
    for _ in range(attempts):
        result = vpcs_ping(console, target, count=count, timeout=timeout)
        if result["success"] == 100:
            return result
        time.sleep(1.5)
    return result


# ---------------------------------------------------------------------------
# Docker guest driver (Docker Engine API over the daemon socket)
# ---------------------------------------------------------------------------

# The e2e needs two things the server's REST surface does not expose: the
# identity of the image a container runs (to verify a cached image is the
# pinned build) and a way to run commands inside a booted container (address
# the guest, drive real ICMP from it). Both are plain Engine API calls over
# the same socket the server itself uses.

DOCKER_SOCKET = os.environ.get("GNS3_E2E_DOCKER_SOCKET", "/var/run/docker.sock")

# The images the Docker scenarios run — the registry's own appliances, so
# the e2e exercises exactly what users pull: the Ubuntu guest appliance for
# the host-behavior scenarios and the FRR router image (the frr-docker and
# frr-docker-lite appliances; ``FRR_PROFILE`` selects the daemon set) for
# the routing-protocol scenarios to come. Both the registry digest (what to
# pull on a cache miss; a rolling tag resolved once and then pinned forever)
# and the repo-digest it must resolve to locally are pinned, so every
# developer tests the same bytes. The Docker daemon is the cache: a hit
# costs no network, a miss pulls through the server's own route (the WebUI's
# path), and no cache + no registry skips the scenario.
DOCKER_IMAGE = "gns3/ubuntu:resolute"
DOCKER_IMAGE_DIGEST = "sha256:b721ec166664a6fa7738a8175cfac1405f25e7464720c854cd98011153576a82"
FRR_DOCKER_IMAGE = "gns3/frr"
FRR_DOCKER_IMAGE_DIGEST = "sha256:919e76c92ce74cf82658c6f93a7fa8f0ccbd4a562e2f6b3f83780f67e1ec3b67"


class _UnixHTTPConnection(http.client.HTTPConnection):
    """An HTTP connection speaking over a Unix socket (stdlib only)."""

    def __init__(self, socket_path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


class DockerDaemon:
    """Minimal Docker Engine API client over the daemon socket."""

    def __init__(self, socket_path=DOCKER_SOCKET, timeout=60):
        self.socket_path = socket_path
        self.timeout = timeout

    def _request(self, method, path, body=None, timeout=None):
        conn = _UnixHTTPConnection(self.socket_path, timeout or self.timeout)
        try:
            data = None
            headers = {}
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException) as e:
            raise AssertionError(f"docker {method} {path} failed: {e}") from None
        finally:
            conn.close()

    def container_id(self, name):
        """The id of the container called *name* (any state), or None. The
        controller's node payload does not carry a Docker node's container
        id (a compute-side read-only field); the daemon knows the container
        by the deterministic name the server gives it (DockerVM.docker_name:
        ``GNS3.<node name>.<project id>``)."""
        filters = urllib.parse.quote(json.dumps({"name": [name]}), safe="")
        status, payload = self._request("GET", f"/containers/json?all=1&filters={filters}")
        assert status == 200, f"docker container list -> HTTP {status}: {payload[:300]!r}"
        for container in json.loads(payload):
            if name in [entry.lstrip("/") for entry in container.get("Names") or []]:
                return container["Id"]
        return None

    def image_inspect(self, reference):
        """The image record stored under *reference*, or None."""
        status, payload = self._request("GET", "/images/" + urllib.parse.quote(reference, safe="") + "/json")
        if status == 404:
            return None
        assert status == 200, f"docker image inspect {reference} -> HTTP {status}: {payload[:300]!r}"
        return json.loads(payload)

    def pull(self, reference, timeout=600):
        """Pull *reference* (digest-pinned when the caller wants
        reproducibility). Raises AssertionError on the daemon's error
        stream — offline, unknown manifest, ..."""
        status, payload = self._request(
            "POST", "/images/create?fromImage=" + urllib.parse.quote(reference, safe=""), timeout=timeout
        )
        if status != 200:
            raise AssertionError(f"docker pull {reference} -> HTTP {status}: {payload[:300]!r}")
        # the body is a stream of JSON progress objects; any object carrying
        # an error key (in either shape) is a failure
        text = payload.decode(errors="replace").strip()
        decoder = json.JSONDecoder()
        while text:
            try:
                obj, index = decoder.raw_decode(text)
            except ValueError:
                break
            error = obj.get("error") or (obj.get("errorDetail") or {}).get("message")
            if error:
                raise AssertionError(f"docker pull {reference} failed: {error}")
            text = text[index:].strip()

    def exec(self, container_id, cmd, timeout=60):
        """Run *cmd* inside a container; returns (exit_code, combined
        output)."""
        status, payload = self._request(
            "POST",
            f"/containers/{container_id}/exec",
            {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": list(cmd)},
        )
        assert status == 201, f"docker exec create in {container_id[:12]} -> HTTP {status}: {payload[:300]!r}"
        exec_id = json.loads(payload)["Id"]
        try:
            status, payload = self._request(
                "POST", f"/exec/{exec_id}/start", {"Detach": False, "Tty": False}, timeout=timeout
            )
        except AssertionError as e:
            # A stalled stream is diagnosable: was the process still running
            # (stream open, nothing flushed) or already gone?
            raise AssertionError(f"{e} (exec {exec_id[:12]} still running: {self._exec_running(exec_id)})") from None
        assert status == 200, f"docker exec start {exec_id[:12]} -> HTTP {status}: {payload[:300]!r}"
        # the hijacked stream multiplexes stdout/stderr: 8-byte frame headers
        # (stream id + big-endian length) — demultiplex into one buffer
        output = bytearray()
        index = 0
        while index + 8 <= len(payload):
            length = int.from_bytes(payload[index + 4 : index + 8], "big")
            output += payload[index + 8 : index + 8 + length]
            index += 8 + length
        status, payload = self._request("GET", f"/exec/{exec_id}/json")
        assert status == 200, f"docker exec inspect {exec_id[:12]} -> HTTP {status}: {payload[:300]!r}"
        return json.loads(payload)["ExitCode"], output.decode(errors="replace")

    def _exec_running(self, exec_id):
        """Whether an exec is still running (diagnostic only, never raises)."""
        try:
            status, payload = self._request("GET", f"/exec/{exec_id}/json", timeout=10)
            return json.loads(payload).get("Running") if status == 200 else f"HTTP {status}"
        except (AssertionError, ValueError):
            return "unknown"

    def cp(self, container_id, tar_bytes, path):
        """Upload a tar archive into the container at *path* (``docker cp``
        in); the daemon extracts it, honoring the entries' modes."""
        conn = _UnixHTTPConnection(self.socket_path, self.timeout)
        try:
            conn.request(
                "PUT",
                f"/containers/{container_id}/archive?path={urllib.parse.quote(path)}",
                body=tar_bytes,
                headers={"Content-Type": "application/x-tar"},
            )
            response = conn.getresponse()
            payload = response.read()
            assert response.status == 200, (
                f"docker cp into {container_id[:12]} -> HTTP {response.status}: {payload[:300]!r}"
            )
        except (OSError, http.client.HTTPException) as e:
            raise AssertionError(f"docker cp into {container_id[:12]} failed: {e}") from None
        finally:
            conn.close()


def ensure_docker_image(server, image=DOCKER_IMAGE, digest=DOCKER_IMAGE_DIGEST):
    """The Docker image the scenarios run, ensured present locally.

    Defaults to the Ubuntu guest appliance (``image``/``digest`` re-point a
    scenario at another pinned build, e.g. the FRR router image). The pinned
    reference is pulled through the server's own pull route on a cache miss
    and verified against the pinned repo digest afterwards. A cached image
    that resolves to another digest is used with a warning if the pull fails
    (offline developer), but with no cached image and no registry the
    scenario skips. ``GNS3_E2E_DOCKER_IMAGE`` overrides the reference
    entirely (the operator then owns its content)."""

    override = os.environ.get("GNS3_E2E_DOCKER_IMAGE")
    daemon = DockerDaemon()
    if override:
        info = daemon.image_inspect(override)
        if info is None:
            pytest.skip(f"GNS3_E2E_DOCKER_IMAGE={override} is not present on the Docker daemon")
        print(f".. using GNS3_E2E_DOCKER_IMAGE={override} ({info['Id'][:19]}…)")
        return override

    reference = f"{image}@{digest}"
    info = daemon.image_inspect(image)
    if info is not None and any(digest in d for d in (info.get("RepoDigests") or [])):
        print(f".. Docker image {image} is cached at the pinned digest ({info['Id'][:19]}…)")
        return image
    if info is None:
        print(f".. Docker image {image} is not cached — pulling the pinned digest")
    else:
        print(f".. cached {image} is {info.get('RepoDigests') or info['Id'][:19]}…, not the pinned digest — pulling")
    try:
        server.compute.call("POST", "/computes/local/docker/images/pull", {"image": reference}, timeout=600)
    except AssertionError as e:
        if info is None:
            pytest.skip(f"Docker image {image} is not cached and could not be pulled: {e}")
        print(f".. pull failed ({e}); using the cached {image} — not the pinned build")
        return image
    print(f".. pulled {reference}")
    return image


# ---------------------------------------------------------------------------
# Test images: registry-pinned builds and the e2e cache
# ---------------------------------------------------------------------------

# The pinned builds each emulator's scenarios prefer, straight from the
# gns3-registry appliance tables (cisco-7200.gns3a, cisco-iou-l3.gns3a,
# frr.gns3a): filename, md5, size — newest first. The md5 is the identity
# of record: Cisco's download channel has shipped new bytes under an old
# pinned filename (the 17.18.2 build as x86_64_crb_linux-adventerprisek9-
# ms.iol), so a source file matches a pin by checksum under any name, and
# the cache stores it under the pin's canonical filename.
DYNAMIPS_IMAGE_PINS = (
    ("c7200-adventerprisek9-mz.153-3.XB12.image", "3d234a3793331c972776354531f87221", 131471340),
    ("c7200-advipservicesk9-mz.152-4.S7.image", "840a757e71bd73daaf9c77e5b02c6333", 93595460),
    ("c7200-advipservicesk9-mz.152-4.S6.image", "8d0bbd5473b58ef5bbc7e926f56e174a", 93586040),
    ("c7200-advipservicesk9-mz.152-4.S5.image", "cbbbea66a253f1dac0fcf81274dc778d", 87756936),
    ("c7200-adventerprisek9-mz.152-4.M11.image", "9a2005ad09ce1ec6fe7cf9af1e9b099e", 128487680),
    ("c7200-adventerprisek9-mz.124-24.T5.image", "6b89d0d804e1f2bb5b8bda66b5692047", 102345240),
    ("c7200-a3jk9s-mz.124-25g.image", "9c7cc9b3f3b3571411a7f62faaa2c036", 71528984),
    ("c7200-itpk9-mz.124-15.SW.image", "3334a0facdbd26164e83d3c201fff5b5", 46423952),
)
IOU_IMAGE_PINS = (
    ("x86_64_crb_linux-adventerprisek9-ms.17.18.2.iol", "34bf876c5b3c60f3ef4eb28eb8a176d7", 293729288),
    ("x86_64_crb_linux-adventerprisek9-ms.17.16.1a.iol", "39bdf959c3b99a3c81d66451f1cf0404", 293062920),
    ("x86_64_crb_linux-adventerprisek9-ms.iol", "5d584f6cfbeaadc87d55f613da1049ed", 292001512),
    ("x86_64_crb_linux-adventerprisek9-ms", "4a2fce8de21d1831fbceffd155e41ae7", 288947184),
)
# The FRR appliance's image is public — a cache miss can simply fetch it,
# which is what makes the QEMU scenarios self-bootstrapping (the IOSv build
# they used to need is Cisco-licensed and could not be fetched).
QEMU_IMAGE = "frr-8.2.2.qcow2"
QEMU_IMAGE_MD5 = "45cda6b991a1b9e8205a3a0ecc953640"
QEMU_IMAGE_BYTES = 56609280
QEMU_IMAGE_URL = "https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/frr-8.2.2.qcow2"
QEMU_IMAGE_PINS = ((QEMU_IMAGE, QEMU_IMAGE_MD5, QEMU_IMAGE_BYTES),)
# A trickling SourceForge mirror must abort, not hang (see
# _download_qemu_image): 54 MB in 5 s needs ~110 KB/s — anything slower is
# a mirror to walk away from.
QEMU_DOWNLOAD_TIME_CAP = 300


def source_images_dir():
    """The directory Cisco-licensed images are looked up in on a cache miss
    (GNS3_E2E_IMAGES, default ``~/GNS3/images``) — read-only to the e2e."""
    return os.environ.get("GNS3_E2E_IMAGES", os.path.expanduser("~/GNS3/images"))


def _md5sum(path):
    md5 = hashlib.md5(usedforsecurity=False)  # integrity matching against the appliances' checksums
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
    return md5.hexdigest()


def _source_files(subfolder):
    """``{filename: path}`` across the source images dir's root and
    *subfolder* (Cisco layouts keep emulator images in per-type subfolders,
    but a file in the root is equally visible to the server's recursive
    listing)."""

    files = {}
    source = source_images_dir()
    for folder in (source, os.path.join(source, subfolder)):
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                path = os.path.join(folder, name)
                if os.path.isfile(path) and not name.startswith("."):
                    files.setdefault(name, path)
    return files


def _find_pinned_source(pins, subfolder):
    """The first registry-pinned build present in the source images dir, as
    ``(canonical filename, source path)`` — matched by filename first, then
    by checksum under any name (see the pins tables' note); None when no
    pin matches. The size prefilter keeps the checksum pass from hashing
    the whole directory."""

    files = _source_files(subfolder)
    for name, md5sum, _size in pins:
        path = files.get(name)
        if path and _md5sum(path) == md5sum:
            return name, path
    for name, md5sum, size in pins:
        for path in files.values():
            if os.path.getsize(path) == size and _md5sum(path) == md5sum:
                return name, path
    return None


def _download_qemu_image(directory):
    """Fetch the pinned FRR qcow2 into the cache's *directory*; the canonical
    filename on success. Being offline is a skip (like an unpullable Docker
    image); a size or checksum mismatch is a hard failure — the pinned URL
    itself went bad, which no silent fallback should paper over.

    A total-time cap aborts a trickling mirror: the socket timeout is
    measured between bytes, so a mirror dripping 50 KB/s never trips it and
    would otherwise hang the scenario for the better part of an hour."""

    os.makedirs(directory, exist_ok=True)
    partial = os.path.join(directory, QEMU_IMAGE + ".part")
    print(f".. downloading {QEMU_IMAGE} ({QEMU_IMAGE_BYTES >> 20} MB, one-time — the appliance's public build)")
    md5 = hashlib.md5(usedforsecurity=False)  # integrity pin, matching the appliance's checksum
    done = 0
    deadline = time.monotonic() + QEMU_DOWNLOAD_TIME_CAP
    try:
        # S310: the pinned appliance URL, not untrusted input
        with urllib.request.urlopen(QEMU_IMAGE_URL, timeout=60) as resp, open(partial, "wb") as f:  # noqa: S310
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                if time.monotonic() > deadline:
                    raise OSError(
                        f"the mirror is too slow — {done} of {QEMU_IMAGE_BYTES} bytes in {QEMU_DOWNLOAD_TIME_CAP}s; "
                        f"retry (SourceForge picks a mirror per connection), or drop the file into {directory}"
                    )
                f.write(chunk)
                md5.update(chunk)
                done += len(chunk)
    except OSError as e:
        with contextlib.suppress(OSError):
            os.remove(partial)
        pytest.skip(f"downloading {QEMU_IMAGE} failed: {e}")
    if done != QEMU_IMAGE_BYTES or md5.hexdigest() != QEMU_IMAGE_MD5:
        with contextlib.suppress(OSError):
            os.remove(partial)
        raise AssertionError(
            f"downloaded {QEMU_IMAGE} is {done} bytes md5 {md5.hexdigest()} — "
            f"expected {QEMU_IMAGE_BYTES} bytes md5 {QEMU_IMAGE_MD5}: the pinned URL went bad"
        )
    os.replace(partial, os.path.join(directory, QEMU_IMAGE))
    print(f".. downloaded {QEMU_IMAGE} (size and md5 verified)")
    return QEMU_IMAGE


def _ensure_image(server, what, pins, subfolder, list_images, fuzzy=None, fetch=None):
    """The image the *what* scenarios run, as the filename the server lists.

    An isolated instance serves from the e2e cache (``CACHE_IMAGES``, the
    per-type subfolder the server's default layout expects): a hit costs
    nothing; a miss is filled by stealing the first registry-pinned build
    found in the source images dir (copied under its canonical pin name),
    or by ``fetch`` when one is given (the FRR qcow2's downloader); as a
    last resort a fuzzy-matching unpinned build is copied with a warning —
    an unverified combination. Against an external server
    (``GNS3_E2E_URL``) nothing is copied anywhere: pins match by filename
    against that server's own listing (the API does not expose checksums),
    then fuzzy, else the scenario skips."""

    if server.isolated:
        directory = os.path.join(CACHE_IMAGES, subfolder)
        for name, _md5sum, _size in pins:
            if os.path.isfile(os.path.join(directory, name)):
                print(f".. {what} image {name} is already in the e2e cache")
                return name
        os.makedirs(directory, exist_ok=True)
        found = _find_pinned_source(pins, subfolder)
        if found:
            name, path = found
            # copy-then-rename: a parallel test must never list (or boot) a
            # half-written image — the cache is the one shared mutable thing
            # in an otherwise per-test world
            partial = os.path.join(directory, name + ".part")
            shutil.copyfile(path, partial)
            os.replace(partial, os.path.join(directory, name))
            print(f".. copied {name} (a registry-pinned build) from {path} into the e2e cache")
        elif fetch:
            name = fetch(directory)
        elif fuzzy:
            hit = next((path for fname, path in _source_files(subfolder).items() if fuzzy(fname)), None)
            if not hit:
                pytest.skip(f"no {what} image in {source_images_dir()} (set GNS3_E2E_IMAGES)")
            name = os.path.basename(hit)
            shutil.copyfile(hit, os.path.join(directory, name))
            print(
                f".. WARNING: no registry-pinned {what} image found — using unpinned {name}, an unverified combination"
            )
        else:
            pytest.skip(f"no registry-pinned {what} image in {source_images_dir()} (set GNS3_E2E_IMAGES)")
        assert name in list_images(), f"the running server does not list the just-cached {name}"
        return name

    listing = list_images()
    for name, _md5sum, _size in pins:
        if name in listing:
            print(f".. using {name} from the external server's images")
            return name
    if fuzzy:
        hit = next((name for name in listing if fuzzy(name)), None)
        if hit:
            print(f".. WARNING: no registry-pinned {what} image on the external server — using unpinned {hit}")
            return hit
    pytest.skip(f"no registry-pinned {what} image on the external server (looked for {[p[0] for p in pins]})")


def ensure_dynamips_image(server):
    """The c7200 IOS image the dynamips-family scenarios run (dynamips,
    ethernet switch, cascade) — the registry's Cisco 7200 appliance
    builds."""
    return _ensure_image(
        server,
        "c7200",
        DYNAMIPS_IMAGE_PINS,
        "IOS",
        server.compute.dynamips_images,
        fuzzy=lambda name: name.startswith("c7200"),
    )


def ensure_iou_image(server):
    """The L3 IOU image the IOU scenario runs — the registry's Cisco IOU L3
    appliance builds. L3 only: the ``l2`` exclusion is deliberate (L2 IOU
    images have their own issues; see the scenario)."""
    return _ensure_image(
        server,
        "IOU L3",
        IOU_IMAGE_PINS,
        "IOU",
        server.compute.iou_images,
        fuzzy=lambda name: "adventerprisek9" in name and "l2" not in name.lower(),
    )


def ensure_qemu_image(server):
    """The qcow2 the QEMU scenarios run — the registry's FRR appliance
    image: public, versioned and pinned, so the scenarios bootstrap
    themselves on any host. ``GNS3_E2E_QEMU_IMAGE`` overrides the reference
    entirely (must already be listed; the operator then owns its
    content)."""

    override = os.environ.get("GNS3_E2E_QEMU_IMAGE")
    if override:
        if override not in server.compute.qemu_images():
            pytest.skip(f"GNS3_E2E_QEMU_IMAGE={override} is not in the server's QEMU images")
        print(f".. using GNS3_E2E_QEMU_IMAGE={override}")
        return override
    return _ensure_image(
        server, "QEMU", QEMU_IMAGE_PINS, "QEMU", server.compute.qemu_images, fetch=_download_qemu_image
    )


def configure_docker_interfaces(node, address, netmask="255.255.255.0", adapter=0):
    """Give the container's eth{adapter} a static address the way a GNS3
    user does: write the persistent ``/etc/network/interfaces`` the server
    bind-mounts into the container and init.sh applies with ifup at boot
    (separate address/netmask lines — the portable stanza every ifup
    flavor understands). Call before starting the node.

    IPv4 only: an inet6 stanza would never apply — see
    ``docker_bring_up_ipv6``."""
    directory = node.get("node_directory")
    if not directory or not os.path.isdir(directory):
        pytest.skip(f"cannot reach the node directory {directory!r} — this scenario needs the compute on this host")
    path = os.path.join(directory, "etc", "network", "interfaces")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"auto eth{adapter}\niface eth{adapter} inet static\n\taddress {address}\n\tnetmask {netmask}\n")


def docker_bring_up_ipv6(daemon, container_id, address6, adapter=0):
    """Give the container's eth{adapter} its global IPv6 address. Call
    after every container start (the address does not survive a stop: the
    netns is rebuilt).

    IPv6 cannot ride the interfaces file here: on bridge networks without
    IPv6 the Docker daemon leaves the container interface with
    ``disable_ipv6=1``, which makes ifup's ``ip -6 addr add`` fail
    with EPERM before init.sh's ``ifup -a`` ever finishes the stanza — the
    interface must be switched on by hand first. DAD transmissions are
    silenced before the address is added: the kernel still holds the
    address tentative for ~1 s (measured; ~2 s with the default one DAD
    solicitation), but nothing here tests DAD and the solicitations are one
    less source of boot-time chatter on the wire."""
    code, output = daemon.exec(
        container_id,
        [
            "sh",
            "-c",
            f"echo 0 > /proc/sys/net/ipv6/conf/eth{adapter}/dad_transmits"
            f" && echo 0 > /proc/sys/net/ipv6/conf/eth{adapter}/disable_ipv6"
            f" && ip -6 addr add {address6}/64 dev eth{adapter}",
        ],
    )
    assert code == 0, output


def docker_wait_address(daemon, container_id, address, timeout=30, adapter=0):
    """Wait until the container's eth{adapter} carries *address* (either
    family) — init.sh applies the interfaces file (ifup) a moment
    after container start. A v6 address also has to leave the tentative
    state (a tentative address answers no neighbour solicitation, so pings
    to it cannot resolve)."""
    family = "-6" if ":" in address else "-4"

    def present():
        _code, output = daemon.exec(container_id, ["ip", family, "-o", "addr", "show", "dev", f"eth{adapter}"])
        if family == "-6":
            return address.lower() in output.lower() and "tentative" not in output.lower()
        return address in output

    if not wait_until(present, timeout=timeout, interval=0.5):
        raise AssertionError(f"container {container_id[:12]} did not configure {address} within {timeout}s")


def docker_ping(daemon, container_id, target, count=3, timeout=1, interval=0.2, size=None):
    """Run a real iputils ping inside a container; returns
    ``{loss, avg, raw, exit}`` (loss in percent, avg in ms). The default
    0.2 s interval packs more samples into loss measurements; loss-based
    checks pass a higher count.

    The ping is wrapped in `timeout` with a generous cap so a
    misbehaving guest can never hold the exec stream open past it — the
    harness then reports a normal failed ping instead of a socket timeout.
    """
    cap = int(count * interval + timeout + 15)
    cmd = ["timeout", str(cap), "ping", "-c", str(count), "-W", str(timeout)]
    if interval is not None:
        cmd += ["-i", str(interval)]
    if size is not None:
        cmd += ["-s", str(size)]
    cmd.append(target)
    code, output = daemon.exec(container_id, cmd, timeout=cap + 10)
    loss_pct, avg_rtt = _ping_parse(output, count)
    return {
        "loss": loss_pct,
        "avg": avg_rtt,
        "raw": output,
        "exit": code,
    }


def docker_wait_ping(daemon, container_id, target, attempts=4, **kwargs):
    """ping until it fully succeeds (a fresh veth/bridge needs a beat for
    carrier and ARP); returns the last result either way."""
    result = None
    for _ in range(attempts):
        result = docker_ping(daemon, container_id, target, **kwargs)
        if result["loss"] == 0:
            return result
        time.sleep(1.5)
    return result


# ---------------------------------------------------------------------------
# Host-side inspection (same machine as the compute)
# ---------------------------------------------------------------------------


def sysfs(path):
    with open(path) as f:
        return f.read().strip()


def tap_exists(name):
    return os.path.exists(f"/sys/class/net/{name}")


def tap_up(name):
    """The tap's administrative state (IFF_UP): what the kernel datapath
    drives for carrier on attach/detach/suspend."""
    return bool(int(sysfs(f"/sys/class/net/{name}/flags"), 16) & 1)


def bridge_members(bridge):
    """Interfaces enslaved to a kernel bridge, or None when the bridge does
    not exist."""
    if not os.path.exists(f"/sys/class/net/{bridge}/brif"):
        return None
    return sorted(os.listdir(f"/sys/class/net/{bridge}/brif"))


def unmanage_from_networkmanager(*names):
    """Best-effort ``nmcli device set <name> managed no`` for the given
    interfaces.

    NetworkManager (desktop hosts) manages the TAP devices uBridge creates.
    While a tap is in NM's not-yet-assumed state, NM's netdev-event state
    machine can *release* it from its bridge some 60-70 ms after
    enslavement (measured: ~50% of re-enslavements on an NM host): the port
    is left administratively up, out of the bridge, with no server-side log
    or error — a silent blackhole. Scenarios that detach and re-enslave an
    anchor (link delete + recreate, node restart) must call this once their
    nodes have booted, or they are nondeterministically flaky on such
    hosts. Silently a no-op where nmcli is unavailable.
    """
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return
    for name in names:
        # S603: resolved binary, fixed argv, no shell
        subprocess.run(  # noqa: S603
            [nmcli, "device", "set", name, "managed", "no"],
            capture_output=True,
            check=False,
        )


# ---------------------------------------------------------------------------
# L2-anchor spec assertions (docs/design/ubridge-l2-anchor-spec.md §E)
# ---------------------------------------------------------------------------

# uBridge's creators harden every host-side datapath device with
# ``link l2only``; these assertions verify the result from the server side.
# They need the probe below to confirm the command exists — the spec's
# degradation contract is a skip on old builds, where anchors keep the
# kernel-default L3 behaviour (measured: 6 frames of MLD/DAD noise per 2 s).


def l2only_supported():
    """Whether this host's uBridge knows ``link l2only`` (probed once).

    Sends the command for a nonexistent device to a throwaway uBridge: a
    208 reply means the command exists, ``202-Unknown command`` an old
    build. Anything unreadable also degrades to False — the L2 assertions
    skip rather than fail, mirroring the tc-capability degradation."""
    global _l2only_support
    if _l2only_support is None:
        _l2only_support = _probe_l2only()
    return _l2only_support


_l2only_support = None


def _probe_l2only():
    ubridge = shutil.which("ubridge")
    if not ubridge:
        return False
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="gns3-e2e-l2probe-") as workdir:
        # S603: resolved binary, fixed argv, no shell
        proc = subprocess.Popen(  # noqa: S603
            [ubridge, "-H", f"127.0.0.1:{port}"],
            cwd=workdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            sock = None
            deadline = time.time() + 10
            while time.time() < deadline and sock is None:
                if proc.poll() is not None:
                    return False
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                except OSError:
                    time.sleep(0.1)
            if sock is None:
                return False
            with sock:
                sock.settimeout(3)
                sock.sendall(b"link l2only e2el2probe0\n")
                buf = b""
                deadline = time.time() + 5
                while time.time() < deadline:
                    try:
                        chunk = sock.recv(4096)
                    except TimeoutError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    if re.match(rb"\d{3}-", buf.split(b"\n")[0]):
                        break
            reply = buf.decode(errors="replace").splitlines()[0] if buf else ""
            # 208 = the command ran and refused the nonexistent device
            return reply.startswith("208-")
        finally:
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)


def assert_pure_l2(name):
    """§E.1: a host-side datapath device (anchor or bridge) carries no L3
    identity — no IPv4/IPv6 address, and addrgenmode none so none can
    self-provision (no DAD, MLD or RS is ever generated from it)."""
    mode_path = f"/sys/class/net/{name}/addr_gen_mode"
    mode = sysfs(mode_path) if os.path.exists(mode_path) else None
    assert mode in (None, "1"), f"{name}: addr_gen_mode is {mode!r}, expected none ('1')"
    if os.path.exists("/proc/net/if_inet6"):
        with open("/proc/net/if_inet6") as f:
            assigned = [line.strip() for line in f if line.split()[-1] == name]
        assert not assigned, f"{name}: unexpected IPv6 address: {assigned}"
    if not IP:
        raise AssertionError("ip binary not found — cannot verify the anchor has no IPv4 address")
    # S603: resolved binary, fixed argv, no shell
    v4 = subprocess.run(  # noqa: S603
        [IP, "-o", "-4", "addr", "show", "dev", name], capture_output=True, text=True, check=False
    ).stdout.strip()
    assert not v4, f"{name}: unexpected IPv4 address: {v4}"


def brport_state(name):
    """The interface's bridge-port STP state (None when not enslaved); the
    kernel reports 3 for forwarding."""
    path = f"/sys/class/net/{name}/brport/state"
    return sysfs(path) if os.path.exists(path) else None


def assert_forwarding(name):
    """Silent-failure guard found while validating the L2 spec: an attached
    bridge port must be FORWARDING. A bridge device left DOWN keeps its
    ports disabled and forwards nothing — with no error anywhere, this
    assertion is the only signal."""
    state = brport_state(name)
    assert state == "3", f"{name}: bridge port state {state!r}, expected forwarding (3)"


def packet_counters(name):
    """(rx, tx) packet counters of a host interface."""
    return (
        int(sysfs(f"/sys/class/net/{name}/statistics/rx_packets")),
        int(sysfs(f"/sys/class/net/{name}/statistics/tx_packets")),
    )


def assert_idle_silence(*names, settle=2.5, window=5.0):
    """§E.2: after the one-shot enslavement burst settles (the IGMP/MLD
    membership reports of the bridge are accepted residual, see §0), an
    idle device in its normal role shows no traffic for *window* seconds.
    The baseline without the hardening: 6 frames / 2 s, continuous."""
    time.sleep(settle)
    before = {name: packet_counters(name) for name in names}
    time.sleep(window)
    noisy = {name: (before[name], packet_counters(name)) for name in names if packet_counters(name) != before[name]}
    assert not noisy, f"idle devices saw traffic (before -> after): {noisy}"


def link_bridge_name(link_id):
    """The per-link kernel bridge name the controller derives from a link
    id (see UDPLink._prepare)."""
    return "gns3" + link_id.replace("-", "")[:11]


def cascade_end_names(link_id):
    """The two veth ends of a switch-to-switch cascade link, as
    ``(end0, end1)`` — a pure function of the link id, like the per-link
    bridge name (see utils.kernel_cascade_names)."""
    stem = link_id.replace("-", "")[:10]
    return f"gs{stem}0", f"gs{stem}1"


def anchor_name(node_id, adapter, port):
    """The dynamips anchor TAP name for a slot/port (see Router._tap_name)."""
    return "gd" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def docker_anchor_name(node_id, adapter, port=0):
    """The standard Docker node's anchor: the veth host end the server keeps
    in the root namespace (see DockerKernelDatapathMixin._veth_names and
    utils.kernel_anchor)."""
    return "gv" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def iol_anchor_name(node_id, adapter, port):
    """The IOL runner container's anchor TAP name (see IOLDockerVM._tap_name)."""
    return "gx" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def iou_anchor_name(node_id, adapter, port=0):
    """The IOU node's anchor TAP name: one persistent TAP per Ethernet
    bay/unit (see IOUVM._tap_name and utils.kernel_anchor)."""
    return "gi" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def qemu_anchor_name(node_id, adapter, port=0):
    """The QEMU node's anchor TAP name: one persistent TAP per adapter —
    the netdev QEMU itself opens by ifname (see QemuVM._tap_name and
    utils.kernel_anchor)."""
    return "gq" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def vpcs_anchor_name(node_id, adapter=0, port=0):
    """The VPCS node's anchor TAP name: one persistent TAP for the single
    adapter, attached to by name through -e -d (see VPCSVM._tap_name and
    utils.kernel_anchor)."""
    return "gp" + node_id.replace("-", "")[:8] + f"e{adapter}p{port}"


def stage_iol_base_config(server):
    """
    Copy the shipped iol-xe base config into an isolated instance's configs
    directory (its GNS3_IOL_STARTUP_CONFIG lookup path) so nodes boot past
    the setup dialog. A no-op for an external server — there the operator's
    install provides it.
    """

    if not server.isolated:
        return
    src = os.path.join(REPO_ROOT, "gns3server", "configs", "iol-xe-base.txt")
    configs_dir = os.path.join(server.tmpdir, "configs")
    os.makedirs(configs_dir, exist_ok=True)
    shutil.copy(src, os.path.join(configs_dir, "iol-xe-base.txt"))


def qdiscs(dev):
    """The tc qdisc listing of a host interface ('' when tc is missing)."""
    if not TC:
        return ""
    # S603: resolved binary, fixed argv, no shell
    result = subprocess.run(  # noqa: S603
        [TC, "qdisc", "show", "dev", dev], capture_output=True, text=True, check=False
    )
    return result.stdout


def wait_until(predicate, timeout=10, interval=0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def pcap_records(path):
    """Count the records of a pcap file and collect the distinct ethertypes
    across all of them (hex, e.g. '0800') — enough to prove a capture is
    real. Scans every record, not a leading sample: a dual-stack host's
    own IPv6 control frames (DAD/MLD) can precede the traffic under test,
    and a truncated sample would let them mask it."""
    import struct

    ethertypes = set()
    with open(path, "rb") as f:
        header = f.read(24)
        if len(header) < 24:
            return 0, ethertypes
        endian = "<" if header[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
        count = 0
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            _ts, _tus, caplen, _orig = struct.unpack(endian + "IIII", rec)
            data = f.read(caplen)
            if len(data) < caplen:
                break
            count += 1
            if caplen >= 14:
                ethertypes.add(data[12:14].hex())
    return count, ethertypes


def pcap_icmp_rtt(path, ethertype):
    """The mean echo request->reply RTT (ms) in a capture, from the
    capture's own timestamps — the wire truth, independent of whatever a
    guest's ping reports (the dynamips-emulated classic IOS under-reports
    its ``ping ipv6`` RTT by roughly 40 % of a delayed round trip; this
    primitive is what the dynamips-family scenarios assert instead).

    Pairs each echo request with the next echo reply (``ethertype`` is
    '0800' or '86dd'; ICMP echo type 8/0 for v4, 128/129 for v6 with the
    fixed 40-byte IPv6 header — no extension headers in these pings).
    Returns None when the capture holds no complete exchange."""
    import struct

    rows = []
    with open(path, "rb") as f:
        header = f.read(24)
        if len(header) < 24:
            return None
        endian = "<" if header[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            ts_s, ts_us, caplen, _orig = struct.unpack(endian + "IIII", rec)
            data = f.read(caplen)
            if len(data) < caplen:
                break
            if caplen < 14 or data[12:14].hex() != ethertype:
                continue
            icmp_off = 14 + ((data[14] & 0xF) * 4 if ethertype == "0800" else 40)
            if caplen >= icmp_off + 1:
                rows.append((ts_s + ts_us / 1e6, data[icmp_off]))
    request_type = 8 if ethertype == "0800" else 128
    deltas, pending = [], None
    for ts, icmp_type in rows:
        if icmp_type == request_type:
            pending = ts
        elif icmp_type == request_type + 1 and pending is not None:
            deltas.append((ts - pending) * 1000)
            pending = None
    return sum(deltas) / len(deltas) if deltas else None
