# GNS3 RBAC + ACL Permission System Implementation Guide

**Document Version**: 1.0
**Created**: 2026-03-06
**Applicable Version**: GNS3 Server v3.0+

---

## Table of Contents

- [System Overview](#system-overview)
- [Core Concepts](#core-concepts)
- [Data Model](#data-model)
- [Permission Check Flow](#permission-check-flow)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)
- [Common Issues](#common-issues)

---

## System Overview

GNS3 Server implements a **two-tier permission control system** that combines **RBAC** (Role-Based Access Control) and **ACL** (Access Control List) features:

```
┌─────────────────────────────────────────────────────┐
│  Tier 1: RBAC (Define Capabilities)                 │
│                                                     │
│  Role → Privilege                                   │
│  Answers: "What operations can a user perform?"     │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Tier 2: ACL (Explicit Authorization)               │
│                                                     │
│  Default: Deny All                                  │
│  Unless: ACE Explicitly Allows                      │
│  Answers: "On which resources can these operations be used?" │
└─────────────────────────────────────────────────────┘
```

### Core Principle

**Default Deny, Explicit Allow**

Like network device ACLs, all access requests are denied by default unless explicitly allowed by an ACE (Access Control Entry).

```
No ACE → ❌ Access Denied
ACE with allowed=False → ❌ Access Denied
ACE with allowed=True → ✅ Access Allowed
```

---

## Core Concepts

### 1. Privilege

Privileges define the operations a user can perform.

```python
Privilege Naming Format: <Resource>.<Action>

Examples:
- Project.Audit    # View projects
- Project.Allocate  # Create/delete projects
- Project.Modify    # Modify projects
- Node.Console      # Access node console
- Link.Capture      # Capture link traffic
```

**Predefined Privileges**: 38 built-in privileges (see `gns3server/db/models/privileges.py`)

### 2. Role

Roles are collections of privileges that simplify permission management.

```python
Built-in Roles:
- Administrator: All privileges
- User: Common privileges for projects, nodes, links, snapshots, etc.
- Auditor: Read-only privileges (*.Audit)
- Template manager: Template and symbol management
- User manager: User and group management
- ACL manager: Role and ACE management
- No Access: No privileges
```

### 3. User Group

User groups are used to batch-manage users.

```python
Built-in Groups:
- Administrators: Administrator group
- Users: Regular user group
```

### 4. ACE (Access Control Entry)

ACEs are the core of access control, defining **on which resources which roles can be used**.

```python
ACE Structure:
{
    "path": "/projects",           # Resource path
    "user_id": "uuid",             # User ID (choose one with group_id)
    "group_id": "uuid",            # User group ID (choose one with user_id)
    "role_id": "uuid",             # Role ID
    "allowed": true,               # Whether to allow (default true)
    "propagate": true,             # Whether to propagate to child paths (default true)
    "ace_type": "user"             # "user" or "group"
}
```

**Important**:
- `path`: File system-style paths like `/projects`, `/projects/123`
- `role_id`: The role associated with the ACE, which defines available privileges
- `allowed`: Explicit allow or deny (default true)
- `propagate`: Whether permissions are inherited by child paths (default true)

---

## Data Model

### Entity Relationships

```
User ────< UserGroup > (many-to-many via user_group_map)
  │           │
  │           └───< ACE (group_id)
  │
  └───< ACE (user_id)
              │
              ├── path (resource path)
              ├── role → Role → Privilege (privilege)
              ├── allowed (allow/deny)
              └── propagate (whether to propagate)
```

### Database Tables

| Table | Description | Key Fields |
|-------|-------------|------------|
| `users` | Users | `user_id`, `username`, `is_superadmin` |
| `user_groups` | User groups | `user_group_id`, `name` |
| `roles` | Roles | `role_id`, `name`, `is_builtin` |
| `privileges` | Privileges | `privilege_id`, `name` |
| `acl` (ACE) | Access Control Entries | `ace_id`, `path`, `user_id`, `group_id`, `role_id`, `allowed`, `propagate` |
| `privilege_role_map` | Role-privilege association | `privilege_id`, `role_id` |
| `user_group_map` | User-group association | `user_id`, `user_group_id` |

---

## Permission Check Flow

### Complete Flowchart

```
User Request: GET /projects/123, requires Project.Audit privilege
    ↓
┌─────────────────────────────────────────────────────┐
│ 1. Extract Request Information                      │
│    - User ID                                         │
│    - Path: /projects/123                             │
│    - Required privilege: Project.Audit               │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 2. Special Check: Superadmin                         │
│    If is_superadmin = True                           │
│    → ✅ Allow directly (bypass RBAC + ACL)           │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 3. Query User ACEs                                  │
│    SELECT * FROM ace                                │
│    JOIN privilege_role_map ON ace.role_id = ...     │
│    JOIN privileges ON ...                           │
│    WHERE                                             │
│      ace.user_id = <user_id>                        │
│      AND privileges.name = 'Project.Audit'          │
│      AND ace.path matches /projects/123             │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 4. Check User ACEs                                  │
│    If matching ACE found:                            │
│      - if allowed = False → ❌ Deny                  │
│      - if allowed = True  → ✅ Allow                 │
│    If not found:                                     │
│      → Continue checking group ACEs                  │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 5. Query Group ACEs                                 │
│    Query ACEs for all groups the user belongs to    │
│    (same logic as user ACEs)                         │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 6. Check Group ACEs                                 │
│    If matching group ACE found:                      │
│      - if allowed = False → ❌ Deny                  │
│      - if allowed = True  → ✅ Allow                 │
│    If not found:                                     │
│      → ❌ Access denied (deny by default)            │
└─────────────────────────────────────────────────────┘
```

### Path Matching Rules

Path matching follows the **specific-to-general** principle:

```
Request Path: /projects/123/nodes/456

Check Order:
1. /projects/123/nodes/456  (most specific)
2. /projects/123/nodes
3. /projects/123
4. /projects
5. /  (most general)
```

**Impact of propagate Parameter**:

```python
# ACE 1: path="/projects", propagate=True
✅ Allow: /projects, /projects/123, /projects/123/nodes
# Permission propagates to all child paths

# ACE 2: path="/projects", propagate=False
✅ Allow: /projects
❌ Deny: /projects/123, /projects/123/nodes
# Permission does not propagate, only exact match allowed
```

---

## Usage Examples

### Scenario 1: Allow User to Access All Projects

```python
# Create ACE
POST /v3/access/aces
{
    "path": "/projects",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# Result: User can access all projects (/projects/*)
```

### Scenario 2: Allow User to Access Only Specific Project

```python
# Create ACE (exact path)
POST /v3/access/aces
{
    "path": "/projects/my-project-id",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": false
}

# Result: User can only access /projects/my-project-id
#         Cannot access other projects
```

### Scenario 3: Use Group Permissions

```python
# Create ACE for group
POST /v3/access/aces
{
    "path": "/projects",
    "group_id": "<Users group_id>",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# Result: All members of "Users" group can access all projects
```

### Scenario 4: Explicitly Deny Specific Resource

```python
# User can access all projects
ACE: path="/projects", user=A, allowed=true, propagate=true

# But deny access to a specific secret project
ACE: path="/projects/secret", user=A, allowed=false

# Result: User can access all projects except /projects/secret
```

### Scenario 5: Use Resource Pools

```python
# Grant user access to resource pool
POST /v3/access/aces
{
    "path": "/pools/pool-123",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# Result: User can access all resources in pool-123
```

---

## Best Practices

### 1. Use Groups for Permission Management (Recommended)

**Recommended** ✅:
```python
# Create ACE for "Users" group
ACE(path="/projects", group="Users", role="User", allowed=true)
```

**Not Recommended** ❌:
```python
# Create separate ACE for each user
ACE(path="/projects", user="user1", role="User", allowed=true)
ACE(path="/projects", user="user2", role="User", allowed=true)
ACE(path="/projects", user="user3", role="User", allowed=true)
# ... Repeat for hundreds of users
```

### 2. Use propagate to Reduce Configuration

**Recommended** ✅:
```python
# Use propagate=True
ACE(path="/projects", group="Users", role="User", allowed=true, propagate=true)
# One ACE covers all projects and sub-resources
```

**Not Recommended** ❌:
```python
# Create separate ACE for each project
ACE(path="/projects/1", group="Users", role="User", allowed=true)
ACE(path="/projects/2", group="Users", role="User", allowed=true)
ACE(path="/projects/3", group="Users", role="User", allowed=true)
# ... Difficult to maintain
```

### 3. Use Default ACEs

**Problem**: Fresh system install has no ACEs by default, users cannot access any resources.

**Solution**: Create default ACEs for default user groups

```python
# Initialization script
async def create_default_aces():
    users_group = await get_group_by_name("Users")
    user_role = await get_role_by_name("User")

    # Create default ACE for "Users" group
    await create_ace({
        "path": "/",
        "group_id": users_group.id,
        "role_id": user_role.id,
        "allowed": true,
        "propagate": true
    })
```

### 4. Audit Permission Configuration

Regularly check ACE configuration:

```python
# Query all ACEs
GET /v3/access/aces

# Check user's actual permissions
GET /v3/access/users/me
# Returns user's groups, accessible pools, ACE list
```

---

## Common Issues

### Q1: Why can't a user access resources even with role privileges?

**A**: This is the most common issue. RBAC defines "what can be done," but ACL limits "where it can be done."

**Checklist**:
1. Does the user have a matching ACE?
2. Does the ACE `path` match the request path?
3. Is the ACE `allowed` set to `true`?
4. Does the associated `role` have the required privilege?

```bash
# Check user's ACEs
curl -X GET http://localhost:3080/v3/access/aces \
  -H "Authorization: Bearer <token>"

# Check user's groups
curl -X GET http://localhost:3080/v3/access/users/me \
  -H "Authorization: Bearer <token>"
```

### Q2: What is the purpose of the propagate parameter?

**A**: `propagate` controls whether permissions are inherited by child paths.

- `propagate=true`: Permission propagates to all child paths
- `propagate=false`: Permission applies only to the exact path

```
ACE: path="/projects", propagate=true
→ Allow: /projects, /projects/1, /projects/1/nodes, ...

ACE: path="/projects", propagate=false
→ Allow: /projects
→ Deny: /projects/1, /projects/1/nodes, ...
```

### Q3: What is the priority of user ACEs vs group ACEs?

**A**: User ACEs take priority over group ACEs.

```python
# User ACE
ACE(path="/projects", user=A, role=Auditor, allowed=true)

# Group ACE (user's group)
ACE(path="/projects", group=Users, role=User, allowed=true)

# Result: User ACE takes priority, user uses Auditor role
```

### Q4: How to deny access to specific resources?

**A**: Create an ACE with `allowed=false`.

```python
# User can access all projects
ACE(path="/projects", user=A, role=User, allowed=true, propagate=true)

# But deny access to secret project
ACE(path="/projects/secret", user=A, role=User, allowed=false)
```

**Note**: The deny ACE path must be more specific (longer path).

### Q5: Are superadmins subject to RBAC + ACL restrictions?

**A**: No. Users with `is_superadmin=true` bypass all permission checks.

```python
# Superadmin
{
    "username": "admin",
    "is_superadmin": true
}

# No ACE required to access any resource
```

### Q6: What is the path format for resource pools?

**A**: Resource pools use the `/pools/{pool_id}` format.

```python
# Grant user access to resource pool
ACE(path="/pools/pool-123", user=A, role=User, allowed=true)

# Project paths within the pool
# /pools/pool-123/projects/project-1
```

**Note**: There is an inconsistency in the code between `/pool` and `/pools`. Recommendation: use `/pools` (plural form).

### Q7: How to debug permission issues?

**A**: Enable debug logging and check the permission check flow.

```python
# Enable debug logging
import logging
logging.getLogger("gns3server.db.repositories.rbac").setLevel(logging.DEBUG)

# View logs
# DEBUG:gns3server.db.repositories.rbac:Checking user admin has privilege Project.Audit on '/projects/123'
```

---

## API Reference

### Permission Check Related API Endpoints

| Endpoint | Method | Description | Required Privilege |
|----------|--------|-------------|-------------------|
| `/v3/access/users/me` | GET | Get current user info (includes groups, pools, ACEs) | None (authenticated user) |
| `/v3/access/users` | GET | Get all users | User.Audit |
| `/v3/access/users/{user_id}` | GET | Get specific user | User.Audit |
| `/v3/access/groups` | GET | Get all groups | Group.Audit |
| `/v3/access/roles` | GET | Get all roles | Role.Audit |
| `/v3/access/privileges` | GET | Get all privileges | Role.Audit |
| `/v3/access/aces` | GET | Get all ACEs | ACE.Audit |
| `/v3/access/aces` | POST | Create ACE | ACE.Allocate |
| `/v3/access/aces/{ace_id}` | PUT | Update ACE | ACE.Modify |
| `/v3/access/aces/{ace_id}` | DELETE | Delete ACE | ACE.Allocate |

---

## Code Reference

| Component | File Path |
|-----------|-----------|
| Data Models | `gns3server/db/models/` |
| - Users and Groups | `users.py` |
| - Roles and Privileges | `roles.py`, `privileges.py` |
| - ACE | `acl.py` |
| RBAC Repository | `gns3server/db/repositories/rbac.py` |
| Permission Check Dependency | `gns3server/api/routes/controller/dependencies/rbac.py` |
| API Routes | `gns3server/api/routes/controller/` |
| - User Routes | `users.py` |
| - RBAC Routes | `roles.py`, `acl.py` |
| Schemas | `gns3server/schemas/controller/rbac.py` |

---

## Summary

GNS3's RBAC + ACL system is a powerful and flexible permission control framework:

### Key Points

1. **Two-Tier Protection**: RBAC defines capabilities, ACL limits scope
2. **Default Deny**: No ACE means access denied
3. **Explicit Allow**: Must have ACE (allowed=true) to access
4. **Role-Based**: ACEs grant privileges through roles
5. **Path Inheritance**: propagate controls permission propagation

### Design Advantages

- ✅ Fine-grained Control: Precise resource-level permissions
- ✅ Flexibility: Support user and group-level permissions
- ✅ Centralized Management: Define permissions centrally through roles
- ✅ High Security: Deny all by default, explicit allow

### Caveats

- ⚠️ New systems require default ACE creation
- ⚠️ Must configure ACEs for each user/group
- ⚠️ Regularly audit permission configurations
- ⚠️ Superadmin bypasses all restrictions

---

**Document Version**: 1.0
**Last Updated**: 2026-03-06
