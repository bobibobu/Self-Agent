# Self-Agent

> 企业级 AI Agent —— 基于 LangGraph + MCP + A2A + 多协议 LLM 的完整实战项目。
> 既是能在你项目目录里干活的**编码 Agent CLI**，也是一套可部署的**多用户 Agent 服务**。
>
> 🔰 **新人入门** → [从零读懂 Self-Agent](docs/00-overview/02-从零读懂.md)（概念 + 完整链路 + 代码阅读路径）
> 📖 **参考手册** → [功能说明 · 使用手册 · 项目结构](docs/00-overview/README.md)

---

## ✨ 项目特色

- **多协议 LLM 抽象层**：统一封装 GLM(智谱)、OpenAI、Anthropic 三套主流协议，GLM 走 OpenAI 兼容协议零适配接入
- **LangGraph 状态图编排**：基于最新 LangGraph 1.x 的 ReAct Agent，原生支持短期/长期记忆、子图、人机协同
- **Hybrid RAG 知识库**：向量+关键词两路 RRF 融合检索，Contextual 分块（LLM 生成块上下文）消除孤立块歧义，检索同时是 Agent 工具（Agentic RAG，模型按需调用可多轮迭代）
- **MCP 工具生态**：基于 MCP 2.x 规范（2026-07-28 大版本，langchain.mcp + fastmcp 4.x），既能暴露自身工具给外部 Agent，也能调用第三方 MCP 服务
- **A2A 协议互通**：基于 Google/Linux Foundation 的 A2A 标准，实现 Agent 间发现与协作
- **多类型记忆系统**：PostgreSQL(对话状态/长期记忆) + Redis(缓存) + Neo4j(用户画像图谱) + MongoDB(日志)
- **企业级工程化**：全程类型注解、结构化日志、配置即代码、Docker 一键起所有基础设施
- **LLM 配置热替换**：`POST /admin/llm-config` 在线换 key/模型/默认 provider，**不重启立即生效**（缓存客户端自动失效），写回 .env 持久化；embedding 维度变化时自动提示重建索引
- **可观测**：OpenTelemetry 链路追踪，一轮对话的 LLM 调用 / 工具执行 / 检索耗时一目了然
- **编码 Agent**：工作区禁闭 + 文件/Shell 工具 + 执行前审批 + 命令沙箱 + 任务计划

## 🏗 技术栈

| 领域 | 技术 |
|---|---|
| Agent 编排 | LangGraph 1.x |
| LLM | GLM / OpenAI / Anthropic（统一抽象） |
| RAG | Hybrid 检索（pgvector + 关键词，RRF 融合）· Contextual 分块 · Agentic 检索工具 |
| Web | FastAPI + Uvicorn + SSE 流式 |
| 前端 | React 19 + Vite 8（Web）· pywebview（桌面） |
| 数据库 | PostgreSQL 16 + pgvector（psycopg 3 单一连接池）· MongoDB 8.0 · Redis 8.2 · Neo4j 5.26 LTS |
| 协议 | MCP 2.x（langchain.mcp + fastmcp 4）· A2A |
| 可观测 | OpenTelemetry（GenAI 语义约定，httpx + httpx2 出站埋点）· Jaeger v2 |
| 编码能力 | 工作区禁闭 · 文件读写 · Shell 执行 · 审批闸门 · 沙箱隔离 · 任务计划 |
| 包管理 | uv |

## 🚀 5 分钟快速开始

### 1. 启动基础设施（4 个数据库 + Jaeger 一键拉起）

```bash
cd infra
docker compose up -d
```

### 2. 安装依赖

```bash
# 推荐使用 uv（最快）
pip install uv
uv sync

# 或者用传统 pip
pip install -e .
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填入 GLM_API_KEY
```

