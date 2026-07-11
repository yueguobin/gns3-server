#
# Copyright (C) 2020 GNS3 Technologies Inc.
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

from datetime import datetime
from typing import Optional
from pydantic import ConfigDict, EmailStr, BaseModel, Field, SecretStr, field_validator
from uuid import UUID

from .base import DateTimeModelMixin


# Reserved prefix used by the SOCKS5 proxy (RFC 1929 password field) to signal
# that the supplied value is a TOTP code rather than a static password. Static
# passwords must never start with this prefix (enforced below) so the proxy can
# branch unambiguously on startswith(TOTP_PASSWORD_PREFIX).
TOTP_PASSWORD_PREFIX = "totp:"


def extract_totp_code(password: str) -> Optional[str]:
    """
    If *password* carries the reserved TOTP prefix, return the code that
    follows it; otherwise return None (the value is treated as a static
    password).
    """

    if password.startswith(TOTP_PASSWORD_PREFIX):
        return password[len(TOTP_PASSWORD_PREFIX):]
    return None


def _reject_totp_prefixed(value: Optional[SecretStr]) -> Optional[SecretStr]:
    """
    Reject static passwords that start with the reserved TOTP prefix.
    Applied to every password-setting schema so the value can never be
    confused with a TOTP code at the SOCKS5 proxy.
    """

    if value is not None and value.get_secret_value().startswith(TOTP_PASSWORD_PREFIX):
        raise ValueError(
            f"Passwords must not start with the reserved prefix '{TOTP_PASSWORD_PREFIX}'"
        )
    return value


class UserBase(BaseModel):
    """
    Common user properties.
    """

    username: Optional[str] = Field(None, min_length=3, pattern="[a-zA-Z0-9_-]+$")
    is_active: bool = True
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """
    Properties to create a user.
    """

    username: str = Field(..., min_length=3, pattern="[a-zA-Z0-9_-]+$")
    password: SecretStr = Field(..., min_length=8, max_length=100)

    @field_validator("password")
    @classmethod
    def _ban_totp_prefix(cls, value: SecretStr) -> SecretStr:
        return _reject_totp_prefixed(value)  # type: ignore[return-value]


class UserUpdate(UserBase):
    """
    Properties to update a user.
    """

    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)

    @field_validator("password")
    @classmethod
    def _ban_totp_prefix(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        return _reject_totp_prefixed(value)


class LoggedInUserUpdate(BaseModel):
    """
    Properties to update a logged-in user.
    """

    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _ban_totp_prefix(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        return _reject_totp_prefixed(value)


class User(DateTimeModelMixin, UserBase):

    user_id: UUID
    last_login: Optional[datetime] = None
    is_superadmin: bool = False
    model_config = ConfigDict(from_attributes=True)


class UserGroupBase(BaseModel):
    """
    Common user group properties.
    """

    name: Optional[str] = Field(None, min_length=3, pattern="[a-zA-Z0-9_-]+$")


class UserGroupCreate(UserGroupBase):
    """
    Properties to create a user group.
    """

    name: Optional[str] = Field(..., min_length=3, pattern="[a-zA-Z0-9_-]+$")


class UserGroupUpdate(UserGroupBase):
    """
    Properties to update a user group.
    """

    pass


class UserGroup(DateTimeModelMixin, UserGroupBase):

    user_group_id: UUID
    is_builtin: bool
    model_config = ConfigDict(from_attributes=True)


class Credentials(BaseModel):

    username: str
    password: str


# ---------------------------------------------------------------------------
# TOTP (SOCKS5 proxy) management schemas
# ---------------------------------------------------------------------------

class TotpPasswordRequest(BaseModel):
    """
    Confirms the current static password when enabling or disabling TOTP,
    preventing a stolen bearer token from silently toggling 2FA. The same
    totp: prefix ban applies so the confirmation password stays unambiguous.
    """

    password: SecretStr

    @field_validator("password")
    @classmethod
    def _ban_totp_prefix(cls, value: SecretStr) -> SecretStr:
        return _reject_totp_prefixed(value)  # type: ignore[return-value]


class TotpStatus(BaseModel):

    totp_enabled: bool


class TotpSetupResponse(BaseModel):

    secret: str
    provisioning_uri: str
