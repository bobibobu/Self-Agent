# 架构总览

> 本文档是 Self-Agent 的顶层架构说明。读完你会清楚：整体怎么分层、数据怎么流转、各组件为什么这么选型。

---

## 一、设计目标

| 目标 | 说明 |
|---|---|
| **企业级质量** | 类型注解、结构化日志、统一异常、配置即代码、优雅降级 |
| **学习友好** | 每层职责单一、目录扁平清晰、文档与代码一一对应 |
| **面试可讲** | 每个技术选型都有"为什么"，能应对深度追问 |
| **可扩展** | 新增 LLM provider / 工具 / Agent 都不影响现有代码 |

---

## 二、分层架构

```
┌─────────────────────────────────────────────────────────┐
│                     API 层 (FastAPI)                      │
│   /chat  /chat/stream  /sessions  /memory  /evolution   │
├─────────────────────────────────────────────────────────┤
│               业务服务层 (services/)                      │
│      会话管理 · （后续：认证 · 权限 · 租户隔离）           │
├─────────────────────────────────────────────────────────┤
│                   Agent 编排层 (LangGraph)                │
│        ┌──────────┐    条件路由    ┌───────┐             │
│        │ agent节点 │ ───────────→ │ tools │             │
│        │ (LLM思考) │ ←─────────── │ 节点  │             │
│        │ +流式writer│              │       │             │
│        └──────────┘               └───────┘             │
│   + 上下文压缩 · 流式中断 · Hermes 进化                   │
├─────────────────────────────────────────────────────────┤
│   LLM 抽象层        │   记忆层          │   工具层        │
│  ┌───────────────┐  │ 短期(checkpoint) │ 内置工具        │
│  │ GLM(OpenAI兼容)│  │ 长期(store)     │ MCP工具         │
│  │ OpenAI        │  │ 用户画像(Neo4j)  │ Skill工具       │
│  │ Anthropic     │  │  对话日志(Mongo) │ A2A delegate    │
│  └───────────────┘  │                  │                │
├─────────────────────────────────────────────────────────┤
│                   数据访问层 (db/)                        │
│      PostgreSQL    MongoDB    Redis    Neo4j            │
├─────────────────────────────────────────────────────────┤
│                基础设施 (infra/ Docker)                   │
└─────────────────────────────────────────────────────────┘
```

**新增业务服务层（Phase 7）**：位于 API 与 Agent 之间，承载会话管理等业务逻辑。
后续认证/租户也加在这一层——核心能力层（LLM/记忆/工具）完全不用改。

### 为什么这么分层？

每一层**只依赖它正下方的层**，符合"依赖倒置 + 单一职责"：

1. **API 层** 不关心 Agent 怎么实现，只负责接收请求、返回响应
2. **Agent 编排层** 不关心用哪个 LLM，只依赖 `LLMClient` 协议
3. **LLM 抽象层** 不关心 Agent 逻辑，只负责把统一请求转成各 provider 的格式
4. **数据访问层** 屏蔽具体数据库，提供连接管理

好处：**替换任何一层都不影响其他层**。比如把 GLM 换成 OpenAI，Agent 代码一行都不用改。

---

## 三、核心数据流：一次带工具调用的对话

以"北京今天天气怎么样？"为例，完整流转如下：

```
用户 POST /chat {message: "北京天气？", thread_id: "t1"}
  │
  ▼
[API 层] routes.py → run_agent()
  │
  ▼
[Agent 层] LangGraph 图执行
  │
  ├─① agent 节点：把消息 + 工具列表 → LLM 抽象层 → GLM
  │     GLM 返回：tool_calls=[get_weather(city="北京")]
  │
  ├─② 条件路由：检测到 tool_calls → 进入 tools 节点
  │
  ├─③ tools 节点：执行 get_weather("北京") → "晴 26°C..."
  │     结果作为 ToolMessage 追加到状态
  │
  ├─④ 回到 agent 节点：把工具结果再交给 GLM
  │     GLM 返回：自然语言总结 "北京今天晴，26度..."
  │
  └─⑤ 条件路由：无 tool_calls → 结束
  │
  ▼
[API 层] 返回 {reply: "北京今天晴，26度...", thread_id: "t1"}
```

