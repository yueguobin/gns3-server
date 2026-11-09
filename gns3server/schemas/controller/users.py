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
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from ..update import PartialUpdateModel
from .base import DateTimeModelMixin


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
    user_group_id: UUID = Field(..., description="The user group the new user belongs to")


class UserUpdate(PartialUpdateModel, UserBase):
    """
    Properties to update a user.
    """

    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)


class LoggedInUserUpdate(BaseModel):
    """
    Properties to update a logged-in user.
    """

    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class User(DateTimeModelMixin, UserBase):
    user_id: UUID
    last_login: Optional[datetime] = None
    is_superadmin: bool = False
    model_config = ConfigDict(from_attributes=True)


class UserPrivileges(BaseModel):
    """
    Effective privileges of the logged in user, flattened across all roles
    assigned to the user (directly or through group membership).

    This is a hint for rendering purposes only: the server remains the
    authority for permission checks and can still deny a privilege listed
    here on a specific resource path.
    """

    is_superadmin: bool
    privileges: List[str]


class UserPreferences(BaseModel):
    """
    Preferences document of a user: an arbitrary JSON object owned by the client
    (e.g. the web UI keeps its per-user settings there so they follow the user
    across machines). The server stores it as-is and does not interpret its
    contents. Clients are expected to carry their own schema version inside the
    document and must not store credentials there.
    """

    preferences: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class UserGroupBase(BaseModel):
    """
    Common user group properties.
    """

    name: Optional[str] = Field(None, min_length=3, pattern="[a-zA-Z0-9_-]+$")


class UserGroupCreate(UserGroupBase):
    """
    Properties to create a user group.
    """

    name: str = Field(..., min_length=3, pattern="[a-zA-Z0-9_-]+$")


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