> **注意**：`.env.example` 里 `AUTH_ENABLED=true`（Web 端有登录页，必须开认证才有意义）。
> 用 CLI 或 curl 裸调试时可临时改为 `false`——此时后端会忽略 token，
> 所有请求都算匿名用户，**会话与记忆在用户之间是共享的**。
>
> `GLM_API_KEY` 同时用于对话和向量化。**没配 key 时向量检索会降级为哈希伪向量**
> （长期记忆与 RAG 的检索结果将失去语义意义），启动日志里有明确 WARNING。

### 4. 启动服务

```bash
uv run uvicorn app.main:app --reload
# 或：python -m uvicorn app.main:app --reload
```

打开 http://localhost:8000/docs 查看交互式 API 文档。

> **Windows 不带 `--reload` 启动时**要加 `--loop app.core.eventloop:pg_loop_factory`。
> uvicorn 在 Windows 上默认用 ProactorEventLoop，psycopg 异步不支持它，
> 登录、会话列表、对话历史持久化会一起失效（启动日志有 ERROR 提示）。桌面客户端已内置该设置。

### 5. 发起对话

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "北京今天天气怎么样？", "thread_id": "demo-001"}'
```

## 📁 项目结构

```
Self-Agent/
├── app/                  # 后端主应用
│   ├── core/             # 配置、日志、异常
│   ├── llm/              # 多协议 LLM 抽象层（GLM/OpenAI/Anthropic）
│   ├── agent/            # LangGraph 核心（真·token 流式、工具、注册表、上下文压缩）
│   ├── memory/           # 短期 & 长期记忆（Postgres 持久化）
│   ├── mcp/              # MCP 协议（client + server）
│   ├── skills/           # Skill 系统
│   ├── a2a/              # A2A 协议（server + client）
│   ├── profile/          # 用户画像（Neo4j）
│   ├── evolution/        # Hermes 自我进化（记忆学习 + 反思优化）
│   ├── rag/              # ★ RAG 知识库（文档分块+向量化+检索增强）
│   ├── auth/             # ★ 用户认证（JWT）+ 多租户隔离
│   ├── services/         # ★ 业务服务层（会话/统计/可观测）
│   ├── middleware/       # ★ 限流中间件
│   ├── logging_service/  # 对话日志（MongoDB）
│   ├── db/               # 数据库连接管理
│   └── api/              # HTTP / SSE / NDJSON 路由 + 文件上传
├── clients/              # ★两套交互前端（各自独立）
│   ├── web/              #   Web 聊天页（React + Vite + SSE）
│   └── cli/              #   命令行客户端（rich + NDJSON，类 Claude Code）
├── infra/                # 基础设施（4 个数据库 + Jaeger，Docker 一键起）
├── docs/                 # 全部文档（架构/模块/开发/面试）
├── scripts/              # 验证脚本
└── tests/                # 测试（单元 + 集成）
```

## 💬 四种交互方式

### 0. 桌面客户端（推荐起步）⭐

类 ZCode / Codex 的形态：选项目目录 → 原生窗口里让 Agent 干活。
本地单机运行，不需要 Docker 和数据库（状态存 SQLite）。

```bash
uv run python clients/desktop/app.py
```

写文件、执行命令前弹审批确认框；任务计划实时打勾。详见 [clients/desktop/README.md](clients/desktop/README.md)。

### 1. Web 聊天页（React）

```bash
# 服务端形态（需先起 infra 基础设施）
uv run uvicorn app.main:app --reload
# 前端（开发模式）或直接访问 http://localhost:8000/（已托管构建产物）
cd clients/web && npm install && npm run dev   # → http://localhost:5173
```

真·token 流式打字机效果 + 工具调用实时展示 + 审批弹窗 + 任务计划面板。

### 2. 命令行 CLI —— **本地模式（默认）**
```bash
pip install -e . && pip install -e clients/cli
cd 你的项目目录
selfagent                    # 在当前目录里干活，不需要起后端、不需要任何数据库
selfagent "把 README 补全"    # 单次任务
```
Agent 跑在本进程里，文件工具操作的就是你 `cd` 进去的那个目录。
状态落单文件 SQLite（`~/.local/share/selfagent/projects/<项目哈希>/state.db`），
**按项目分库**——换个目录就是干净的新开始。

写文件、执行命令前会停下来问你：
```
╭─ 需要你的确认 ───────────╮
│ 工具：run_command        │
│ 风险：执行命令            │
╰──────────────────────────╯
 pytest tests/ -q
