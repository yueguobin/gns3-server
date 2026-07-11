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
Tests for the reserved ``totp:`` password prefix ban across the password
schemas. Static passwords may never start with this prefix so the SOCKS5 proxy
can branch unambiguously.
"""

import pytest
from pydantic import ValidationError

from gns3server.schemas.controller.users import (
    UserCreate,
    UserUpdate,
    LoggedInUserUpdate,
    TotpPasswordRequest,
)


def test_user_create_rejects_totp_prefixed_password():
    with pytest.raises(ValidationError):
        UserCreate(username="alice", email="alice@example.com", password="totp:123456")


def test_user_update_rejects_totp_prefixed_password():
    with pytest.raises(ValidationError):
        UserUpdate(password="totp:abcdef")


def test_logged_in_user_update_rejects_totp_prefixed_password():
    with pytest.raises(ValidationError):
        LoggedInUserUpdate(password="totp:something")


def test_totp_password_request_rejects_totp_prefixed_password():
    with pytest.raises(ValidationError):
        TotpPasswordRequest(password="totp:123456")


def test_case_sensitive_prefix_is_allowed():
    # Only lowercase 'totp:' is reserved; 'Totp:' never triggers the SOCKS5
    # branch, so it is a legal static password.
    user = UserCreate(username="alice", email="alice@example.com", password="Totp:123456")
    assert user.password.get_secret_value() == "Totp:123456"


def test_normal_password_is_accepted():
    user = UserCreate(username="alice", email="alice@example.com", password="validpass")
    assert user.password.get_secret_value() == "validpass"
