# LLM Model Configurations API

## Overview

This API provides LLM model configuration management for users and user groups with inheritance support.

### Key Features

- **User-level configurations**: Each user can have their own LLM model configurations
- **Group-level configurations**: User groups can share LLM model configurations
- **Inheritance**: Users automatically inherit configurations from their groups (when they have no own configs)
- **Default configuration**: Both users and groups can set a default configuration
- **API Key Encryption**: API keys are automatically encrypted in the database
- **Optimistic Locking**: Prevents concurrent modification conflicts using version tracking

### Inheritance Logic

```
User requests configs:
  ├─ If user has own configs → return user's configs
  └─ If user has NO configs → return inherited group configs
```

### Configuration Priority

```
User's own config > User's group config
```

---

## Database Schema

### Table: `llm_model_configs`

| Column | Type | Description |
|--------|------|-------------|
| `config_id` | UUID | Primary key |
| `config` | JSONB | Configuration data (name, provider, model, etc.) |
| `user_id` | UUID (nullable) | Foreign key to users table |
| `group_id` | UUID (nullable) | Foreign key to user_groups table |
| `is_default` | BOOLEAN | Default configuration flag |
| `version` | INTEGER | Optimistic locking version (starts at 0, increments on each update) |
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

### Constraints

- Each config belongs to **either** a user **or** a group (not both)
- Each user can have **at most one** default configuration
- Each group can have **at most one** default configuration
- `version` field is automatically incremented on each update

---

## API Endpoints

### User Configuration Endpoints

| Method | Path | Description | Privilege |
|--------|------|-------------|-----------|
| GET | `/v3/access/users/{user_id}/llm-model-configs` | Get user's effective configs (own + inherited) | User.Audit |
| GET | `/v3/access/users/{user_id}/llm-model-configs/own` | Get user's own configs only | User.Audit |
| POST | `/v3/access/users/{user_id}/llm-model-configs` | Create a new configuration | User.Modify |
| PUT | `/v3/access/users/{user_id}/llm-model-configs/{config_id}` | Update a configuration | User.Modify |
| DELETE | `/v3/access/users/{user_id}/llm-model-configs/{config_id}` | Delete a configuration | User.Modify |
| PUT | `/v3/access/users/{user_id}/llm-model-configs/default/{config_id}` | Set default configuration | User.Modify |

### Group Configuration Endpoints

| Method | Path | Description | Privilege |
|--------|------|-------------|-----------|
| GET | `/v3/access/groups/{group_id}/llm-model-configs` | Get all group configurations | Group.Audit |
| POST | `/v3/access/groups/{group_id}/llm-model-configs` | Create a new configuration | Group.Modify |
| PUT | `/v3/access/groups/{group_id}/llm-model-configs/{config_id}` | Update a configuration | Group.Modify |
| DELETE | `/v3/access/groups/{group_id}/llm-model-configs/{config_id}` | Delete a configuration | Group.Modify |
| PUT | `/v3/access/groups/{group_id}/llm-model-configs/default/{config_id}` | Set default configuration | Group.Modify |

---

## Request/Response Schemas

### LLMModelConfigCreate

**Required Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Configuration name (1-100 chars) |
| `provider` | string | LLM provider (e.g., "openai", "anthropic", "ollama") |
| `base_url` | string | API base URL |
| `model` | string | Model name |
| `temperature` | float | Temperature (0.0-2.0, default: 0.7) |

**Optional Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | string | API key (auto-encrypted) |
| `max_tokens` | integer | Max tokens for generation |
| `is_default` | boolean | Set as default (default: false) |

**Extra Fields:** Any custom fields are supported for future extensibility.

### LLMModelConfigUpdate

| Field | Type | Description |
|-------|------|-------------|
| `name` | string (optional) | Configuration name |
| `provider` | string (optional) | LLM provider |
| `base_url` | string (optional) | API base URL |
| `model` | string (optional) | Model name |
| `temperature` | float (optional) | Temperature |
| `api_key` | string (optional) | API key |
| `max_tokens` | integer (optional) | Max tokens |
| `is_default` | boolean (optional) | Default flag |
| `expected_version` | integer (optional) | **Optimistic locking version** |

