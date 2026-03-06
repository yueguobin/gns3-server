# User-Selectable Group Default Config

**Document Status**: Design Phase
**Priority**: Medium
**Created**: 2026-03-06
**Related Docs**: [LLM Model Configs API](../llm-model-configs-api.md)

---

## Table of Contents

- [Problem Description](#problem-description)
- [Current State Analysis](#current-state-analysis)
- [Requirements Analysis](#requirements-analysis)
- [Solution Design](#solution-design)
- [Implementation Steps](#implementation-steps)
- [Code Changes Checklist](#code-changes-checklist)
- [Testing Plan](#testing-plan)
- [Risk Assessment](#risk-assessment)

---

## Problem Description

### Current Behavior

Regular users cannot select an inherited group LLM model config as their default config, even though they can see the inherited group configs in their config list.

### User Scenario

1. Administrator creates multiple LLM model configs for a user group (e.g., GPT-4, Claude 3.5, Gemini Pro)
2. The group default is set to GPT-4
3. Users inherit these configs and can see all group configs in their config list
4. Users want to use Claude 3.5 as their default, but have no way to set it via API

### Existing Code Limitation

**File**: `gns3server/db/repositories/llm_model_configs.py:194-218`

```python
async def set_user_default_config(self, user_id: UUID, config_id: UUID) -> bool:
    """Set a user's default LLM model configuration."""
    # ...

    # Set new default
    query = update(models.LLMModelConfig).where(
        and_(
            models.LLMModelConfig.config_id == config_id,
            models.LLMModelConfig.user_id == user_id  # KEY LIMITATION
        )
    ).values(is_default=True, updated_at=now)
```

**Problem**: The `user_id == user_id` condition restricts setting only user's own configs. Inherited group configs have `user_id` as `NULL`, so they cannot be set as default.

---

## Current State Analysis

### Current Config Retrieval Flow

```
User requests config list
    ↓
GET /v3/access/users/{user_id}/llm-model-configs
    ↓
get_user_effective_configs(user_id)
    ↓
Returns: {
  configs: [
    { source: "user", ... },      # User's own configs
    { source: "group", ... }      # Inherited group configs
  ],
  default_config: { ... }          # Current default config
}
```

### Default Config Selection Priority

**Current Logic** (`llm_model_configs.py:503-520`):

1. User config marked with `is_default: true`
2. Group config marked with `is_default: true`
3. First config in the list (user configs come before group configs)

### Agent Config Retrieval Flow

**Key Discovery**: Agent retrieves config via `user_id`, doesn't care about config source.

**Flow**:
```
Agent → get_user_llm_config_full(user_id, app)
        ↓
        get_user_effective_configs(user_id)
        ↓
        Returns default config (auto-decrypts API key)
        ↓
        Agent uses config to call LLM
```

**Key Files**:
- `gns3server/db/tasks.py:314-406` - `get_user_llm_config_full`
- `gns3server/api/routes/controller/chat.py:122` - API entry point

### API Key Visibility Control

| Scenario | User Configs | Group Configs |
|----------|-------------|---------------|
| User viewing own configs | **Visible** | **Hidden** (`null`) |
| Admin viewing other users' configs | **Hidden** | **Hidden** |
| Agent usage (system-level) | **Visible** | **Visible** (direct DB access) |

---

## Requirements Analysis

### Functional Requirements

1. **Users can select group config as default**
   - Users can set any accessible config (own or inherited) as default via API
   - API endpoint remains unchanged: `PUT /v3/access/users/{user_id}/llm-model-configs/default/{config_id}`

2. **Maintain API Key Security**
   - Group config API keys remain hidden when users view config list
   - Agent can access and decrypt group config API keys when using

3. **Backward Compatibility**
   - No impact on existing user configs
   - No impact on Agent calling flow
   - Config list response structure remains consistent

### Non-Functional Requirements

1. **Performance**: No significant query overhead
2. **Maintainability**: Clear code logic, easy to understand and maintain
3. **Extensibility**: Future support for config overrides (users modifying certain parameters of inherited configs)

---

## Solution Design

### Selection: Shadow Config Approach

Add `inherited_from_config_id` field to `llm_model_configs` table. When user selects a group config as default, create a "shadow config" record.

### Data Model Design

#### Table Structure Modification

**File**: `gns3server/db/models/llm_model_configs.py`

```python
class LLMModelConfig(BaseTable):
    """LLM model configuration for users and user groups."""

    __tablename__ = "llm_model_configs"

    config_id = Column(GUID, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    model_type = Column(String(50), nullable=False)
    config = Column(JSON, nullable=False)
    user_id = Column(GUID, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True)
    group_id = Column(GUID, ForeignKey("user_groups.user_group_id", ondelete="CASCADE"), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=0, nullable=False)

    # NEW FIELD: Shadow config references original group config
    inherited_from_config_id = Column(
        GUID,
        ForeignKey("llm_model_configs.config_id", ondelete="CASCADE"),
        nullable=True
    )

    # Relationships
    inherited_from = relationship(
        "LLMModelConfig",
        remote_side=[config_id],
        backref="shadow_configs"
    )

    # Constraints
    __table_args__ = (
        # Original constraints...
        CheckConstraint(
            "(user_id IS NOT NULL AND group_id IS NULL) OR "
            "(user_id IS NULL AND group_id IS NOT NULL)",
            name="single_owner_check"
        ),
        # NEW CONSTRAINT: Shadow configs must belong to users
        CheckConstraint(
            "inherited_from_config_id IS NULL OR user_id IS NOT NULL",
            name="shadow_config_belong_to_user"
        ),
        # ... other constraints
    )
```

### Shadow Config Explanation

| Field | Value | Description |
|------|-------|-------------|
| `config_id` | New UUID | Shadow config's unique identifier |
| `name` | Original group config's name | Display name |
| `model_type` | Original group config's type | Config type |
| `config` | `{"api_key": "__INHERITED_FROM_GROUP__", ...}` | Config data, API key marked with special value |
| `user_id` | Current user's ID | Belongs to user |
| `group_id` | `NULL` | Shadow config doesn't belong to group |
| `is_default` | `true` | Marked as default config |
| `inherited_from_config_id` | Original group config's ID | References original config |

### Workflow

#### 1. User Sets Group Config as Default

```
User Request: PUT /users/{user_id}/llm-model-configs/default/{group_config_id}
    ↓
set_user_default_config(user_id, group_config_id)
    ↓
Detects group_config_id is a group config
    ↓
Creates shadow config:
  - user_id = current user
  - inherited_from_config_id = group_config_id
  - config = original config (API key marked as "__INHERITED_FROM_GROUP__")
  - is_default = true
    ↓
Deletes old shadow configs and default flags
    ↓
Commits to database
```

#### 2. User Views Config List

```
GET /users/{user_id}/llm-model-configs
    ↓
get_user_effective_configs(user_id)
    ↓
Gets user configs (including shadow configs)
    ↓
For shadow configs:
  - Reads complete data from original group config
  - Hides API key (sets to null)
  - Marks source = "user"
  - Marks inherited_from = original config ID
    ↓
Returns config list
```

#### 3. Agent Retrieves Config for Usage

```
Agent → get_user_llm_config_full(user_id, app)
        ↓
        Gets default config (detects it's a shadow config)
        ↓
        Gets encrypted API key from original group config
        ↓
        Decrypts API key
        ↓
        Returns complete config (including API key)
        ↓
        Agent uses config to call LLM
```

### Solution Advantages

| Advantage | Description |
|-----------|-------------|
| **Data Integrity** | Foreign key constraints ensure referential integrity, cascading deletes handle cleanup |
| **Backward Compatible** | No modification to existing logic, shadow config is a new feature |
| **Clear Semantics** | `inherited_from_config_id` clearly indicates inheritance relationship |
| **Unified API** | Users don't need to care about config source, just select directly |
| **Extensible** | Shadow config can add override fields in the future (e.g., user-custom parameters) |
| **No Agent Changes Required** | Agent still retrieves config via `user_id`, automatically compatible |

---

## Implementation Steps

### Step 1: Database Migration

Create new migration file: `gns3server/db_migrations/versions/{timestamp}_add_inherited_from_config_id.py`

```python
"""Add inherited_from_config_id to llm_model_configs table

Revision ID: xxx_add_inherited_from_config_id
Revises: [previous_revision_id]
Create Date: 2026-03-06

This migration adds support for shadow configs, allowing users to select
inherited group configurations as their default.
"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # Add the new column
    op.add_column(
        'llm_model_configs',
        sa.Column(
            'inherited_from_config_id',
            sa.GUID(),
            nullable=True
        )
    )

    # Create foreign key constraint
    op.create_foreign_key(
        'fk_llm_configs_inherited_from',
        'llm_model_configs', 'llm_model_configs',
        ['inherited_from_config_id'], ['config_id'],
        ondelete='CASCADE'
    )

    # Add check constraint: shadow configs must belong to users
    op.execute("""
        ALTER TABLE llm_model_configs
        ADD CONSTRAINT shadow_config_belong_to_user
        CHECK (inherited_from_config_id IS NULL OR user_id IS NOT NULL)
    """)


def downgrade():
    # Remove constraints and column
    op.execute("ALTER TABLE llm_model_configs DROP CONSTRAINT shadow_config_belong_to_user")
    op.drop_constraint('fk_llm_configs_inherited_from', 'llm_model_configs', type_='foreignkey')
    op.drop_column('llm_model_configs', 'inherited_from_config_id')
```

### Step 2: Modify Data Model

**File**: `gns3server/db/models/llm_model_configs.py`

Add to `LLMModelConfig` class:
- `inherited_from_config_id` field
- `inherited_from` relationship
- `shadow_config_belong_to_user` constraint

### Step 3: Modify Repository Layer

**File**: `gns3server/db/repositories/llm_model_configs.py`

#### 3.1 Modify `set_user_default_config` Method

```python
async def set_user_default_config(self, user_id: UUID, config_id: UUID) -> bool:
    """
    Set a user's default LLM model configuration.
    Supports setting inherited group configs as default via shadow configs.

    Args:
        user_id: User UUID
        config_id: Configuration UUID (can be user's own or inherited group config)

    Returns:
        True if successful, False if config not found or not accessible
    """
    from gns3server.utils.encryption import is_encrypted

    # Check if config is accessible to user
    effective = await self.get_user_effective_configs(
        user_id,
        current_user_id=user_id
    )
    accessible_config_ids = {c["config_id"] for c in effective["configs"]}

    if config_id not in accessible_config_ids:
        return False

    # Get the original config
    result = await self._db_session.execute(
        select(models.LLMModelConfig).where(
            models.LLMModelConfig.config_id == config_id
        )
    )
    orig_config = result.scalars().first()

    if not orig_config:
        return False

    now = datetime.utcnow()

    if orig_config.user_id == user_id:
        # Scenario 1: User selects their own config
        # Use the existing is_default mechanism

        # Delete old shadow configs
        await self._db_session.execute(
            delete(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.user_id == user_id,
                    models.LLMModelConfig.inherited_from_config_id.isnot(None)
                )
            )
        )

        # Clear all user default flags
        await self._db_session.execute(
            update(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.user_id == user_id,
                    models.LLMModelConfig.is_default == True
                )
            )
            .values(is_default=False, updated_at=now)
        )

        # Set new default
        await self._db_session.execute(
            update(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.config_id == config_id,
                    models.LLMModelConfig.user_id == user_id
                )
            )
            .values(is_default=True, updated_at=now)
        )
    else:
        # Scenario 2: User selects a group config - create shadow config

        # Clear all user default flags
        await self._db_session.execute(
            update(models.LLMModelConfig)
            .where(models.LLMModelConfig.user_id == user_id)
            .values(is_default=False)
        )

        # Delete old shadow configs
        await self._db_session.execute(
            delete(models.LLMModelConfig)
            .where(
                and_(
                    models.LLMModelConfig.user_id == user_id,
                    models.LLMModelConfig.inherited_from_config_id.isnot(None)
                )
            )
        )

        # Copy config data, but mark API key as inherited
        shadow_config_data = orig_config.config.copy()
        shadow_config_data["api_key"] = "__INHERITED_FROM_GROUP__"

        # Create shadow config
        shadow_config = models.LLMModelConfig(
            name=orig_config.name,
            model_type=orig_config.model_type,
            config=shadow_config_data,
            user_id=user_id,
            group_id=None,
            is_default=True,
            inherited_from_config_id=config_id,
            version=0,
            created_at=now,
            updated_at=now
        )
        self._db_session.add(shadow_config)

    await self._db_session.commit()
    return True
```

#### 3.2 Modify `get_user_effective_configs` Method

Add special logic for shadow config handling:

```python
# In get_user_effective_configs method

# Process user configs (including shadow configs)
user_configs = await self.get_user_configs(user_id)

# Build map of group configs for shadow config resolution
group_configs_map = {}
group_names_map = {}
for group in user_groups:
    configs = await self.get_group_configs(group.user_group_id)
    if configs:
        group_configs_map[group.user_group_id] = configs
        group_names_map[group.user_group_id] = group.name

# Flatten group configs for easy access
all_group_configs = {}
for configs in group_configs_map.values():
    for config in configs:
        all_group_configs[config.config_id] = config

configs_with_source = []

# Process each user config
for config in user_configs:
    if config.inherited_from_config_id:
        # This is a shadow config - resolve from parent group config
        parent_config = all_group_configs.get(config.inherited_from_config_id)
        if parent_config:
            config_dict = parent_config.config.copy()

            # Hide API key in shadow configs (users viewing their own configs)
            if "api_key" in config_dict:
                config_dict["api_key"] = None

            configs_with_source.append({
                "config_id": config.config_id,
                "name": config.name,
                "model_type": config.model_type,
                "config": config_dict,
                "user_id": config.user_id,
                "group_id": None,
                "is_default": config.is_default,
                "version": config.version,
                "created_at": config.created_at,
                "updated_at": config.updated_at,
                "source": "user",
                "inherited_from": config.inherited_from_config_id,
                "group_name": group_names_map.get(parent_config.group_id)
            })
    else:
        # Regular user config - existing logic
        config_dict = config.config.copy()

        # API key visibility control
        if "api_key" in config_dict and config_dict["api_key"]:
            if is_viewing_own:
                try:
                    if is_encrypted(config_dict["api_key"]):
                        config_dict["api_key"] = decrypt(config_dict["api_key"])
                except Exception as e:
                    log.warning(f"Failed to decrypt API key: {e}")
                    config_dict["api_key"] = None
            else:
                config_dict["api_key"] = None

        configs_with_source.append({
            "config_id": config.config_id,
            "name": config.name,
            "model_type": config.model_type,
            "config": config_dict,
            "user_id": config.user_id,
            "group_id": config.group_id,
            "is_default": config.is_default,
            "version": config.version,
            "created_at": config.created_at,
            "updated_at": config.updated_at,
            "source": "user",
            "inherited_from": None,
            "group_name": None
        })

# Add inherited group configs (exclude those already shadowed)
shadow_inherited_ids = {
    c["inherited_from"]
    for c in configs_with_source
    if c["inherited_from"]
}

for group_id, configs in group_configs_map.items():
    for config in configs:
        if config.config_id in shadow_inherited_ids:
            continue  # Already shadowed, don't duplicate

        config_dict = config.config.copy()
        if "api_key" in config_dict:
            config_dict["api_key"] = None

        configs_with_source.append({
            "config_id": config.config_id,
            "name": config.name,
            "model_type": config.model_type,
            "config": config_dict,
            "user_id": None,
            "group_id": config.group_id,
            "is_default": config.is_default,
            "version": config.version,
            "created_at": config.created_at,
            "updated_at": config.updated_at,
            "source": "group",
            "inherited_from": None,
            "group_name": group_names_map[group_id]
        })

# Select default_config (shadow configs have priority since marked is_default=true)
default_config = None
for config in configs_with_source:
    if config["is_default"] and config["source"] == "user":
        default_config = config
        break

if default_config is None:
    for config in configs_with_source:
        if config["is_default"] and config["source"] == "group":
            default_config = config
            break

if default_config is None and configs_with_source:
    default_config = configs_with_source[0]

return {
    "configs": configs_with_source,
    "default_config": default_config
}
```

### Step 4: Modify System-Level Config Retrieval

**File**: `gns3server/db/tasks.py`

Modify `get_user_llm_config_full` function to add shadow config API key decryption logic:

```python
async def get_user_llm_config_full(user_id: str, app: FastAPI) -> Optional[dict]:
    """
    Get user's full LLM configuration with decrypted API key for Copilot.

    This is a system-level function that bypasses API security restrictions.
    It retrieves the complete configuration including decrypted API keys,
    even for inherited group configurations and shadow configs.

    Args:
        user_id: User UUID
        app: FastAPI application instance

    Returns:
        Dictionary with LLM configuration (provider, model, api_key, etc.)
        or None if not found.
    """
    from uuid import UUID
    from gns3server.db.repositories.llm_model_configs import LLMModelConfigsRepository
    from gns3server.utils.encryption import decrypt, is_encrypted

    try:
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id

        async with AsyncSession(app.state._db_engine, expire_on_commit=False) as session:
            repo = LLMModelConfigsRepository(session)

            # Get effective configs (own + inherited from groups)
            result = await repo.get_user_effective_configs(
                user_uuid,
                current_user_id=user_uuid,
                current_user_is_superadmin=False
            )

            if not result or not result.get("default_config"):
                log.warning(f"No default LLM configuration found for user {user_id}")
                return None

            default_config = result["default_config"]
            config_id = default_config["config_id"]
            source = default_config["source"]
            inherited_from = default_config.get("inherited_from")

            # Get full config from database
            full_config = await repo.get_user_config(config_id)

            if not full_config:
                log.error(f"Failed to retrieve full config: config_id={config_id}")
                return None

            # Decrypt API key
            config_data = full_config.config.copy()
            inherited_from_config_id = full_config.inherited_from_config_id

            # If shadow config, get API key from parent group config
            if inherited_from_config_id:
                parent_config = await repo.get_group_config(inherited_from_config_id)
                if parent_config and "api_key" in parent_config.config:
                    try:
                        encrypted_key = parent_config.config["api_key"]
                        if encrypted_key and is_encrypted(encrypted_key):
                            config_data["api_key"] = decrypt(encrypted_key)
                            log.debug(f"Decrypted API key from inherited group config for user {user_id}")
                        else:
                            config_data["api_key"] = encrypted_key
                    except Exception as e:
                        log.error(f"Failed to decrypt inherited API key: {e}")
                        config_data["api_key"] = None
                else:
                    log.error(f"Parent group config not found for shadow config: {inherited_from_config_id}")
                    config_data["api_key"] = None
            else:
                # Regular user config - decrypt API key directly
                if "api_key" in config_data and config_data["api_key"]:
                    try:
                        if is_encrypted(config_data["api_key"]):
                            config_data["api_key"] = decrypt(config_data["api_key"])
                            log.debug(f"Successfully decrypted API key for user {user_id}")
                    except Exception as e:
                        log.error(f"Failed to decrypt API key: {e}")
                        config_data["api_key"] = None

            # Build configuration dict
            llm_config = {
                "config_id": str(full_config.config_id),
                "name": full_config.name,
                "model_type": str(full_config.model_type),
                "source": source,
                "inherited_from": str(inherited_from_config_id) if inherited_from_config_id else None,
                "group_name": default_config.get("group_name"),
                "user_id": str(full_config.user_id) if full_config.user_id else None,
                "group_id": str(full_config.group_id) if full_config.group_id else None,
                **config_data
            }

            # Validate required fields
            if not llm_config.get("provider"):
                log.error(f"LLM config missing 'provider' field: {config_id}")
                return None

            if not llm_config.get("model"):
                log.error(f"LLM config missing 'model' field: {config_id}")
                return None

            log.info(
                f"Retrieved LLM config for user {user_id}: "
                f"provider={llm_config.get('provider')}, model={llm_config.get('model')}, "
                f"source={source}, inherited_from={inherited_from_config_id}"
            )

            return llm_config

    except Exception as e:
        log.error(f"Failed to retrieve LLM config for user {user_id}: {e}", exc_info=True)
        return None
```

### Step 5: Update Schema (Optional)

If you want to display `inherited_from` field in API response, update relevant Schema:

**File**: `gns3server/schemas/controller/chat.py` or corresponding schema file

```python
class LLMModelConfigWithSource(BaseModel):
    """LLM model configuration with source information."""
    config_id: UUID
    name: str
    model_type: str
    config: Dict[str, Any]
    user_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime
    source: str  # "user" or "group"
    group_name: Optional[str] = None
    inherited_from: Optional[UUID] = None  # NEW FIELD
```

### Step 6: Update API Documentation

**File**: `docs/gns3-copilot/llm-model-configs-api.md`

Add `inherited_from` field description in response schema section:

```markdown
### LLMModelConfigWithSource

| Field | Type | Description |
|-------|------|-------------|
| ...
| `inherited_from` | UUID (nullable) | For shadow configs, the ID of the inherited group config |
```

---

## Code Changes Checklist

### Files to Modify

| File Path | Change Type | Description |
|-----------|-------------|-------------|
| `gns3server/db/models/llm_model_configs.py` | Modify | Add `inherited_from_config_id` field and relationship |
| `gns3server/db/repositories/llm_model_configs.py` | Modify | Modify `set_user_default_config` and `get_user_effective_configs` |
| `gns3server/db/tasks.py` | Modify | Modify `get_user_llm_config_full` to support shadow configs |
| `gns3server/schemas/...` | Modify (Optional) | Add `inherited_from` field to Schema |
| `gns3server/db_migrations/versions/...` | New | Database migration file |
| `docs/gns3-copilot/llm-model-configs-api.md` | Modify | Update API documentation |

### New Files

| File Path | Description |
|-----------|-------------|
| `gns3server/db_migrations/versions/{timestamp}_add_inherited_from_config_id.py` | Database migration |

---

## Testing Plan

### Unit Tests

#### 1. Test `set_user_default_config`

- **Test 1.1**: User sets their own config as default
  - Input: User's config ID
  - Expected: `is_default=true`, old shadow configs deleted

- **Test 1.2**: User sets group config as default
  - Input: Group config ID
  - Expected: Shadow config created, `inherited_from_config_id` points to group config

- **Test 1.3**: User switches default config (from own to group config)
  - Input: Group config ID
  - Expected: Old shadow config deleted, new shadow config created

- **Test 1.4**: User sets non-existent config as default
  - Input: Invalid config ID
  - Expected: Returns `False`

- **Test 1.5**: User sets inaccessible config as default
  - Input: Other user's group config ID
  - Expected: Returns `False`

#### 2. Test `get_user_effective_configs`

- **Test 2.1**: User with only own configs
  - Expected: Returns user configs, no `inherited_from` field

- **Test 2.2**: User with inherited group configs, no default set
  - Expected: Returns user configs + group configs, `default_config` is first user config or first group config

- **Test 2.3**: User set group config as default (shadow config)
  - Expected: Shadow config `source="user"`, `is_default=true`, `inherited_from` points to group config, API key is `null`

- **Test 2.4**: User viewing own configs (API key visibility)
  - Expected: Own config shows API key, shadow config and group config hide API key

#### 3. Test `get_user_llm_config_full`

- **Test 3.1**: User using own default config
  - Expected: Returns config with decrypted API key

- **Test 3.2**: User using shadow config (group config)
  - Expected: Retrieves and decrypts API key from original group config

- **Test 3.3**: Shadow config's original group config deleted
  - Expected: Returns `None` or appropriate error handling

### Integration Tests

#### 1. API Endpoint Tests

- **Test 1.1**: `PUT /users/{user_id}/llm-model-configs/default/{group_config_id}`
  - Request: Set group config as default
  - Expected: Returns 200, config set as default

- **Test 1.2**: `GET /users/{user_id}/llm-model-configs`
  - Expected: Shadow config appears in list, `source="user"`, `inherited_from` field exists

- **Test 1.3**: `GET /users/{user_id}/llm-model-configs/default`
  - Expected: Returns shadow config

#### 2. Agent Integration Tests

- **Test 2.1**: User using shadow config calls Agent
  - Expected: Agent successfully retrieves config and calls LLM

- **Test 2.2**: Multiple users using same group config as default
  - Expected: Each user has their own shadow config, no interference

### Security Tests

- **Test 1**: User views config list, shadow config's API key is hidden
- **Test 2**: Admin views other user's config, API key is hidden
- **Test 3**: User cannot set other user's config as default
- **Test 4**: Cascading delete: Group config deleted, shadow config auto-deleted

---

## Risk Assessment

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Database migration failure | High | Low | Thoroughly test migration script, prepare rollback plan |
| Shadow config out of sync with original config | Medium | Medium | Shadow config dynamically reads from original config, real-time sync |
| API key decryption failure | High | Low | Add error handling and logging |
| Performance impact | Low | Low | Limited number of shadow configs, negligible performance impact |

### Business Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| User confusion (shadow config vs own config) | Medium | Medium | Clearly indicate inheritance source in UI |
| Users unaware of group config updates | Low | Low | Document behavior, or add config version notification in the future |

### Compatibility Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Existing API clients incompatible with `inherited_from` field | Low | Low | Field is optional, old clients can ignore it |
| Agent doesn't support shadow config | High | Low | Agent retrieves config via `user_id`, automatically compatible |

---

## Future Enhancements

### Potential Future Features

1. **Config Overrides**: Allow users to override certain parameters in shadow config (e.g., `temperature`)
2. **Change Notifications**: Notify users when group config is updated
3. **Config Version Tracking**: Record change history of configs
4. **Config Recommendations**: Recommend default configs based on usage patterns

### Related Features

- Support user config templates (create own config based on group config)
- Config import/export functionality
- Batch config management

---

## References

- [LLM Model Configs API](../llm-model-configs-api.md)
- [AI Chat API Design](../ai-chat-api-design.md)
- SQLAlchemy Foreign Key: https://docs.sqlalchemy.org/en/14/core/metadata.html
- Alembic Migrations: https://alembic.sqlalchemy.org/en/latest/tutorial.html

---

**Document Version**: 1.0
**Last Updated**: 2026-03-06
