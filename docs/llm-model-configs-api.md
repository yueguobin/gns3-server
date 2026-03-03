# LLM Model Configurations API

## Overview

This API provides LLM model configuration management for users and user groups with inheritance support.

### Key Features

- **User-level configurations**: Each user can have their own LLM model configurations
- **Group-level configurations**: User groups can share LLM model configurations
- **Inheritance**: Users automatically inherit configurations from their groups (when they have no own configs)
- **Default configuration**: Both users and groups can set a default configuration
- **API Key Encryption**: API keys are automatically encrypted in the database

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
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

### Constraints

- Each config belongs to **either** a user **or** a group (not both)
- Each user can have **at most one** default configuration
- Each group can have **at most one** default configuration

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

All fields are optional. Only provided fields will be updated.

### LLMModelConfigResponse

| Field | Type | Description |
|-------|------|-------------|
| `config_id` | UUID | Configuration ID |
| `config` | LLMModelConfigData | Configuration data |
| `user_id` | UUID (nullable) | Owner user ID |
| `group_id` | UUID (nullable) | Owner group ID |
| `is_default` | boolean | Default flag |
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

### 4. Update a configuration

```bash
curl -X PUT http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/{config_id} \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "temperature": 0.9,
    "max_tokens": 4000
  }'
```

### 5. Set default configuration

```bash
curl -X PUT http://localhost:3080/v3/access/users/{user_id}/llm-model-configs/default/{config_id} \
  -H "Authorization: Bearer <token>"
```

### 6. Delete a configuration

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
| 500 | Server error |

---

## Security Notes

1. **API Key Encryption**: All API keys are encrypted using Fernet symmetric encryption (AES-128-CBC)
2. **Access Control**: All endpoints require appropriate privileges (User.Audit, User.Modify, Group.Audit, Group.Modify)
3. **User Isolation**: Users can only access their own configurations
4. **Group Access**: Group configurations can only be modified by users with Group.Modify privilege

---

## Migration from Old User Settings API

The old user settings API (`/v3/access/users/{user_id}/profiles`) stored configurations in the `users.model_configs` JSON column. This new API uses a dedicated table with better inheritance support.

**Migration strategy:**
1. Run the database migration to create the `llm_model_configs` table
2. Optionally migrate existing data from `users.model_configs` to the new table
3. Update clients to use the new API endpoints
4. Deprecate the old `/profiles` endpoints
