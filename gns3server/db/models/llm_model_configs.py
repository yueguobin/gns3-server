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

from sqlalchemy import Column, Boolean, ForeignKey, CheckConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import BaseTable, generate_uuid, GUID

import logging

log = logging.getLogger(__name__)


class LLMModelConfig(BaseTable):
    """
    LLM model configuration for users and user groups.
    Supports inheritance: users can inherit configs from their groups.
    """

    __tablename__ = "llm_model_configs"

    config_id = Column(GUID, primary_key=True, default=generate_uuid)
    config = Column(JSONB, nullable=False)  # All config fields including name, provider, etc.
    user_id = Column(GUID, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True)
    group_id = Column(GUID, ForeignKey("user_groups.user_group_id", ondelete="CASCADE"), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User", backref="llm_model_configs")
    group = relationship("UserGroup", backref="llm_model_configs")

    # Constraints
    __table_args__ = (
        # Ensure a config belongs to either a user or a group, not both
        CheckConstraint(
            "(user_id IS NOT NULL AND group_id IS NULL) OR "
            "(user_id IS NULL AND group_id IS NOT NULL)",
            name="single_owner_check"
        ),
        # Each user can have at most one default config
        UniqueConstraint("user_id", "is_default", name="unique_user_default",
                         deferrable=True, initially="deferred",
                         postgresql_where="is_default = TRUE AND user_id IS NOT NULL"),
        # Each group can have at most one default config
        UniqueConstraint("group_id", "is_default", name="unique_group_default",
                         deferrable=True, initially="deferred",
                         postgresql_where="is_default = TRUE AND group_id IS NOT NULL"),
        # Indexes for efficient queries
        Index("idx_llm_model_configs_user_id", "user_id"),
        Index("idx_llm_model_configs_group_id", "group_id"),
        Index("idx_llm_model_configs_config", "config", postgresql_using="gin"),
    )

    def __repr__(self):
        config_name = self.config.get("name", "unnamed") if self.config else "unnamed"
        owner = f"user_{self.user_id}" if self.user_id else f"group_{self.group_id}"
        return f"<LLMModelConfig {config_name} for {owner} (default={self.is_default})>"
