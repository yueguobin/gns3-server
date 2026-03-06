# GNS3 RBAC + ACL 权限系统实现说明

**文档版本**: 1.0
**创建日期**: 2026-03-06
**适用版本**: GNS3 Server v3.0+

---

## 目录

- [系统概述](#系统概述)
- [核心概念](#核心概念)
- [数据模型](#数据模型)
- [权限检查流程](#权限检查流程)
- [使用示例](#使用示例)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

---

## 系统概述

GNS3 Server 实现了一个**两层权限控制系统**，结合了 **RBAC**（基于角色的访问控制）和 **ACL**（访问控制列表）的特性：

```
┌─────────────────────────────────────────────────────┐
│  第 1 层：RBAC (定义能力)                            │
│                                                     │
│  角色 → 权限                                         │
│  回答问题："用户能做什么操作？"                        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  第 2 层：ACL (明确授权)                              │
│                                                     │
│  默认：拒绝所有 (Deny All)                            │
│  除非：ACE 明确允许 (Explicitly Allow)                │
│  回答问题："能在哪些资源上使用这些操作？"               │
└─────────────────────────────────────────────────────┘
```

### 核心原则

**默认拒绝，明确允许**

就像网络设备的 ACL，默认情况下拒绝所有访问请求，除非有明确的 ACE（访问控制条目）允许。

```
没有 ACE → ❌ 拒绝访问
有 ACE (allowed=False) → ❌ 拒绝访问
有 ACE (allowed=True) → ✅ 允许访问
```

---

## 核心概念

### 1. 权限 (Privilege)

权限定义了用户可以执行的操作。

```python
权限命名格式: <资源>.<操作>

示例:
- Project.Audit    # 查看项目
- Project.Allocate  # 创建/删除项目
- Project.Modify    # 修改项目
- Node.Console      # 访问节点控制台
- Link.Capture      # 捕获链路流量
```

**预定义权限**: 38 个内置权限（详见 `gns3server/db/models/privileges.py`）

### 2. 角色 (Role)

角色是权限的集合，用于简化权限管理。

```python
内置角色:
- Administrator: 所有权限
- User: 项目、节点、链路、快照等常用权限
- Auditor: 只读权限 (*.Audit)
- Template manager: 模板和符号管理
- User manager: 用户和组管理
- ACL manager: 角色和 ACE 管理
- No Access: 无任何权限
```

### 3. 用户组 (User Group)

用户组用于批量管理用户。

```python
内置组:
- Administrators: 管理员组
- Users: 普通用户组
```

### 4. ACE (Access Control Entry)

ACE 是访问控制的核心，定义了**在哪些资源上可以使用哪些角色**。

```python
ACE 结构:
{
    "path": "/projects",           # 资源路径
    "user_id": "uuid",             # 用户 ID (与 group_id 二选一)
    "group_id": "uuid",            # 用户组 ID (与 user_id 二选一)
    "role_id": "uuid",             # 角色 ID
    "allowed": true,               # 是否允许 (默认 true)
    "propagate": true,             # 是否传播到子路径 (默认 true)
    "ace_type": "user"             # "user" 或 "group"
}
```

**重要**:
- `path`: 使用文件系统风格的路径，如 `/projects`、`/projects/123`
- `role_id`: ACE 关联的角色，角色定义了可用权限
- `allowed`: 显式允许或拒绝（默认 true）
- `propagate`: 权限是否继承到子路径（默认 true）

---

## 数据模型

### 实体关系

```
User ────< UserGroup > (many-to-many via user_group_map)
  │           │
  │           └───< ACE (group_id)
  │
  └───< ACE (user_id)
              │
              ├── path (资源路径)
              ├── role → Role → Privilege (权限)
              ├── allowed (允许/拒绝)
              └── propagate (是否传播)
```

### 数据库表

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `users` | 用户 | `user_id`, `username`, `is_superadmin` |
| `user_groups` | 用户组 | `user_group_id`, `name` |
| `roles` | 角色 | `role_id`, `name`, `is_builtin` |
| `privileges` | 权限 | `privilege_id`, `name` |
| `acl` (ACE) | 访问控制条目 | `ace_id`, `path`, `user_id`, `group_id`, `role_id`, `allowed`, `propagate` |
| `privilege_role_map` | 角色-权限关联 | `privilege_id`, `role_id` |
| `user_group_map` | 用户-组关联 | `user_id`, `user_group_id` |

---

## 权限检查流程

### 完整流程图

```
用户请求: GET /projects/123，需要 Project.Audit 权限
    ↓
┌─────────────────────────────────────────────────────┐
│ 1. 提取请求信息                                      │
│    - 用户 ID                                         │
│    - 路径: /projects/123                             │
│    - 所需权限: Project.Audit                         │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 2. 特殊检查: Superadmin                              │
│    如果 is_superadmin = True                         │
│    → ✅ 直接允许（绕过 RBAC + ACL）                  │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 3. 查询用户 ACE                                      │
│    SELECT * FROM ace                                │
│    JOIN privilege_role_map ON ace.role_id = ...     │
│    JOIN privileges ON ...                           │
│    WHERE                                             │
│      ace.user_id = <user_id>                        │
│      AND privileges.name = 'Project.Audit'          │
│      AND ace.path 匹配 /projects/123                │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 4. 检查用户 ACE                                      │
│    如果找到匹配的 ACE:                               │
│      - if allowed = False → ❌ 拒绝                  │
│      - if allowed = True  → ✅ 允许                  │
│    如果没找到:                                       │
│      → 继续检查组 ACE                                │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 5. 查询组 ACE                                        │
│    查询用户所属的所有组的 ACE                        │
│    （查询逻辑与用户 ACE 相同）                        │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│ 6. 检查组 ACE                                        │
│    如果找到匹配的组 ACE:                             │
│      - if allowed = False → ❌ 拒绝                  │
│      - if allowed = True  → ✅ 允许                  │
│    如果没找到:                                       │
│      → ❌ 拒绝访问（默认拒绝所有）                    │
└─────────────────────────────────────────────────────┘
```

### 路径匹配规则

路径匹配遵循**从具体到通用**的原则：

```
请求路径: /projects/123/nodes/456

检查顺序:
1. /projects/123/nodes/456  (最具体)
2. /projects/123/nodes
3. /projects/123
4. /projects
5. /  (最通用)
```

**propagate 参数的影响**:

```python
# ACE 1: path="/projects", propagate=True
✅ 允许访问: /projects, /projects/123, /projects/123/nodes
# 权限传播到所有子路径

# ACE 2: path="/projects", propagate=False
✅ 允许访问: /projects
❌ 拒绝访问: /projects/123, /projects/123/nodes
# 权限不传播，只允许精确匹配
```

---

## 使用示例

### 场景 1: 允许用户访问所有项目

```python
# 创建 ACE
POST /v3/access/aces
{
    "path": "/projects",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# 结果: 用户可以访问所有项目 (/projects/*)
```

### 场景 2: 允许用户只访问特定项目

```python
# 创建 ACE（精确路径）
POST /v3/access/aces
{
    "path": "/projects/my-project-id",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": false
}

# 结果: 用户只能访问 /projects/my-project-id
#       不能访问其他项目
```

### 场景 3: 使用组权限

```python
# 为组创建 ACE
POST /v3/access/aces
{
    "path": "/projects",
    "group_id": "<Users group_id>",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# 结果: "Users" 组的所有成员都可以访问所有项目
```

### 场景 4: 显式拒绝特定资源

```python
# 用户可以访问所有项目
ACE: path="/projects", user=A, allowed=true, propagate=true

# 但拒绝访问某个秘密项目
ACE: path="/projects/secret", user=A, allowed=false

# 结果: 用户可以访问所有项目，除了 /projects/secret
```

### 场景 5: 使用资源池

```python
# 为用户分配资源池访问权限
POST /v3/access/aces
{
    "path": "/pools/pool-123",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "role_id": "<User role_id>",
    "allowed": true,
    "propagate": true
}

# 结果: 用户可以访问 pool-123 中的所有资源
```

---

## 最佳实践

### 1. 使用组管理权限（推荐）

**推荐** ✅:
```python
# 为 "Users" 组创建 ACE
ACE(path="/projects", group="Users", role="User", allowed=true)
```

**不推荐** ❌:
```python
# 为每个用户单独创建 ACE
ACE(path="/projects", user="user1", role="User", allowed=true)
ACE(path="/projects", user="user2", role="User", allowed=true)
ACE(path="/projects", user="user3", role="User", allowed=true)
# ... 为数百个用户重复
```

### 2. 使用 propagate 减少配置

**推荐** ✅:
```python
# 使用 propagate=True
ACE(path="/projects", group="Users", role="User", allowed=true, propagate=true)
# 一个 ACE 覆盖所有项目和子资源
```

**不推荐** ❌:
```python
# 为每个项目单独创建 ACE
ACE(path="/projects/1", group="Users", role="User", allowed=true)
ACE(path="/projects/2", group="Users", role="User", allowed=true)
ACE(path="/projects/3", group="Users", role="User", allowed=true)
# ... 难以维护
```

### 3. 使用默认 ACE

**问题**: 新安装的系统，默认没有任何 ACE，用户无法访问任何资源。

**解决方案**: 为默认用户组创建默认 ACE

```python
# 初始化脚本
async def create_default_aces():
    users_group = await get_group_by_name("Users")
    user_role = await get_role_by_name("User")

    # 为 "Users" 组创建默认 ACE
    await create_ace({
        "path": "/",
        "group_id": users_group.id,
        "role_id": user_role.id,
        "allowed": true,
        "propagate": true
    })
```

### 4. 审计权限配置

定期检查 ACE 配置：

```python
# 查询所有 ACE
GET /v3/access/aces

# 检查用户的实际权限
GET /v3/access/users/me
# 返回用户所属组、可访问池、ACE 列表
```

---

## 常见问题

### Q1: 为什么用户有角色权限，但无法访问资源？

**A**: 这是最常见的问题。RBAC 定义了"能做什么"，但 ACL 限定了"能在哪里做"。

**检查清单**:
1. 用户是否有匹配的 ACE？
2. ACE 的 `path` 是否匹配请求路径？
3. ACE 的 `allowed` 是否为 `true`？
4. ACE 关联的 `role` 是否有所需权限？

```bash
# 检查用户的 ACE
curl -X GET http://localhost:3080/v3/access/aces \
  -H "Authorization: Bearer <token>"

# 检查用户的组
curl -X GET http://localhost:3080/v3/access/users/me \
  -H "Authorization: Bearer <token>"
```

### Q2: propagate 参数有什么用？

**A**: `propagate` 控制权限是否继承到子路径。

- `propagate=true`: 权限传播到所有子路径
- `propagate=false`: 权限只应用于精确路径

```
ACE: path="/projects", propagate=true
→ 允许: /projects, /projects/1, /projects/1/nodes, ...

ACE: path="/projects", propagate=false
→ 允许: /projects
→ 拒绝: /projects/1, /projects/1/nodes, ...
```

### Q3: 用户 ACE 和组 ACE 的优先级？

**A**: 用户 ACE 优先于组 ACE。

```python
# 用户 ACE
ACE(path="/projects", user=A, role=Auditor, allowed=true)

# 组 ACE（同一用户的组）
ACE(path="/projects", group=Users, role=User, allowed=true)

# 结果: 用户 ACE 优先，用户使用 Auditor 角色
```

### Q4: 如何拒绝访问特定资源？

**A**: 创建 `allowed=false` 的 ACE。

```python
# 用户可以访问所有项目
ACE(path="/projects", user=A, role=User, allowed=true, propagate=true)

# 但拒绝访问秘密项目
ACE(path="/projects/secret", user=A, role=User, allowed=false)
```

**注意**: 拒绝 ACE 的路径必须更具体（更长的路径）。

### Q5: Superadmin 是否受 RBAC + ACL 限制？

**A**: 不受限制。`is_superadmin=true` 的用户绕过所有权限检查。

```python
# Superadmin
{
    "username": "admin",
    "is_superadmin": true
}

# 访问任何资源都不需要 ACE
```

### Q6: 资源池的路径格式是什么？

**A**: 资源池使用 `/pools/{pool_id}` 格式。

```python
# 为用户分配资源池访问权限
ACE(path="/pools/pool-123", user=A, role=User, allowed=true)

# 池中的项目路径
# /pools/pool-123/projects/project-1
```

**注意**: 代码中有 `/pool` 和 `/pools` 的不一致问题，建议使用 `/pools`（复数形式）。

### Q7: 如何调试权限问题？

**A**: 启用调试日志并检查权限检查流程。

```python
# 启用调试日志
import logging
logging.getLogger("gns3server.db.repositories.rbac").setLevel(logging.DEBUG)

# 查看日志
# DEBUG:gns3server.db.repositories.rbac:Checking user admin has privilege Project.Audit on '/projects/123'
```

---

## API 参考

### 权限检查相关的 API 端点

| 端点 | 方法 | 说明 | 所需权限 |
|------|------|------|----------|
| `/v3/access/users/me` | GET | 获取当前用户信息（包含组、池、ACE） | 无（认证用户） |
| `/v3/access/users` | GET | 获取所有用户 | User.Audit |
| `/v3/access/users/{user_id}` | GET | 获取指定用户 | User.Audit |
| `/v3/access/groups` | GET | 获取所有组 | Group.Audit |
| `/v3/access/roles` | GET | 获取所有角色 | Role.Audit |
| `/v3/access/privileges` | GET | 获取所有权限 | Role.Audit |
| `/v3/access/aces` | GET | 获取所有 ACE | ACE.Audit |
| `/v3/access/aces` | POST | 创建 ACE | ACE.Allocate |
| `/v3/access/aces/{ace_id}` | PUT | 更新 ACE | ACE.Modify |
| `/v3/access/aces/{ace_id}` | DELETE | 删除 ACE | ACE.Allocate |

---

## 代码位置参考

| 组件 | 文件路径 |
|------|----------|
| 数据模型 | `gns3server/db/models/` |
| - 用户和组 | `users.py` |
| - 角色和权限 | `roles.py`, `privileges.py` |
| - ACE | `acl.py` |
| RBAC 仓库 | `gns3server/db/repositories/rbac.py` |
| 权限检查依赖 | `gns3server/api/routes/controller/dependencies/rbac.py` |
| API 路由 | `gns3server/api/routes/controller/` |
| - 用户路由 | `users.py` |
| - RBAC 路由 | `roles.py`, `acl.py` |
| Schemas | `gns3server/schemas/controller/rbac.py` |

---

## 总结

GNS3 的 RBAC + ACL 系统是一个强大且灵活的权限控制框架：

### 关键要点

1. **两层防护**: RBAC 定义能力，ACL 限定范围
2. **默认拒绝**: 没有 ACE = 拒绝访问
3. **明确允许**: 必须有 ACE（allowed=true）才能访问
4. **角色优先**: ACE 通过角色授予权限
5. **路径继承**: propagate 控制权限传播

### 设计优势

- ✅ 细粒度控制：精确到具体资源的权限
- ✅ 灵活性强：支持用户和组级别的权限
- ✅ 集中管理：通过角色集中定义权限
- ✅ 安全性高：默认拒绝所有，显式允许

### 注意事项

- ⚠️ 新系统需要创建默认 ACE
- ⚠️ 必须为每个用户/组配置 ACE
- ⚠️ 定期审计权限配置
- ⚠️ Superadmin 绕过所有限制

---

**文档版本**: 1.0
**最后更新**: 2026-03-06