允许吗？ (y=允许 / n=拒绝 / a=本次会话总是允许该工具) [默认 n]
```
默认是**拒绝**（直接回车即拒绝）——安全选项必须是默认值。
`--approval auto` 或 `-y` 可跳过全部确认，但只该在沙箱/CI 里用。

常用参数与命令：
```
--cwd DIR       指定工作区          --remote [URL]  改用远程后端（旧的 HTTP 形态）
--approval M    审批策略             -y              跳过所有确认
/tools  /info  /trust  /new  /help  /exit
```

### 2b. 远程模式（服务端形态）
```bash
selfagent --remote                 # 接 http://localhost:8000
/register <用户名>   /login <用户名>   /sessions   /resume <thread>
```
token 存在 `~/.config/selfagent/credentials.json`（权限 0600）。

### 3. API 直接调用
```bash
curl -X POST http://localhost:8000/chat/stream ...   # SSE 流式
curl -X POST http://localhost:8000/chat/http-stream ... # NDJSON 流式
```

## 📚 文档导航

- **[从零读懂 Self-Agent](docs/00-overview/02-从零读懂.md)** ← 零基础从这里开始
- **[项目总览：功能点 · 使用说明 · 项目结构](docs/00-overview/README.md)** ← 参考手册
- **[启动指南：桌面 / 服务端 / Web / CLI 四种形态](docs/03-development/02-启动指南.md)** ← 怎么跑起来
- **[📘 Agent 开发学习书架](docs/06-agent-book/README.md)** ← 系统学习 Agent 开发（基础全书 + 4 本开源项目拆解，含状态/记忆/安全/协议全领域，附「状态的真相」「外部世界怎么做」等深度章节）
- [架构总览](docs/01-architecture/README.md)
- [环境搭建指南](docs/03-development/01-setup.md)
- [LLM 多协议设计](docs/02-modules/01-llm-layer.md)
- [基础设施说明](infra/README.md)

## 📌 交付进度

- [x] **Phase 1** —— 可运行地基（基础设施 + LLM 层 + LangGraph Agent + 短期记忆）
- [x] **Phase 2** —— MCP 集成 + Skill 系统
- [x] **Phase 3** —— 长期记忆 + 用户画像 + 对话日志
- [x] **Phase 4** —— A2A 协议 + 多 Agent 协作
- [x] **Phase 5** —— 测试套件 + 面试问答文档
- [x] **Phase 6** —— ★真·token 流式（SSE + NDJSON）+ Hermes 自我进化 + Web/CLI 客户端
- [x] **Phase 7** —— ★会话管理（CRUD）+ dev 持久化 + 上下文压缩 + 流式中断
- [x] **Phase 8** —— ★用户认证(JWT) + 多租户 + 限流 + RAG知识库 + 文件上传 + 用量统计 + 可观测
- [x] **Phase 9** —— ★OpenTelemetry 链路追踪
- [x] **Phase 10** —— ★编码 Agent：工作区 + 文件/Shell 工具 + 审批闸门 + 命令沙箱
- [x] **Phase 11** —— ★CLI 本地模式（内嵌 Agent + SQLite）+ 任务计划层

## 🔭 链路追踪

打开 `OTEL_ENABLED=true`，每轮对话产出一棵 span 树，Jaeger UI 在 http://localhost:16686

```
agent.turn                        5078.2ms
├─ graph.compile                  5061.4ms   ← 首次请求才有（已在启动时预热）
├─ context.build                     4.4ms
│  ├─ rag.retrieve                   0.3ms   chunk_count=3
│  ├─ memory.search                  0.1ms   memory_hits=2
│  └─ profile.get                    0.0ms
├─ chat glm-4.5-flash              820.0ms   input_tokens=312 output_tokens=24 tool_call_count=1
├─ execute_tool calculator           0.7ms
└─ chat glm-4.5-flash              610.0ms   input_tokens=381 output_tokens=17
```

它能直接回答几个平时只能靠猜的问题：**首字延迟是卡在检索还是卡在模型**、
**一个 turn 到底调了几次 LLM**（历史上这里有过「每轮调两次」的退化）、
**token 花在哪一步**。属性遵循 OpenTelemetry GenAI 语义约定（`gen_ai.*`），
不绑定特定厂商，换 Grafana Tempo / 任意 OTLP 后端都能直接用。

日志里的 `trace=` 字段会自动取当前 span 的 trace_id，同一个 id
既能在日志里 grep，也能直接在 Jaeger 里搜到调用树。

> **隐私**：`OTEL_CAPTURE_CONTENT` 默认关闭。prompt/completion 正文可能含
> 用户隐私、密钥、内部文档内容，需要时再显式打开。
>
> **开销**：`OTEL_ENABLED=false` 时全局没有 TracerProvider，所有 span 都是
> `NonRecordingSpan`（`is_recording=False`），业务代码里的埋点近乎免费，
> 所以不需要到处写 `if enabled`。

## 🔧 升级已有环境

`infra/postgres/init.sql` 只在 Postgres 数据卷**首次创建**时执行。已经跑过旧版本的话，
需要手动应用迁移，否则会话列表会一直是空的：

```bash
docker exec -i selfagent-postgres \
  psql -U selfagent -d selfagent < infra/postgres/migrations/001_fix_conversations_schema.sql
