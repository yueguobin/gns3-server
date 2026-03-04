# GNS3 Copilot Agent Chat API 设计文档

## 概述

本文档描述 GNS3 Copilot Chat API 的架构设计和实现方案。该 API 使客户端能够通过 RESTful 接口与 GNS3 Copilot Agent 进行交互，提供流式对话、会话管理、项目拓扑查询等功能。

## 核心特性

- **项目级隔离**：每个 GNS3 项目拥有独立的 Agent 实例和会话存储
- **流式响应**：使用 Server-Sent Events (SSE) 实现实时流式输出
- **会话管理**：支持会话列表、重命名、删除、历史记录查询
- **统计追踪**：自动记录消息数量、LLM 调用次数、Token 使用量
- **用户隔离**：每个用户拥有独立的 LLM 配置和会话空间

## 架构设计

### 整体架构

```
Frontend (Web UI)
    │
    │ SSE Streaming
    ▼
FastAPI Chat API Routes
    │
    │ Project-level Agent Management
    ▼
AgentService (per project)
    │
    ├─ SQLite Checkpointer (project_dir/gns3-copilot/)
    │   ├─ checkpoints table (LangGraph state)
    │   └─ chat_sessions table (session metadata)
    │
    └─ LangGraph Agent
        ├─ llm_call node
        ├─ should_continue node
        └─ tool_node (GNS3 tools)
```

### 项目级 Checkpoint 设计

每个 GNS3 项目在项目目录下创建 `gns3-copilot/copilot_checkpoints.db` SQLite 数据库，包含两张表：

1. **checkpoints 表**（LangGraph 自动管理）：存储 Agent 的对话状态和记忆
2. **chat_sessions 表**（自定义）：存储会话元数据和统计信息

**目录结构**：
```
{project.path}/
├── gns3-copilot/
│   └── copilot_checkpoints.db
├── project-files/
└── project.gns3
```

**设计优势**：
- 项目删除时自动清理所有相关数据
- 实现项目级别的会话隔离
- 便于备份和迁移

## 用户认证信息传递

### 背景需求

GNS3 Copilot Agent 需要以下信息才能正常工作：
1. **user_id**：获取用户专属的 LLM 配置
2. **jwt_token**：调用 GNS3 API 时进行身份验证
3. **llm_config**：包含 provider、model、api_key 等配置

### ContextVars 方案

使用 Python 的 `contextvars.ContextVar` 在请求作用域内传递数据，避免敏感信息持久化到 checkpoint。

**数据流**：
```
1. API 层获取用户信息
   ├─ 从 FastAPI get_current_active_user 获取 user_id
   ├─ 从 Authorization header 提取 jwt_token
   └─ 从数据库查询 LLM 配置（已解密 API key）

2. 设置 ContextVars（内存临时存储）
   ├─ set_current_jwt_token(jwt_token)
   └─ set_current_llm_config(llm_config)

3. 构建安全的 LangGraph config（仅包含非敏感标识符）
   {
     "configurable": {
       "thread_id": session_id,
       "project_id": project_id
     },
     "metadata": {
       "user_id": user_id
     }
   }

4. LLM 节点从 ContextVars 获取配置
   ├─ get_current_jwt_token()
   └─ get_current_llm_config()
```

**方案优势**：
- 敏感数据（JWT token、API key）仅存储在内存中
- 请求结束后自动清理，不会持久化到数据库
- 避免序列化/反序列化开销
- 实现请求级别的数据隔离

## 会话管理

### chat_sessions 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键（自增） |
| thread_id | TEXT | LangGraph thread_id（唯一） |
| user_id | TEXT | 用户 ID |
| project_id | TEXT | GNS3 项目 ID |
| title | TEXT | 会话标题 |
| message_count | INTEGER | 消息数量 |
| llm_calls_count | INTEGER | LLM 调用次数 |
| input_tokens | INTEGER | 输入 token 总数 |
| output_tokens | INTEGER | 输出 token 总数 |
| total_tokens | INTEGER | 总 token 数 |
| last_message_at | TIMESTAMP | 最后消息时间 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |
| metadata | TEXT | 预留元数据（JSON） |
| stats | TEXT | 额外统计信息（JSON） |

### ChatSessionsRepository

提供会话的 CRUD 操作：

- **create_session**：创建新会话
- **get_session_by_thread**：根据 thread_id 查询会话
- **list_sessions**：列出用户的会话（支持过滤和分页）
- **update_session**：更新会话（支持增量更新计数器）
- **delete_session**：删除会话及其 checkpoints
- **delete_all_sessions**：删除项目的所有会话

### 统计信息自动收集

在 `stream_chat` 流程中自动追踪：
- 每次用户消息：message_count +1
- 每次 AI 响应：message_count +1
- 每次工具调用：llm_calls_count +1
- LLM 返回的 token 使用量：实时累加

流结束后一次性更新到数据库。

### Title 自动同步

