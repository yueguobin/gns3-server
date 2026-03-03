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

from uuid import UUID
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import json
import logging

from .base import BaseRepository
import gns3server.db.models as models

log = logging.getLogger(__name__)


class LLMModelConfigsRepository(BaseRepository):
    """Repository for LLM model configurations with inheritance support."""

    # User configuration methods

    async def get_user_config(self, config_id: UUID) -> Optional[models.LLMModelConfig]:
        """Get a user's LLM model configuration by ID."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.user_id.isnot(None)
            )
        )
        result = await self._db_session.execute(query)
        return result.scalars().first()

    async def get_user_configs(self, user_id: UUID) -> List[models.LLMModelConfig]:
        """Get all LLM model configurations for a user."""
        query = select(models.LLMModelConfig).where(
            models.LLMModelConfig.user_id == user_id
        ).order_by(models.LLMModelConfig.created_at)
        result = await self._db_session.execute(query)
        return result.scalars().all()

    async def get_user_default_config(self, user_id: UUID) -> Optional[models.LLMModelConfig]:
        """Get a user's default LLM model configuration."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.user_id == user_id,
                models.LLMModelConfig.is_default == True
            )
        )
        result = await self._db_session.execute(query)
        return result.scalars().first()

    async def create_user_config(
        self,
        user_id: UUID,
        config_data: Dict[str, Any],
        is_default: bool = False
    ) -> models.LLMModelConfig:
        """Create a new LLM model configuration for a user."""
        # Encrypt API key if present
        from gns3server.utils.encryption import encrypt
        config_to_store = config_data.copy()
        if "api_key" in config_to_store and config_to_store["api_key"]:
            try:
                config_to_store["api_key"] = encrypt(config_to_store["api_key"])
            except Exception as e:
                log.error(f"Failed to encrypt API key: {e}")
                raise

        db_config = models.LLMModelConfig(
            config=config_to_store,
            user_id=user_id,
            is_default=is_default
        )
        self._db_session.add(db_config)
        await self._db_session.commit()
        await self._db_session.refresh(db_config)
        return db_config

    async def update_user_config(
        self,
        config_id: UUID,
        user_id: UUID,
        updates: Dict[str, Any]
    ) -> Optional[models.LLMModelConfig]:
        """Update a user's LLM model configuration."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.user_id == user_id
            )
        )
        result = await self._db_session.execute(query)
        db_config = result.scalars().first()

        if not db_config:
            return None

        # Encrypt API key if present in updates
        from gns3server.utils.encryption import encrypt
        updates_copy = updates.copy()
        if "api_key" in updates_copy and updates_copy["api_key"]:
            try:
                updates_copy["api_key"] = encrypt(updates_copy["api_key"])
            except Exception as e:
                log.error(f"Failed to encrypt API key: {e}")
                raise

        # Update config JSONB fields
        current_config = db_config.config.copy()
        for key, value in updates_copy.items():
            if key == "is_default":
                db_config.is_default = value
            elif value is not None:
                current_config[key] = value

        db_config.config = current_config
        await self._db_session.commit()
        await self._db_session.refresh(db_config)
        return db_config

    async def delete_user_config(self, config_id: UUID, user_id: UUID) -> bool:
        """Delete a user's LLM model configuration."""
        query = delete(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.user_id == user_id
            )
        )
        result = await self._db_session.execute(query)
        await self._db_session.commit()
        return result.rowcount > 0

    async def set_user_default_config(self, user_id: UUID, config_id: UUID) -> bool:
        """Set a user's default LLM model configuration."""
        # First, unset current default
        await self._db_session.execute(
            update(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.user_id == user_id,
                    models.LLMModelConfig.is_default == True
                )
            )
            .values(is_default=False)
        )

        # Set new default
        query = update(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.user_id == user_id
            )
        ).values(is_default=True)
        result = await self._db_session.execute(query)
        await self._db_session.commit()
        return result.rowcount > 0

    # Group configuration methods

    async def get_group_config(self, config_id: UUID) -> Optional[models.LLMModelConfig]:
        """Get a group's LLM model configuration by ID."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.group_id.isnot(None)
            )
        )
        result = await self._db_session.execute(query)
        return result.scalars().first()

    async def get_group_configs(self, group_id: UUID) -> List[models.LLMModelConfig]:
        """Get all LLM model configurations for a group."""
        query = select(models.LLMModelConfig).where(
            models.LLMModelConfig.group_id == group_id
        ).order_by(models.LLMModelConfig.created_at)
        result = await self._db_session.execute(query)
        return result.scalars().all()

    async def get_group_default_config(self, group_id: UUID) -> Optional[models.LLMModelConfig]:
        """Get a group's default LLM model configuration."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.group_id == group_id,
                models.LLMModelConfig.is_default == True
            )
        )
        result = await self._db_session.execute(query)
        return result.scalars().first()

    async def create_group_config(
        self,
        group_id: UUID,
        config_data: Dict[str, Any],
        is_default: bool = False
    ) -> models.LLMModelConfig:
        """Create a new LLM model configuration for a group."""
        # Encrypt API key if present
        from gns3server.utils.encryption import encrypt
        config_to_store = config_data.copy()
        if "api_key" in config_to_store and config_to_store["api_key"]:
            try:
                config_to_store["api_key"] = encrypt(config_to_store["api_key"])
            except Exception as e:
                log.error(f"Failed to encrypt API key: {e}")
                raise

        db_config = models.LLMModelConfig(
            config=config_to_store,
            group_id=group_id,
            is_default=is_default
        )
        self._db_session.add(db_config)
        await self._db_session.commit()
        await self._db_session.refresh(db_config)
        return db_config

    async def update_group_config(
        self,
        config_id: UUID,
        group_id: UUID,
        updates: Dict[str, Any]
    ) -> Optional[models.LLMModelConfig]:
        """Update a group's LLM model configuration."""
        query = select(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.group_id == group_id
            )
        )
        result = await self._db_session.execute(query)
        db_config = result.scalars().first()

        if not db_config:
            return None

        # Encrypt API key if present in updates
        from gns3server.utils.encryption import encrypt
        updates_copy = updates.copy()
        if "api_key" in updates_copy and updates_copy["api_key"]:
            try:
                updates_copy["api_key"] = encrypt(updates_copy["api_key"])
            except Exception as e:
                log.error(f"Failed to encrypt API key: {e}")
                raise

        # Update config JSONB fields
        current_config = db_config.config.copy()
        for key, value in updates_copy.items():
            if key == "is_default":
                db_config.is_default = value
            elif value is not None:
                current_config[key] = value

        db_config.config = current_config
        await self._db_session.commit()
        await self._db_session.refresh(db_config)
        return db_config

    async def delete_group_config(self, config_id: UUID, group_id: UUID) -> bool:
        """Delete a group's LLM model configuration."""
        query = delete(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.group_id == group_id
            )
        )
        result = await self._db_session.execute(query)
        await self._db_session.commit()
        return result.rowcount > 0

    async def set_group_default_config(self, group_id: UUID, config_id: UUID) -> bool:
        """Set a group's default LLM model configuration."""
        # First, unset current default
        await self._db_session.execute(
            update(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.group_id == group_id,
                    models.LLMModelConfig.is_default == True
                )
            )
            .values(is_default=False)
        )

        # Set new default
        query = update(models.LLMModelConfig).where(
            and_(
                models.LLMModelConfig.config_id == config_id,
                models.LLMModelConfig.group_id == group_id
            )
        ).values(is_default=True)
        result = await self._db_session.execute(query)
        await self._db_session.commit()
        return result.rowcount > 0

    # Inheritance methods

    async def get_user_effective_configs(self, user_id: UUID) -> Dict[str, Any]:
        """
        Get user's effective configurations (own + inherited from groups).
        Returns a dict with 'configs' list and 'default_config'.
        """
        from gns3server.utils.encryption import decrypt, is_encrypted

        # Get user's own configs
        user_configs = await self.get_user_configs(user_id)

        # Get user's groups
        query = select(models.UserGroup).\
            join(models.UserGroup.users).\
            filter(models.User.user_id == user_id)
        result = await self._db_session.execute(query)
        user_groups = result.scalars().all()

        # Get group configs
        group_configs_map = {}  # group_id -> [configs]
        group_names_map = {}  # group_id -> group_name
        for group in user_groups:
            configs = await self.get_group_configs(group.user_group_id)
            if configs:
                group_configs_map[group.user_group_id] = configs
                group_names_map[group.user_group_id] = group.name

        # Decrypt API keys and build result
        configs_with_source = []
        default_config = None

        # Add user's configs
        for config in user_configs:
            config_dict = config.config.copy()
            if "api_key" in config_dict and config_dict["api_key"]:
                try:
                    if is_encrypted(config_dict["api_key"]):
                        config_dict["api_key"] = decrypt(config_dict["api_key"])
                except Exception as e:
                    log.warning(f"Failed to decrypt API key for config {config.config_id}: {e}")
                    config_dict["api_key"] = None

            configs_with_source.append({
                "config_id": config.config_id,
                "source": "user",
                "group_name": None,
                "is_default": config.is_default,
                **config_dict
            })

            if config.is_default and default_config is None:
                default_config = configs_with_source[-1]

        # Add inherited group configs (only if user has no configs)
        if not user_configs:
            for group_id, configs in group_configs_map.items():
                for config in configs:
                    config_dict = config.config.copy()
                    if "api_key" in config_dict and config_dict["api_key"]:
                        try:
                            if is_encrypted(config_dict["api_key"]):
                                config_dict["api_key"] = decrypt(config_dict["api_key"])
                        except Exception as e:
                            log.warning(f"Failed to decrypt API key for config {config.config_id}: {e}")
                            config_dict["api_key"] = None

                    configs_with_source.append({
                        "config_id": config.config_id,
                        "source": "group",
                        "group_name": group_names_map[group_id],
                        "is_default": config.is_default,
                        **config_dict
                    })

                    if config.is_default and default_config is None:
                        default_config = configs_with_source[-1]

        return {
            "configs": configs_with_source,
            "default_config": default_config
        }