**Note:** When using `expected_version`, the API will verify the version hasn't changed since you read the data. If it has, you'll receive a 409 Conflict error.

### LLMModelConfigResponse

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | UUID | Configuration ID |
| `config` | LLMModelConfigData | Configuration data |
| `user_id` | UUID (nullable) | Owner user ID |
| `group_id` | UUID (nullable) | Owner group ID |
| `is_default` | boolean | Default flag |
| `version` | integer | **Current version number** (for optimistic locking) |
| `created_at` | TIMESTAMP | Creation time |
| `updated_at` | TIMESTAMP | Last update time |

### LLMModelConfigInheritedResponse

| Field | Type | Description |
|-------|------|-------------|
| `configs` | list[LLMModelConfigWithSource] | Effective configurations |
| `default_config` | LLMModelConfigWithSource (nullable) | Default configuration |
| `total` | integer | Total count |

---

## Usage Examples

### 1. Create a user configuration

```bash
curl -X POST http://localhost:3080/v3/access/users/{user_id}/llm-model-configs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GPT-4",
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4",
    "temperature": 0.7,
    "api_key": "sk-xxx",
    "is_default": true
  }'
```

**Response:**
```json
{
  "config_id": "uuid-1",
  "config": {
    "name": "GPT-4",
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4",
    "temperature": 0.7,
    "api_key": "sk-xxx"
  },
  "user_id": "uuid-user",
  "group_id": null,
  "is_default": true,
  "version": 0,
  "created_at": "2026-03-03T12:00:00Z",
  "updated_at": "2026-03-03T12:00:00Z"
}
```

### 2. Create a group configuration

```bash
curl -X POST http://localhost:3080/v3/access/groups/{group_id}/llm-model-configs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Claude-3",
    "provider": "anthropic",
    "base_url": "https://api.anthropic.com",
    "model": "claude-3-opus-20240229",
    "temperature": 0.7,
    "api_key": "sk-ant-xxx",
    "is_default": true
  }'
```

### 3. Get user's effective configurations (with inheritance)

```bash
curl -X GET http://localhost:3080/v3/access/users/{user_id}/llm-model-configs \
  -H "Authorization: Bearer <token>"
```

**Response (user has own configs):**
```json
{
  "configs": [
    {
      "config_id": "uuid-1",
      "source": "user",
      "group_name": null,
      "is_default": true,
      "name": "GPT-4",
      "provider": "openai",
      "model": "gpt-4",
      "base_url": "https://api.openai.com/v1",
      "temperature": 0.7,
      "api_key": "sk-xxx"
    }
  ],
  "default_config": {
    "config_id": "uuid-1",
    "source": "user",
    "group_name": null,
    "is_default": true,
    "name": "GPT-4",
    ...
  },
  "total": 1
}
```

**Response (user inherits from group):**
```json
{
  "configs": [
    {
      "config_id": "uuid-2",
      "source": "group",
      "group_name": "Developers",
      "is_default": true,
      "name": "Claude-3",
      "provider": "anthropic",
      "model": "claude-3-opus-20240229",
      "base_url": "https://api.anthropic.com",
      "temperature": 0.7,
      "api_key": "sk-ant-xxx"
    }
  ],
  "default_config": {
    "config_id": "uuid-2",
    "source": "group",
    "group_name": "Developers",
    "is_default": true,
    ...
  },
  "total": 1
}
```

### 4. Update a configuration (without optimistic locking)

```bash
curl -X PUT http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/{config_id} \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "temperature": 0.9,
    "max_tokens": 4000
  }'
```

### 5. Update a configuration (WITH optimistic locking)

**Best practice for avoiding concurrent modification conflicts:**

```bash
# Step 1: Read the config (get the current version)
curl -X GET http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/own \
  -H "Authorization: Bearer <token>"

# Response includes "version": 5

# Step 2: Update with expected_version
curl -X PUT http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/{config_id} \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "temperature": 0.9,
    "max_tokens": 4000,
    "expected_version": 5
  }'

# Response includes incremented "version": 6
```