会话标题由 `generate_title` 节点自动生成，保存在 LangGraph checkpoint 的 `conversation_title` 字段中。

**同步机制**：
1. 流式 Chat 完成后，从 checkpoint 读取最终 state
2. 检查 `conversation_title` 是否有变化
3. 如果有变化，更新到 `chat_sessions` 表

**优势**：
- 避免在节点中直接访问数据库（防止循环依赖）
- 所有数据库更新集中在流结束后
- 逻辑清晰，易于维护

## SSE 消息格式

Chat API 使用 Server-Sent Events (SSE) 进行流式传输。

### 消息类型

| type | 说明 | 包含字段 |
|------|------|----------|
| content | AI 文本内容（流式） | content |
| tool_call | 工具调用请求 | tool_call (id, name, arguments) |
| tool_start | 工具开始执行 | tool_name |
| tool_end | 工具执行完成 | tool_name, tool_output |
| error | 错误信息 | error |
| done | 流结束 | session_id |
| heartbeat | 心跳保活 | session_id |

### 消息示例

```json
// AI 文本流式输出
{"type": "content", "content": "Hello! How can I help"}

// 工具调用
{"type": "tool_call", "tool_call": {"id": "call_123", "function": {"name": "GNS3TopologyTool", "arguments": {"project_id": "xxx"}}}}

// 工具开始
{"type": "tool_start", "tool_name": "GNS3TopologyTool", "session_id": "xxx"}

// 工具完成
{"type": "tool_end", "tool_name": "GNS3TopologyTool", "tool_output": "{...}", "session_id": "xxx"}

// 完成
{"type": "done", "session_id": "xxx"}

// 错误
{"type": "error", "error": "Project not found", "session_id": "xxx"}
```

### 心跳机制

**作用**：防止代理服务器/负载均衡器因超时断开 SSE 连接。

**实现**：使用 `asyncio.wait` 设置超时，超时后发送 `heartbeat` 消息，然后继续等待下一个事件。

**前端处理**：收到 `heartbeat` 消息时直接忽略，不渲染任何内容。

## API 端点

