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
The overlay disks of a distributed copy: every QEMU disk image of the
template becomes a thin qcow2 overlay, every other file of the QEMU node
directories is copied verbatim.
"""

import os
import shutil

import pytest

from gns3server.controller import qemu_overlay
from gns3server.controller.controller_error import ControllerError


@pytest.fixture
def source_project(tmp_path):
    """
    A template project directory with one QEMU node: a disk image, a plain
    config file, and a nested flash directory.
    """

    node_id = "4b2b1e5a-0000-0000-0000-000000000001"
    qemu_dir = tmp_path / "source" / "project-files" / "qemu" / node_id
    qemu_dir.mkdir(parents=True)
    (qemu_dir / "hda_disk.qcow2").write_bytes(b"not really a disk, probed as an image")
    (qemu_dir / "config.txt").write_text("hostname r1")
    flash_dir = qemu_dir / "flash"
    flash_dir.mkdir()
    (flash_dir / "startup.cfg").write_text("boot")
    # files outside the QEMU directories are not touched by the overlay pass
    (tmp_path / "source" / "test.gns3").write_text("{}")
    return tmp_path / "source"


def test_disk_images_become_overlays_and_other_files_are_copied(source_project, tmp_path, monkeypatch):
    """
    Disk images are replaced by overlays pointing at the template (absolute
    path, original virtual size); config files are copied verbatim.
    """

    destination = tmp_path / "copy"
    destination.mkdir()

    created = []

    def fake_image_info(qemu_img, path):
        if path.endswith(".qcow2"):
            return {"format": "qcow2", "virtual-size": 42949632}
        return None

    def fake_create_overlay(qemu_img, backing_file, overlay_file, info):
        created.append((backing_file, overlay_file, info))
        with open(overlay_file, "w") as f:
            f.write("overlay")

    monkeypatch.setattr(qemu_overlay, "find_qemu_img", lambda: "/fake/qemu-img")
    monkeypatch.setattr(qemu_overlay, "_image_info", fake_image_info)
    monkeypatch.setattr(qemu_overlay, "_create_overlay", fake_create_overlay)

    overlays = qemu_overlay.create_overlay_disks(str(source_project), str(destination))
    assert overlays == 1

    # exactly one overlay, pointing at the template's disk by absolute path
    (backing_file, overlay_file, info) = created[0]
    assert backing_file == str(
        source_project / "project-files" / "qemu" / "4b2b1e5a-0000-0000-0000-000000000001" / "hda_disk.qcow2"
    )
    assert os.path.isabs(backing_file)
    assert info["virtual-size"] == 42949632
    assert overlay_file.endswith("hda_disk.qcow2")

    # the non-image files ride along verbatim, nested directories included
    assert (
        destination / "project-files" / "qemu" / "4b2b1e5a-0000-0000-0000-000000000001" / "config.txt"
    ).read_text() == "hostname r1"
    assert (
        destination / "project-files" / "qemu" / "4b2b1e5a-0000-0000-0000-000000000001" / "flash" / "startup.cfg"
    ).read_text() == "boot"


def test_project_without_qemu_files_is_a_no_op(source_project, tmp_path, monkeypatch):
    """
    A project without a project-files/qemu directory (no QEMU nodes) creates
    no overlay and does not even need qemu-img.
    """

    destination = tmp_path / "copy"
    destination.mkdir()

    def fail_find():
        raise AssertionError("qemu-img must not be needed without QEMU disks")

    monkeypatch.setattr(qemu_overlay, "find_qemu_img", fail_find)
    shutil.rmtree(source_project / "project-files" / "qemu")
    assert qemu_overlay.create_overlay_disks(str(source_project), str(destination)) == 0


def test_overlay_creation_failure_is_reported(source_project, tmp_path, monkeypatch):
    """
    A failing qemu-img create surfaces as a ControllerError, not a silent
    broken copy.
    """

    destination = tmp_path / "copy"
    destination.mkdir()
    monkeypatch.setattr(qemu_overlay, "find_qemu_img", lambda: "/fake/qemu-img")
    monkeypatch.setattr(qemu_overlay, "_image_info", lambda qemu_img, path: {"format": "qcow2", "virtual-size": 1024})
    monkeypatch.setattr(
        qemu_overlay, "_create_overlay", lambda *args: (_ for _ in ()).throw(ControllerError("qemu-img failed"))
    )
    with pytest.raises(ControllerError, match="qemu-img failed"):
        qemu_overlay.create_overlay_disks(str(source_project), str(destination))
