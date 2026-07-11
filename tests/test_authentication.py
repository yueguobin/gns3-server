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

"""
Unit tests for the TOTP helpers on AuthService and the SOCKS5 ``totp:`` prefix
handling exposed by schemas.controller.users.
"""

from datetime import datetime, timedelta, timezone

import pyotp

from gns3server.services.authentication import AuthService
from gns3server.schemas.controller.users import extract_totp_code


def test_generate_totp_secret_is_base32():
    secret = AuthService().generate_totp_secret()
    # pyotp.random_base32() yields 32 base32 characters by default
    assert len(secret) == 32
    # the secret must produce a valid 6-digit code
    assert pyotp.TOTP(secret).now().isdigit()


def test_verify_totp_accepts_current_code():
    auth = AuthService()
    secret = auth.generate_totp_secret()
    assert auth.verify_totp(secret, pyotp.TOTP(secret).now()) is True


def test_verify_totp_rejects_code_outside_window():
    auth = AuthService()
    secret = auth.generate_totp_secret()
    # ~3 windows (95s) ago is well outside the +/-30s valid_window
    old_time = datetime.now(timezone.utc) - timedelta(seconds=95)
    expired_code = pyotp.TOTP(secret).at(old_time)
    assert auth.verify_totp(secret, expired_code) is False


def test_verify_totp_tolerates_small_skew():
    auth = AuthService()
    secret = auth.generate_totp_secret()
    # 20s ago is within the +/-30s window
    recent_time = datetime.now(timezone.utc) - timedelta(seconds=20)
    recent_code = pyotp.TOTP(secret).at(recent_time)
    assert auth.verify_totp(secret, recent_code) is True


def test_totp_provisioning_uri():
    auth = AuthService()
    secret = auth.generate_totp_secret()
    uri = auth.totp_provisioning_uri(secret, "alice")
    assert uri.startswith("otpauth://totp/")
    assert "GNS3" in uri
    assert "alice" in uri
    assert secret in uri


def test_extract_totp_code_with_prefix():
    assert extract_totp_code("totp:123456") == "123456"


def test_extract_totp_code_without_prefix_returns_none():
    assert extract_totp_code("a_normal_password") is None


def test_extract_totp_code_empty_code_after_prefix():
    assert extract_totp_code("totp:") == ""
