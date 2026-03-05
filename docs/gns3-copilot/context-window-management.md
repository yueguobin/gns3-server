# LLM 上下文窗口管理实现文档

## 概述

本文档说明 GNS3 Copilot 的上下文窗口管理实现机制，包括消息裁剪、Token 计数和配置验证。

## 实现架构

### 1. 核心模块

**文件位置**: `gns3server/agent/gns3_copilot/agent/context_manager.py`

#### Token 计数策略

系统使用 **tiktoken** 进行 Token 计数（context_manager.py:60）：

```python
_tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
```

**必需依赖**：
```bash
pip install tiktoken>=0.8.0
```

如果未安装 tiktoken，系统将在启动时抛出 `ModuleNotFoundError`。

#### 关键函数

**`count_tokens(text: str) -> int`** (context_manager.py:84-100)
- 使用 tiktoken 准确计数文本的 token 数
- 使用 `cl100k_base` 编码
- 返回精确的 token 数

**`estimate_tool_tokens(tools: list) -> int`** (context_manager.py:103-169)
- 序列化工具 schema 为 JSON
- 使用 tiktoken 计数工具定义的 token 消耗
- 支持 Pydantic v1/v2 兼容性
- 失败时使用 1000 tokens 的回退值

**`create_pre_model_hook(...)`** (context_manager.py:195-402)
- 创建预处理函数（pre_model_hook）
- 在每次 LLM 调用前自动执行：
  1. 注入 topology 信息到 system prompt
  2. 估算工具定义的 token 消耗
  3. 裁剪消息历史以适应上下文限制
- 返回一个可调用的函数，用于准备消息

### 2. 裁剪逻辑详解

#### 2.1 Token 预算分配

当调用 LLM 时，发送的内容包含两部分：

```
发送给 LLM 的完整请求:
┌─────────────────────────────────────────────────────────────┐
│ 1. Messages (我们管理的)                                     │
│    ├─ SystemMessage: system prompt + topology (模板注入)     │
│    └─ HumanMessage/AIMessage: 用户消息 / 历史消息             │
├─────────────────────────────────────────────────────────────┤
│ 2. Tool Definitions (LangChain 自动添加，不在消息中)          │
│    ├─ Tool 1 schema (name, description, parameters)        │
│    ├─ Tool 2 schema                                        │
│    └─ ... (约 500-1500 tokens per tool)                   │
└─────────────────────────────────────────────────────────────┘
```

**System Message 结构**：
- 使用模板变量 `{{topology_info}}` 动态注入 topology
- System prompt 包含占位符：`"### CURRENT TOPOLOGY\n{{topology_info}}"`
- 如果有 topology，替换为实际内容
- 如果没有 topology，替换为 `"(No topology information available)"`

#### 2.2 裁剪流程

```
第一步：计算输入预算
┌─────────────────────────────────────────────────────────────┐
│ context_limit: 128,000 tokens (128K)                        │
│ strategy: balanced (75%)                                    │
│                                                            │
│ 输入预算 = 128 × 1000 × 0.75 = 96,000 tokens              │
└─────────────────────────────────────────────────────────────┘
                            ↓
第二步：减去工具定义
┌─────────────────────────────────────────────────────────────┐
│ 输入预算: 96,000 tokens                                     │
│ 工具定义: 1,725 tokens                                     │
│                                                            │
│ 可用于消息 = 96,000 - 1,725 = 94,275 tokens                │
└─────────────────────────────────────────────────────────────┘
                            ↓
第三步：trim_messages 处理
┌─────────────────────────────────────────────────────────────┐
│ 调用 LangChain 的 trim_messages:                            │
│ - max_tokens = 94,275 (包含 system message)                │
│ - strategy = "last" (保留最新消息)                          │
│ - token_counter = tiktoken 计数函数                         │
│ - include_system = True (始终保留 system)                   │
│                                                            │
│ trim_messages 会:                                           │
│ 1. 保留 SystemMessage (system + topology)                  │
│ 2. 从最新消息开始，保留尽可能多的历史                        │
│ 3. 超出限制时，丢弃最旧的消息                                │
└─────────────────────────────────────────────────────────────┘
```

#### 2.3 裁剪优先级

系统按以下优先级保留内容：

| 优先级 | 内容 | 说明 |
|--------|------|------|
| 1️⃣ | System Message (system prompt + topology) | 永远保留 |
| 2️⃣ | 最新用户消息 | 至少保留最后1条 |
| 3️⃣ | 旧对话历史 | 按时间顺序丢弃 |

**注意**：System prompt 和 topology info 通过模板变量合并为一个 SystemMessage，无法单独分离。

#### 2.4 边界情况处理

| 情况 | 处理方式 |
|------|----------|
| System (包含 topology) > 预算 | 保留完整的 System Message（无法分离 system 和 topology） |
| Tools > 预算 | ERROR 日志，建议增加 context_limit 或减少工具数量 |
| 历史全被裁剪 | 保留最后1条用户消息 |

**重要提示**：
- 当 system + topology 超出可用预算时，**两者都会被保留**
- 无法只丢弃 topology 而保留 system prompt（因为已合并）

### 3. 集成到 GNS3 Copilot

**文件位置**: `gns3server/agent/gns3_copilot/agent/gns3_copilot.py`

#### 实现方式

**关键点**：系统使用**自定义 StateGraph**，不是 LangGraph 的预构建 agent。

因此，`pre_model_hook` 不能通过 `model.invoke(config={"configurable": {"pre_model_hook": ...}})` 传递。

**正确的使用方式**：**直接调用** `pre_hook` 函数准备消息。