所有端点都在 `/v3/projects/{project_id}/chat/` 路径下。

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/stream` | 流式 Chat（主要接口） |
| GET | `/sessions` | 列出会话 |
| GET | `/sessions/{session_id}/history` | 获取会话历史 |
| PATCH | `/sessions/{session_id}` | 重命名会话 |
| DELETE | `/sessions/{session_id}` | 删除会话 |

### POST /v3/projects/{project_id}/chat/stream

**功能**：流式对话接口

**请求参数**：
- message: 用户消息内容
- session_id: 会话 ID（可选，不提供则自动创建新会话）
- stream: 是否启用流式响应（默认 true）
- mode: 交互模式（当前仅支持 "text"）

**响应**：SSE 流，包含多种类型的消息（见上文消息格式）

**项目状态检查**：只允许项目状态为 "opened" 时进行对话

### GET /v3/projects/{project_id}/chat/sessions

**功能**：列出项目的所有会话

**响应**：会话列表，包含统计信息（消息数、token 使用量等）

### GET /v3/projects/{project_id}/chat/sessions/{session_id}/history

**功能**：获取会话的完整历史记录

**参数**：
- session_id: 会话 ID
- limit: 最大消息数量（默认 100）

**响应**：
- thread_id: 会话 ID
- title: 会话标题
- messages: 消息列表（OpenAI 格式）
- llm_calls: LLM 调用次数

### PATCH /v3/projects/{project_id}/chat/sessions/{session_id}

**功能**：重命名会话

**请求参数**：
- title: 新标题（1-255 字符）

**响应**：更新后的会话信息

### DELETE /v3/projects/{project_id}/chat/sessions/{session_id}

**功能**：删除会话及其所有 checkpoint 数据

**响应**：204 No Content

## 数据模型

### ChatRequest

- message: str - 用户消息内容
- session_id: Optional[str] - 会话 ID（可选）
- stream: bool - 是否流式响应（默认 true）
- mode: Literal["text"] - 交互模式

### ChatSession

- id: Optional[int] - 数据库 ID
- thread_id: str - Thread/Session ID
- user_id: str - 用户 ID
- project_id: str - 项目 ID
- title: str - 会话标题
- message_count: int - 消息数量
- llm_calls_count: int - LLM 调用次数
- input_tokens: int - 输入 token 数
- output_tokens: int - 输出 token 数
- total_tokens: int - 总 token 数
- last_message_at: Optional[str] - 最后消息时间
- created_at: Optional[str] - 创建时间
- updated_at: Optional[str] - 更新时间
- metadata: Dict - 预留元数据
- stats: Dict - 额外统计信息

### ConversationHistory

- thread_id: str - 会话 ID
- title: str - 会话标题
- messages: List[OpenAIMessage] - 消息列表
- created_at: Optional[str] - 创建时间
- updated_at: Optional[str] - 更新时间
- llm_calls: int - LLM 调用次数

### OpenAIMessage

- id: str - 消息 ID
- role: Literal["user", "assistant", "system", "tool"] - 角色
- content: str - 消息内容
- name: Optional[str] - 工具消息名称
- tool_call_id: Optional[str] - 关联的工具调用 ID
- tool_calls: Optional[List] - 工具调用列表（assistant 消息）
- created_at: str - 创建时间

## 核心组件

### AgentService

**职责**：项目级的 Agent 管理服务

**主要方法**：
- `stream_chat`：流式对话，自动管理会话和统计
- `get_history`：获取会话历史
- `list_sessions`：列出会话
- `delete_session`：删除会话
- `rename_session`：重命名会话
- `close`：关闭数据库连接

**核心流程**（stream_chat）：
1. 获取或创建会话
2. 设置 ContextVars（JWT token、LLM config）
3. 构建 LangGraph config
4. 流式执行 Agent，收集统计信息
5. 流结束后更新会话统计
6. 同步 auto-generated title

**连接管理**：
- 使用 `AsyncSqliteSaver` 作为 checkpointer
- 支持 WAL 模式提升并发性能
- 项目切换时自动关闭旧连接
- 防止连接被垃圾回收（保存引用）

### ProjectAgentManager

**职责**：全局单例，管理所有项目的 AgentService 实例

**方法**：
- `get_agent(project_id, project_path)`：获取或创建项目的 AgentService
- `remove_agent(project_id)`：移除项目的 AgentService
- `close_all`：关闭所有 AgentService

### Chat API Routes

**文件**：`gns3server/api/routes/controller/chat.py`

**路由注册**：
```python
router.include_router(
    chat.router,
    prefix="/{project_id}/chat",
    tags=["Chat"]
)
```

**主要端点实现**：
- 所有端点都需要用户认证（`get_current_active_user`）
- 所有端点都检查项目状态是否为 "opened"
- stream 端点使用 `StreamingResponse` 返回 SSE 流

## 项目生命周期集成

### 项目打开时

创建或获取 AgentService 实例：
```python
agent_manager = await get_project_agent_manager()
agent_service = await agent_manager.get_agent(project_id, project.path)
```

### 项目关闭时

移除 AgentService 实例，释放资源：
```python
agent_manager.remove_agent(project_id)
```

### 项目删除时

1. 调用 `delete_all_sessions(project_id)` 删除所有会话和 checkpoint 数据
2. 移除 AgentService 实例
3. 项目目录被删除，数据库文件也被删除

## 前端集成

### useChat Hook

根据 SSE 消息的 `type` 字段进行不同处理：

| type | 处理逻辑 |
|------|----------|
| content | 追加到当前 AI 消息内容 |
| tool_call | 创建 tool_call 类型消息，显示工具调用信息 |
| tool_start | 可选：显示工具开始执行状态 |
| tool_end | 创建 tool_result 类型消息，显示工具执行结果 |
| error | 显示错误信息 |
| done | 标记流结束，停止加载状态 |
| heartbeat | 忽略（保活信号） |

### 错误处理

- 网络错误：显示重试选项
- LLM 错误：显示错误消息
- 项目未打开：提示用户打开项目
- LLM 未配置：引导用户配置 LLM

## 安全考虑

### 用户隔离

- 每个用户只能访问自己的会话
- user_id 存储在 config.metadata 中
- 所有数据库查询都带 user_id 过滤

### 项目访问控制

- 只允许访问用户有权限的项目
- 项目状态检查：只允许 "opened" 状态的项目使用 Chat

### LLM 配置安全

- API key 加密存储在数据库
- 使用 ContextVars 传递，不持久化到 checkpoint
- 请求结束后自动清理内存中的敏感信息

## 性能优化

### 数据库连接管理

- 使用 WAL 模式提升并发写入性能
- 项目级连接复用
- 项目切换时自动关闭旧连接

### Checkpoint 优化

- LangGraph 自动管理 checkpoints 表
- 定期清理旧 checkpoint（可选）
- 使用索引加速查询（thread_id, user_id + project_id）

### 统计信息批量更新

- 流结束后一次性更新统计信息
- 避免频繁的数据库写入

## 依赖项

- `langchain` >= 0.3.0
- `langgraph` >= 0.2.0
- `langchain-core`
- `langgraph-checkpoint-sqlite` >= 3.0.1
- `aiosqlite`

## 扩展性

### 预留字段

- `metadata`（TEXT JSON）：存储会话级别的元数据
- `stats`（TEXT JSON）：存储额外的统计信息

### 未来可能的扩展

- 多模态支持（图片、文件）
- 语音输入/输出
- 多人协作会话
- 会话分享和导出
- 自定义工具注册

## 参考资料

- [LangGraph Checkpoint Documentation](https://langchain-ai.github.io/langgraph/how-tos/checkpointers/)
- [Server-Sent Events (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [OpenAI Chat Format](https://platform.openai.com/docs/api-reference/chat)
