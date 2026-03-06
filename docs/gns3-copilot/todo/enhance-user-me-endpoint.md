# Enhance `/me` Endpoint with Groups, Pools, and ACEs

**Document Status**: Design Phase
**Priority**: High
**Created**: 2026-03-06
**Related Docs**: [User-Selectable Group Default Config](./user-selectable-group-default-config.md)

---

## Table of Contents

- [Problem Description](#problem-description)
- [Data Model Analysis](#data-model-analysis)
- [Solution Design](#solution-design)
- [Implementation Steps](#implementation-steps)
- [API Response Structure](#api-response-structure)
- [Testing Plan](#testing-plan)

---

## Problem Description

### Current Behavior

The `/me` endpoint only returns basic user information. Users cannot easily see:
1. Which groups they belong to
2. Which resource pools they have access to
3. Their access control entries (ACEs)

### User Needs

1. **Group Membership**: Understand inherited configs and permissions
2. **Pool Access**: Know which resource pools are available
3. **ACE Visibility**: See what access control rules apply to them

---

## Data Model Analysis

### User Model Relationships

**File**: `gns3server/db/models/users.py:38-52`

```python
class User(BaseTable):
    __tablename__ = "users"

    user_id = Column(GUID, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    full_name = Column(String)
    hashed_password = Column(String)
    last_login = Column(DateTime)
    is_active = Column(Boolean, default=True)
    is_superadmin = Column(Boolean, default=False)

    # Relationships
    groups = relationship("UserGroup", secondary=user_group_map, back_populates="users")
    acl_entries = relationship("ACE")  # User's direct ACEs
```

### ACE Model

**File**: `gns3server/db/models/acl.py:28-46`

```python
class ACE(BaseTable):
    __tablename__ = "acl"

    ace_id = Column(GUID, primary_key=True, default=generate_uuid)
    ace_type = Column(String)  # "user" or "group"
    path = Column(String)       # e.g., "/pools/{pool_id}", "/projects"
    propagate = Column(Boolean, default=True)
    allowed = Column(Boolean, default=True)
    user_id = Column(GUID, ForeignKey('users.user_id', ondelete="CASCADE"))
    user = relationship("User", back_populates="acl_entries")
    group_id = Column(GUID, ForeignKey('user_groups.user_group_id', ondelete="CASCADE"))
    group = relationship("UserGroup", back_populates="acl_entries")
    role_id = Column(GUID, ForeignKey('roles.role_id', ondelete="CASCADE"))
    role = relationship("Role", back_populates="acl_entries")
```

### Resource Pool Model

**File**: `gns3server/db/models/pools.py:46-53`

```python
class ResourcePool(BaseTable):
    __tablename__ = "resource_pools"

    resource_pool_id = Column(GUID, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, index=True)
    resources = relationship("Resource", secondary=resource_pool_map, back_populates="resource_pools")
```

### Key Relationships

```
User ────< UserGroup > (via user_group_map)
  │
  └───< ACE (user_id)
              │
              ├── path = "/pools/{pool_id}" → ResourcePool
              ├── path = "/projects"
              ├── role → Role → Privilege
              └── allowed (boolean)

UserGroup ────< ACE (group_id)
  │
  └─── users
```

### Pool Path Format

From `gns3server/db/repositories/rbac.py:326-327`:

```python
if ace_path.startswith("/pool"):
    resource_pool_id = ace_path.split("/")[2]
```

**Pool ACE Path Format**: `/pools/{resource_pool_id}`

---

## Solution Design

### Approach

1. **Groups**: Eager load via `selectinload(User.groups)`
2. **Pools**: Extract from user and group ACEs where path starts with `/pools/`
3. **ACEs**: Aggregate user's direct ACEs and group ACEs

### Response Structure

```json
{
  // ===== Basic User Info =====
  "user_id": "uuid",
  "username": "string",
  "email": "string",
  "full_name": "string",
  "is_active": true,
  "is_superadmin": false,
  "last_login": "datetime",
  "created_at": "datetime",
  "updated_at": "datetime",

  // ===== User Groups =====
  "groups": [
    {
      "user_group_id": "uuid",
      "name": "Developers",
      "is_builtin": false,
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ],

  // ===== Accessible Pools =====
  "pools": [
    {
      "resource_pool_id": "uuid",
      "name": "Production Pool",
      "access_source": "user",  // "user" or "group"
      "access_allowed": true
    }
  ],

  // ===== ACEs =====
  "aces": [
    {
      "ace_id": "uuid",
      "path": "/pools/{pool_id}",
      "allowed": true,
      "propagate": true,
      "ace_type": "user",  // "user" or "group"
      "source_group_id": null,  // null if ace_type is "user"
      "source_group_name": null
    }
  ]
}
```

---

## Implementation Steps

### Step 1: Update Schemas

**File**: `gns3server/schemas/controller/users.py`

```python
from typing import List, Optional
from datetime import datetime
from pydantic import ConfigDict, EmailStr, BaseModel, Field, SecretStr
from uuid import UUID

from .base import DateTimeModelMixin


class UserGroup(BaseModel):
    """User group reference."""
    user_group_id: UUID
    name: str
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResourcePoolInfo(BaseModel):
    """Resource pool info accessible to user."""
    resource_pool_id: UUID
    name: str
    access_source: str = Field(..., description="'user' or 'group'")
    access_allowed: bool = Field(..., description="Whether access is allowed")

    model_config = ConfigDict(from_attributes=True)


class ACEInfo(BaseModel):
    """Access Control Entry info."""
    ace_id: UUID
    path: str
    allowed: bool
    propagate: bool
    ace_type: str = Field(..., description="'user' or 'group'")
    source_group_id: Optional[UUID] = Field(None, description="Group ID if from group ACE")
    source_group_name: Optional[str] = Field(None, description="Group name if from group ACE")

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    """Common user properties."""
    username: Optional[str] = Field(None, min_length=3, pattern="[a-zA-Z0-9_-]+$")
    is_active: bool = True
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class User(DateTimeModelMixin, UserBase):
    user_id: UUID
    last_login: Optional[datetime] = None
    is_superadmin: bool = False

    # NEW FIELDS
    groups: List[UserGroup] = []
    pools: List[ResourcePoolInfo] = []
    aces: List[ACEInfo] = []

    model_config = ConfigDict(from_attributes=True)


# Other existing schemas...
class UserCreate(UserBase):
    username: str = Field(..., min_length=3, pattern="[a-zA-Z0-9_-]+$")
    password: SecretStr = Field(..., min_length=8, max_length=100)


class UserUpdate(UserBase):
    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)


class LoggedInUserUpdate(BaseModel):
    password: Optional[SecretStr] = Field(None, min_length=8, max_length=100)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class Credentials(BaseModel):
    username: str
    password: str
```

### Step 2: Update Repository Method

**File**: `gns3server/db/repositories/users.py`

```python
from uuid import UUID
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .base import BaseRepository

import gns3server.db.models as models
from gns3server import schemas
from gns3server.services import auth_service

import logging

log = logging.getLogger(__name__)


class UsersRepository(BaseRepository):

    # ... existing methods ...

    async def get_user_with_details(
        self,
        user_id: UUID,
        include_pools: bool = True,
        include_aces: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get user with groups, pools, and ACEs.

        Args:
            user_id: User UUID
            include_pools: Whether to include accessible resource pools
            include_aces: Whether to include ACEs

        Returns:
            Dictionary with user, groups, pools, and aces
        """

        # Get user with groups eagerly loaded
        query = select(models.User).where(
            models.User.user_id == user_id
        ).options(selectinload(models.User.groups))

        result = await self._db_session.execute(query)
        user = result.scalars().first()

        if not user:
            return None

        # Prepare response
        response = {
            "user": user,
            "groups": list(user.groups),
            "pools": [],
            "aces": []
        }

        if not include_pools and not include_aces:
            return response

        # Get user's direct ACEs
        user_aces_query = select(models.ACE).where(
            models.ACE.user_id == user_id
        )
        user_aces_result = await self._db_session.execute(user_aces_query)
        user_aces = user_aces_result.scalars().all()

        # Get group ACEs (inherited from user's groups)
        group_aces = []
        for group in user.groups:
            group_aces_query = select(models.ACE).where(
                models.ACE.group_id == group.user_group_id
            )
            group_aces_result = await self._db_session.execute(group_aces_query)
            group_aces.extend(group_aces_result.scalars().all())

        # Process ACEs and extract pools
        pool_ids_seen = set()

        if include_aces:
            # Add user ACEs
            for ace in user_aces:
                response["aces"].append({
                    "ace_id": ace.ace_id,
                    "path": ace.path,
                    "allowed": ace.allowed,
                    "propagate": ace.propagate,
                    "ace_type": "user",
                    "source_group_id": None,
                    "source_group_name": None
                })

            # Add group ACEs
            for ace in group_aces:
                response["aces"].append({
                    "ace_id": ace.ace_id,
                    "path": ace.path,
                    "allowed": ace.allowed,
                    "propagate": ace.propagate,
                    "ace_type": "group",
                    "source_group_id": ace.group_id,
                    "source_group_name": next((g.name for g in user.groups if g.user_group_id == ace.group_id), None)
                })

        if include_pools:
            # Extract pools from ACEs
            for ace in user_aces + group_aces:
                if ace.path.startswith("/pools/") and ace.allowed:
                    try:
                        pool_id = UUID(ace.path.split("/")[2])

                        if pool_id not in pool_ids_seen:
                            # Get pool info
                            pool_query = select(models.ResourcePool).where(
                                models.ResourcePool.resource_pool_id == pool_id
                            )
                            pool_result = await self._db_session.execute(pool_query)
                            pool = pool_result.scalars().first()

                            if pool:
                                response["pools"].append({
                                    "resource_pool_id": pool.resource_pool_id,
                                    "name": pool.name,
                                    "access_source": "user" if ace.user_id else "group",
                                    "access_allowed": ace.allowed
                                })
                                pool_ids_seen.add(pool_id)
                    except (ValueError, IndexError) as e:
                        log.warning(f"Invalid pool path format: {ace.path}, error: {e}")

        return response
```

### Step 3: Update API Endpoint

**File**: `gns3server/api/routes/controller/users.py`

```python
@router.get("/me", response_model=schemas.User)
async def get_logged_in_user(
    current_user: schemas.User = Depends(get_current_active_user),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository))
) -> schemas.User:
    """
    Get the current active user (including groups, pools, and ACEs).

    Returns comprehensive user information including:
    - Basic user profile
    - Group memberships
    - Accessible resource pools
    - Access control entries (ACEs)
    """

    # Fetch user with all details
    user_details = await users_repo.get_user_with_details(
        current_user.user_id,
        include_pools=True,
        include_aces=True
    )

    if not user_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Convert to schema
    user = user_details["user"]

    return schemas.User(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        last_login=user.last_login,
        created_at=user.created_at,
        updated_at=user.updated_at,
        groups=[schemas.UserGroup.model_validate(g) for g in user_details["groups"]],
        pools=[schemas.ResourcePoolInfo(**p) for p in user_details["pools"]],
        aces=[schemas.ACEInfo(**a) for a in user_details["aces"]]
    )
```

---

## API Response Structure

### Complete Example

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "johndoe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "is_superadmin": false,
  "last_login": "2026-03-06T10:30:00Z",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-03-06T10:30:00Z",

  "groups": [
    {
      "user_group_id": "650e8400-e29b-41d4-a716-446655440001",
      "name": "Developers",
      "is_builtin": false,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    },
    {
      "user_group_id": "750e8400-e29b-41d4-a716-446655440002",
      "name": "Administrators",
      "is_builtin": true,
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ],

  "pools": [
    {
      "resource_pool_id": "850e8400-e29b-41d4-a716-446655440003",
      "name": "Production Pool",
      "access_source": "user",
      "access_allowed": true
    },
    {
      "resource_pool_id": "950e8400-e29b-41d4-a716-446655440004",
      "name": "Development Pool",
      "access_source": "group",
      "access_allowed": true
    }
  ],

  "aces": [
    {
      "ace_id": "a50e8400-e29b-41d4-a716-446655440005",
      "path": "/pools/850e8400-e29b-41d4-a716-446655440003",
      "allowed": true,
      "propagate": true,
      "ace_type": "user",
      "source_group_id": null,
      "source_group_name": null
    },
    {
      "ace_id": "b50e8400-e29b-41d4-a716-446655440006",
      "path": "/projects",
      "allowed": true,
      "propagate": true,
      "ace_type": "group",
      "source_group_id": "650e8400-e29b-41d4-a716-446655440001",
      "source_group_name": "Developers"
    },
    {
      "ace_id": "c50e8400-e29b-41d4-a716-446655440007",
      "path": "/pools/950e8400-e29b-41d4-a716-446655440004",
      "allowed": true,
      "propagate": true,
      "ace_type": "group",
      "source_group_id": "650e8400-e29b-41d4-a716-446655440001",
      "source_group_name": "Developers"
    }
  ]
}
```

---

## Testing Plan

### Unit Tests

#### Test `get_user_with_details` Repository Method

```python
import pytest
from uuid import uuid4

@pytest.mark.asyncio
async def test_get_user_with_groups_only(db_session, test_user, test_group):
    """Test getting user with groups only."""
    from gns3server.db.repositories.users import UsersRepository

    repo = UsersRepository(db_session)
    result = await repo.get_user_with_details(
        test_user.user_id,
        include_pools=False,
        include_aces=False
    )

    assert result is not None
    assert len(result["groups"]) > 0
    assert result["groups"][0].name == test_group.name
    assert result["pools"] == []
    assert result["aces"] == []


@pytest.mark.asyncio
async def test_get_user_with_pools_and_aces(db_session, test_user, test_pool, test_ace):
    """Test getting user with pools and ACEs."""
    from gns3server.db.repositories.users import UsersRepository

    repo = UsersRepository(db_session)
    result = await repo.get_user_with_details(
        test_user.user_id,
        include_pools=True,
        include_aces=True
    )

    assert result is not None
    assert len(result["pools"]) > 0
    assert result["pools"][0]["name"] == test_pool.name
    assert len(result["aces"]) > 0
    assert result["aces"][0]["path"].startswith("/pools/")


@pytest.mark.asyncio
async def test_get_user_with_group_pools(db_session, test_user, test_group, test_group_pool, test_group_ace):
    """Test getting user with pools inherited from groups."""
    from gns3server.db.repositories.users import UsersRepository

    repo = UsersRepository(db_session)
    result = await repo.get_user_with_details(
        test_user.user_id,
        include_pools=True,
        include_aces=True
    )

    assert result is not None
    # Should have pool from group ACE
    group_pools = [p for p in result["pools"] if p["access_source"] == "group"]
    assert len(group_pools) > 0
```

### Integration Tests

#### Test `/me` Endpoint Response

```python
def test_get_me_with_all_details(test_client, auth_token, test_user_with_groups_and_pools):
    """Test GET /me returns groups, pools, and ACEs."""

    response = test_client.get(
        "/v3/access/users/me",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()

    # Verify basic user info
    assert "user_id" in data
    assert "username" in data

    # Verify groups
    assert "groups" in data
    assert isinstance(data["groups"], list)
    assert len(data["groups"]) > 0
    assert "user_group_id" in data["groups"][0]
    assert "name" in data["groups"][0]

    # Verify pools
    assert "pools" in data
    assert isinstance(data["pools"], list)
    if len(data["pools"]) > 0:
        pool = data["pools"][0]
        assert "resource_pool_id" in pool
        assert "name" in pool
        assert "access_source" in pool
        assert pool["access_source"] in ["user", "group"]

    # Verify ACEs
    assert "aces" in data
    assert isinstance(data["aces"], list)
    if len(data["aces"]) > 0:
        ace = data["aces"][0]
        assert "ace_id" in ace
        assert "path" in ace
        assert "allowed" in ace
        assert "ace_type" in ace
        assert ace["ace_type"] in ["user", "group"]


def test_get_me_user_with_no_groups(test_client, auth_token, test_user_no_groups):
    """Test GET /me for user with no groups."""

    response = test_client.get(
        "/v3/access/users/me",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["groups"] == []
    # May still have pools and ACEs from direct user ACEs
```

---

## Benefits

| Feature | Benefit |
|---------|---------|
| **Groups in /me** | Users see inherited configs and permissions |
| **Pools in /me** | Users know available resource pools without separate API call |
| **ACEs in /me** | Transparency - users see their access control rules |
| **Single API Call** | Frontend gets all user context in one request |
| **No Privilege Required** | Users can always see their own info |

---

## Use Cases

### 1. Frontend User Profile Page

```javascript
// Get complete user context
const response = await fetch('/v3/access/users/me', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const user = await response.json();

// Display groups
console.log('Member of:', user.groups.map(g => g.name));

// Display available pools
console.log('Accessible pools:', user.pools.map(p => p.name));

// Display ACE summary
console.log('ACEs:', user.aces.length);
```

### 2. LLM Config Selection UI

```javascript
// User wants to select from inherited configs
const user = await fetchCurrentUser();

// Show which configs are from which groups
user.groups.forEach(group => {
  console.log(`Configs from ${group.name}:`, getGroupConfigs(group.user_group_id));
});
```

### 3. Permission Troubleshooting

```javascript
// User can't access a resource - why?
const user = await fetchCurrentUser();

// Check if user has pool access
const hasPoolAccess = user.pools.some(p => p.resource_pool_id === targetPoolId);

// Check ACEs
const relevantACEs = user.aces.filter(ace => ace.path.includes(resourcePath));
console.log('Relevant ACEs:', relevantACEs);
```

---

## Performance Considerations

| Query | Complexity | Optimization |
|-------|------------|--------------|
| Get user with groups | 1 JOIN (eager load) | Uses `selectinload` |
| Get user ACEs | 1 query | Direct index lookup |
| Get group ACEs | N queries (one per group) | Could optimize with subquery |
| Get pool details | M queries (one per unique pool) | Could batch fetch |

**Potential Optimization**:

```python
# Batch fetch all pools in one query
pool_ids = [extract_pool_id_from_ace(ace) for ace in all_aces]

pools_query = select(models.ResourcePool).where(
    models.ResourcePool.resource_pool_id.in_(pool_ids)
)
pools_result = await self._db_session.execute(pools_query)
pools = {p.resource_pool_id: p for p in pools_result.scalars().all()}
```

---

## Security Considerations

### Data Exposure

| Data | Visibility | Rationale |
|------|-----------|-----------|
| Basic user info | User themselves | Already exposed in current `/me` |
| Groups | User themselves | User knows which groups they joined |
| Pools | User themselves | User knows which pools they can access |
| ACEs | User themselves | Transparency about access rules |
| Other users' data | **Hidden** | Not included in response |

### Access Control

- **Authentication Required**: Must provide valid JWT token
- **No Special Privilege**: Users can always view their own data
- **Filtering**: Only returns data for the authenticated user

---

## Future Enhancements

1. **Roles**: Add user's roles (derived from ACEs)
   ```json
   "roles": ["User", "Auditor"]
   ```

2. **Effective Privileges**: Consolidated privilege list
   ```json
   "privileges": ["Project.Audit", "Node.Create"]
   ```

3. **Resource Counts**: Summary of accessible resources
   ```json
   "resources_summary": {
     "projects_count": 5,
     "templates_count": 3
   }
   ```

---

## Code Changes Checklist

| File | Change Type | Description |
|------|-------------|-------------|
| `gns3server/schemas/controller/users.py` | Modify | Add UserGroup, ResourcePoolInfo, ACEInfo schemas; Update User schema |
| `gns3server/db/repositories/users.py` | Modify | Add `get_user_with_details` method |
| `gns3server/api/routes/controller/users.py` | Modify | Update `/me` endpoint to use new method |

---

**Document Version**: 1.0
**Last Updated**: 2026-03-06