```python
def llm_call(state: dict, config: RunnableConfig | None = None):
    """LLM decides whether to call a tool or not."""

    # 1. 获取 topology 信息
    project_id = config["configurable"].get("project_id")
    topology_info = None
    if project_id:
        topology_tool = GNS3TopologyTool()
        topology = topology_tool._run(project_id=project_id)
        if topology and "error" not in topology:
            topology_info = topology

    # 2. 创建 pre_model_hook
    system_prompt = load_system_prompt()
    pre_hook = create_pre_model_hook(
        system_prompt=system_prompt,
        get_topology_func=lambda s: s.get("topology_info"),
        get_llm_config_func=get_current_llm_config,
        get_tools_func=lambda: tools,
    )

    # 3. 创建 model with tools
    model_with_tools = create_base_model_with_tools(tools, llm_config=llm_config)

    # 4. ⭐ 关键：直接调用 pre_hook 准备消息
    logger.info("Calling pre_hook to prepare %d messages", len(messages))
    prepared_state = pre_hook({"messages": messages, "topology_info": topology_info})
    prepared_messages = prepared_state["messages"]

    # 5. 使用准备好的消息调用 LLM
    response = model_with_tools.invoke(prepared_messages)

    return {"messages": [response], ...}
```

#### 为什么不通过 config 传递？

LangGraph 的 `pre_model_hook` 参数仅适用于**预构建的 agent**，不适用于自定义 StateGraph。

| Agent 类型 | pre_model_hook 支持方式 |
|------------|------------------------|
| `create_react_agent` | ✅ 通过 `pre_model_hook` 参数 |
| `chat_agent_executor` | ✅ 通过 `pre_model_hook` 参数 |
| **自定义 StateGraph** | ❌ **不支持**，需要直接调用 |

我们的实现使用的是自定义 StateGraph（`agent_builder = StateGraph(MessagesState)`），所以必须直接调用 `pre_hook`。

### 4. 执行流程

```
用户发送消息
     ↓
llm_call 节点被调用
     ↓
获取 project_id (从 config["configurable"])
     ↓
调用 GNS3TopologyTool._run(project_id) 获取 topology
     ↓
存储 topology_info 到 state
     ↓
创建 pre_model_hook (通过 create_pre_model_hook())
     ↓
【关键】直接调用 pre_hook({"messages": messages, "topology_info": topology_info})
     ├─ 1. 注入 topology 到 system prompt
     ├─ 2. 估算工具定义 tokens
     ├─ 3. 调用 trim_messages() 裁剪消息
     └─ 4. 返回准备好的消息列表
     ↓
使用准备好的消息调用 model.invoke()
     ↓
返回 LLM 响应
```

---

## 策略实现

### Context Strategy Ratios

**定义**（context_manager.py:68-72）：

```python
CONTEXT_STRATEGY_RATIOS = {
    "conservative": 0.60,
    "balanced": 0.75,
    "aggressive": 0.85,
}
```

**默认值**（context_manager.py:74）：
```python
DEFAULT_CONTEXT_STRATEGY = "balanced"
```

### 策略对比

| 策略 | 输入比例 | 输出预留 | 计算公式 |
|------|---------|---------|---------|
| Conservative | 60% | 40% | `context_limit × 1000 × 0.60` |
| Balanced | 75% | 25% | `context_limit × 1000 × 0.75` |
| Aggressive | 85% | 15% | `context_limit × 1000 × 0.85` |

---

## 日志输出

### 正常情况（topology 成功注入）

```
INFO: Calling pre_hook to prepare 1 messages
INFO: ✓ Topology injected: 7722 chars, nodes: ['netshoot-1', 'R1', 'R2', 'IOU-L3-1', 'IOU-L3-2']
INFO: Context ready: 2 msgs, ~3815 tokens + 1725 tools = 5540 / 128K (4.3%), strategy=conservative
INFO: Messages prepared: 1 → 2
INFO: LLM call completed: tool_calls=0
```

### 发生裁剪时

```
INFO: Calling pre_hook to prepare 50 messages
INFO: ✓ Topology injected: 8500 chars, nodes: ['R1', 'R2', ...]
INFO: Messages trimmed: 50 → 25 msgs. Total: ~82000 tokens + 1725 tools = 83725 / 128K (65.4%), strategy=balanced
INFO: Messages prepared: 50 → 25
```

### topology 为 None 时

```
INFO: Calling pre_hook to prepare 1 messages
WARNING: ✗ Topology data is None, injecting placeholder
INFO: Context ready: 2 msgs, ~800 tokens + 1725 tools = 2525 / 128K (2.0%), strategy=balanced
```

---

## 错误处理

### tiktoken 未安装

如果 tiktoken 未安装，系统将在启动时抛出错误：

```python
ModuleNotFoundError: No module named 'tiktoken'
```

**解决方法**：
```bash
pip install tiktoken>=0.8.0
```

### context_limit 缺失或无效

如果 LLM 配置中没有 `context_limit` 或值无效（context_manager.py:285-295）：

```python
if "context_limit" not in llm_config:
    raise ValueError("context_limit is required in LLM config")

limit = llm_config["context_limit"]
if not isinstance(limit, int) or limit <= 0:
    raise ValueError(f"Invalid context_limit: {limit}")
```

### 裁剪失败

```python
try:
    trimmed = trim_messages(...)
except Exception as e:
    logger.error("Failed to trim messages: %s", e)
    logger.warning("Returning original messages due to trimming error")
    return {"messages": messages_with_system}
```

---

## 相关源文件

- `gns3server/agent/gns3_copilot/agent/context_manager.py` - 上下文管理核心逻辑
- `gns3server/agent/gns3_copilot/agent/gns3_copilot.py` - LLM 调用节点（StateGraph）
- `gns3server/agent/gns3_copilot/agent/model_factory.py` - 模型创建和工具绑定