```

另外 `docker-compose.yml` 的 Postgres 镜像已换成 `pgvector/pgvector:0.8.7-pg16`
（LangGraph 的语义索引需要 `vector` 扩展）。换镜像后需要重建容器：

```bash
cd infra && docker compose up -d --force-recreate postgres
```

用原版 postgres 镜像也能跑，应用会自动降级为「持久化但无语义索引」并打 WARNING。

## ⚠️ 已知限制

这些是**当前实现的真实边界**，不是待办清单里的美好设想：

| 领域 | 限制 |
|---|---|
| 流式中断 | `cancel_registry` 是进程内字典，多 worker / 多副本下 `/chat/cancel` 只有 1/N 概率命中 |
| 可观测 | 链路追踪已接入（见上），但 `/metrics` 仍是进程内计数、非 Prometheus 格式，无法跨副本聚合 |
| 提示词版本 | `prompt_store` 落本地文件，多副本状态不一致 |
| 上传文件 | 扁平目录、无按用户分区；`/uploads` 静态目录本身不鉴权，知道文件名即可下载 |
| JWT | 无吊销名单，改密码/登出无法使已签发 token 失效（token 里已留 `jti` 锚点） |
| Hermes 进化 | 采纳与否只依据 LLM 自评分，没有评测集把关；反思样本取自全部对话，存在提示词注入面（已限管理员触发） |
| 沙箱 | 已实现（bubblewrap / Landlock 分层降级）。但 Landlock 后端**只管文件系统不限制网络**；两者都不做 syscall 过滤，未防提权类攻击 |
| 长任务 | 已有计划/TODO 层，但仍是单层 ReAct，无子 Agent / 并行分解 |
| 流式契约 | `stream_agent` 的事件流**必须消费完**，中途 break 会丢掉审批中断状态（有回归测试钉住） |
| 多模态 | 图片能上传，但 LLM 层 `ChatMessage.content` 只支持纯文本，图片进不了对话 |
| Windows | 服务端必须跑 SelectorEventLoop（psycopg 要求，见上文启动说明）；它不支持 asyncio 子进程，shell 工具退到线程里执行，超时只能杀直接子进程，杀不掉它派生出的孙进程 |
| 部署 | 无应用自身的 Dockerfile，无 CI；Renovate 会按周开依赖 PR，但没有 CI 自动跑测试，合并前要本地 `uv run pytest` |

## 📄 License

MIT