**短期记忆**：整个过程中，checkpointer 在每步后保存状态快照。
下次用 `thread_id="t1"` 调用时，自动恢复历史消息，实现多轮对话。

---

## 四、目录与职责对照

| 目录 | 职责 | 对应层 |
|---|---|---|
| `app/api/` | HTTP 路由、请求响应模型 | API 层 |
| `app/agent/` | LangGraph 状态图、节点、工具、提示词 | Agent 编排层 |
| `app/llm/` | 多协议 LLM 抽象与 provider 实现 | LLM 抽象层 |
| `app/memory/` | 短期/长期记忆的 checkpointer 与 store | 记忆层 |
| `app/db/` | 4 个数据库的连接生命周期管理 | 数据访问层 |
| `app/core/` | 配置、日志、异常（横切关注点） | 跨层基础设施 |
| `infra/` | Docker 化的基础设施 | 基础设施 |

---

## 五、关键架构决策（面试常问）

### Q1: 为什么 LLM 用自研抽象层，而不是直接用 LangChain 的 ChatModel？

**答**：LangChain 的 `ChatOpenAI` / `ChatAnthropic` 耦合了它的消息类型和工具调用协议，且 `create_react_agent` 强制要求 LangChain 模型。自研抽象层让我们：
- **完全掌控**消息格式转换（OpenAI 和 Anthropic 的工具调用格式差异很大）
- **解耦** LangGraph 与具体 SDK，换 provider 零成本
- **统一**流式、token 统计、错误处理逻辑

代价是失去了 LangSmith 自动追踪 LLM 调用（但我们用结构化日志 + trace_id 补偿）。

### Q2: 为什么 GLM 走 OpenAI 兼容协议而不是官方 SDK？

**答**：智谱暴露了完全 OpenAI 兼容的 `/chat/completions` 端点，只需换 `base_url`。
- **零适配**：复用成熟的 openai SDK，工具调用、流式、token 统计全部白嫖
- **统一性**：GLM、OpenAI、DeepSeek、Moonshot 等都用同一份代码
- 官方 `zhipuai` SDK 只在需要 GLM 特有功能（如 thinking 模式）时才有必要

### Q3: 为什么用 PostgreSQL 而不是 MySQL？

**答**：LangGraph 的 checkpointer（短期记忆）和 store（长期记忆）官方**只实现**了 Postgres 和 SQLite 适配。
MySQL 需要自己实现整套 BaseCheckpointSaver 接口，工作量大、易踩坑。
Postgres 的 JSONB、pgvector、事务能力完全覆盖企业场景，是 Agent 领域事实标准。

### Q4: 数据库连不上时为什么不直接崩溃？

**答**：**优雅降级**。开发期常见某个容器没启动。
我们让连接失败只告警不阻断启动——这样 LLM 对话（不依赖 DB 也能跑，用 MemorySaver）仍可用。
这是生产系统韧性的体现：核心链路尽量独立于非关键依赖。

---

## 六、后续架构演进（Phase 2-5）

| Phase | 新增能力 | 架构影响 |
|---|---|---|
| P2 | MCP 协议 + Skill 系统 | tools 节点扩展为支持 MCP 远程工具 |
| P3 | 长期记忆 + 用户画像 | 新增 store 节点 + Neo4j 画像查询节点 |
| P4 | A2A 协议 | Agent 可作为 A2A server 被发现，也可调用外部 Agent |
| P5 | 完整测试 + 面试文档 | 工程化收尾 |

每个 Phase 都向后兼容，不会推翻已有架构。
