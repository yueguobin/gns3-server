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
Tests for the SOCKS5 proxy authentication routing: the reserved ``totp:``
prefix must dispatch to ``authenticate_user_totp`` while any other value uses
the regular password path.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gns3server.controller import proxy

pytestmark = pytest.mark.asyncio


def _async_session_mock():
    """
    Build an AsyncSession stand-in that can be used as
    ``async with AsyncSession(...) as session``.
    """

    mock_session = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None
    return mock_session, mock_cm


async def test_totp_prefix_routes_to_totp_auth():
    app = MagicMock()
    user = MagicMock(username="alice")
    _, mock_cm = _async_session_mock()
    with patch.object(proxy, "AsyncSession", return_value=mock_cm), \
            patch.object(proxy, "UsersRepository") as MockRepo:
        repo = MockRepo.return_value
        repo.authenticate_user_totp = AsyncMock(return_value=user)
        repo.authenticate_user = AsyncMock(return_value=user)

        result_user, method = await proxy._authenticate(app, "alice", "totp:123456")

        repo.authenticate_user_totp.assert_awaited_once_with("alice", "123456")
        repo.authenticate_user.assert_not_awaited()
        assert method == "totp"
        assert result_user is user


async def test_plain_password_routes_to_password_auth():
    app = MagicMock()
    user = MagicMock(username="alice")
    _, mock_cm = _async_session_mock()
    with patch.object(proxy, "AsyncSession", return_value=mock_cm), \
            patch.object(proxy, "UsersRepository") as MockRepo:
        repo = MockRepo.return_value
        repo.authenticate_user_totp = AsyncMock(return_value=None)
        repo.authenticate_user = AsyncMock(return_value=user)

        result_user, method = await proxy._authenticate(app, "alice", "a_plain_password")

        repo.authenticate_user.assert_awaited_once_with("alice", "a_plain_password")
        repo.authenticate_user_totp.assert_not_awaited()
        assert method == "password"
        assert result_user is user


async def test_failed_totp_returns_none_method():
    app = MagicMock()
    _, mock_cm = _async_session_mock()
    with patch.object(proxy, "AsyncSession", return_value=mock_cm), \
            patch.object(proxy, "UsersRepository") as MockRepo:
        repo = MockRepo.return_value
        repo.authenticate_user_totp = AsyncMock(return_value=None)

        result_user, method = await proxy._authenticate(app, "alice", "totp:badcode")

        repo.authenticate_user_totp.assert_awaited_once_with("alice", "badcode")
        assert result_user is None
        assert method is None