**If someone else modified the config before you:**

```json
HTTP 409 Conflict
{
  "detail": "Concurrent modification detected. Expected version 5, but current version is 6. Please retry."
}
```

**Client retry flow:**
1. Receive 409 Conflict error
2. Re-fetch the config to get the latest version
3. Apply your changes on top of the latest data
4. Retry the update with the new `expected_version`

### 6. Set default configuration

```bash
curl -X PUT http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/default/{config_id} \
  -H "Authorization: Bearer <token>"
```

### 7. Delete a configuration

```bash
curl -X DELETE http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/{config_id} \
  -H "Authorization: Bearer <token>"
```

---

## Error Codes

| Status | Description |
|--------|-------------|
| 200 | Success |
| 201 | Created |
| 204 | Deleted (no content) |
| 400 | Bad request |
| 401 | Unauthorized |
| 404 | Not found |
| **409** | **Conflict (optimistic lock violation)** |
| 500 | Server error |

### 409 Conflict Response

```json
{
  "detail": "Concurrent modification detected. Expected version 5, but current version is 6. Please retry."
}
```

---

## Concurrency Control

### Optimistic Locking

This API uses **optimistic locking** to prevent concurrent modification conflicts:

1. **Version Tracking**: Each configuration has a `version` field that starts at 0 and increments on each update
2. **Read-Modify-Write**: When updating, clients should include the `expected_version` from their last read
3. **Conflict Detection**: If the provided version doesn't match the current version, the update is rejected with HTTP 409

### When to Use Optimistic Locking

**Use `expected_version` when:**
- Multiple users/admins might modify the same configuration
- You want to prevent accidental overwrites of concurrent changes
- Building interactive UIs that display and edit configurations

**Skip `expected_version` when:**
- You're sure no one else is modifying the config
- Performance is more important than data integrity (not recommended)

### Example Workflow

```python
# Client-side example (Python)
import requests

def update_config_safely(config_id, updates):
    max_retries = 3
    for attempt in range(max_retries):
        # 1. Fetch current config
        response = requests.get(
            f"/users/{user_id}/llm-model-configs/own",
            headers={"Authorization": f"Bearer {token}"}
        )
        configs = response.json()
        config = next(c for c in configs if c["config_id"] == config_id)
        current_version = config["version"]

        # 2. Try update with expected_version
        try:
            response = requests.put(
                f"/users/{user_id}/llm-model-configs/{config_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    **updates,
                    "expected_version": current_version
                }
            )
            response.raise_for_status()
            return response.json()  # Success

        except requests.HTTPError as e:
            if e.response.status_code == 409:
                # Conflict: someone else modified it
                if attempt < max_retries - 1:
                    continue  # Retry
                raise Exception("Max retries exceeded for concurrent update")
            raise
```

---

## Security Notes

1. **API Key Encryption**: All API keys are encrypted using Fernet symmetric encryption (AES-128-CBC)
2. **Access Control**: All endpoints require appropriate privileges (User.Audit, User.Modify, Group.Audit, Group.Modify)
3. **User Isolation**: Users can only access their own configurations
4. **Group Access**: Group configurations can only be modified by users with Group.Modify privilege
5. **Encryption Key Storage**: Encryption keys are stored in `{secrets_dir}/gns3_encryption_key` with 0600 permissions

---

## Migration from Old User Settings API

The old user settings API (`/v3/access/users/{user_id}/profiles`) stored configurations in the `users.model_configs` JSON column. This new API uses a dedicated table with better inheritance support and optimistic locking.

**Migration strategy:**
1. Run the database migration to create the `llm_model_configs` table
2. Optionally migrate existing data from `users.model_configs` to the new table
3. Update clients to use the new API endpoints
4. Update clients to handle `version` field and 409 Conflict errors
5. Deprecate the old `/profiles` endpoints

**Key differences:**
- **Inheritance**: Users without configs inherit from groups (automatic fallback)
- **Optimistic locking**: New `version` field and `expected_version` parameter
- **Dedicated table**: Better query performance and data integrity
- **Transparent encryption**: API keys auto-encrypted/decrypted by the API
