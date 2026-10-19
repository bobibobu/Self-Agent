# Self-Agent 项目总览

> 一个能在你的项目目录里干活的编码 Agent，同时也是一套可部署的多用户 Agent 服务。

> 🔰 **第一次接触本项目、或不熟悉 Agent/LangGraph？**
> 请先读 **[从零读懂 Self-Agent](02-从零读懂.md)** —— 从概念到代码阅读路径，
> 用一句话的完整旅程把整个系统串起来。本文档偏参考手册，适合读完那篇之后查阅。

本文档覆盖：[功能点](#一功能点) · [快速开始](#二快速开始) · [使用说明](#三使用说明) ·
[项目结构](#四项目结构) · [配置项](#五配置项) · [安全模型](#六安全模型) ·
[开发与测试](#七开发与测试) · [已知限制](#八已知限制)

---

## 零、它是什么

Self-Agent 有两种形态，共用同一套 Agent 内核：

| 形态 | 入口 | 状态存储 | 适用 |
|---|---|---|---|
| **本地 CLI** | `selfagent` | 单文件 SQLite | 在自己项目里写代码，类似 Codex CLI |
| **服务端** | `uvicorn app.main:app` | PostgreSQL + Mongo + Redis + Neo4j | 多用户 / 多租户，Web 端接入 |

本地形态**零外部依赖**——不需要起任何数据库。服务端形态提供认证、多租户、
RAG 知识库、用量统计等企业能力。

---

## 一、功能点

### 1.1 Agent 内核

| 能力 | 说明 |
|---|---|
| **ReAct 循环** | 基于 LangGraph 1.x 状态图，`agent ⇄ tools` 条件路由 |
| **真·token 流式** | 单次流式调用同时拿到文本与 tool_calls，不做二次采样 |
| **任务计划** | `update_plan` 工具维护 TODO 记事板，随 checkpointer 持久化 |
| **人在回路** | 写文件 / 执行命令前 `interrupt()` 挂起，用户决策后 `Command(resume=)` 续跑 |
| **上下文压缩** | 消息超阈值自动摘要早期对话；per-thread 摘要缓存 + 迟滞窗口，长会话不每轮重摘 |
| **流式中断** | 协作式取消标志，可中途停止生成 |

### 1.2 编码能力

| 工具 | 风险 | 说明 |
|---|---|---|
| `read_file` | 只读 | 带行号读取，支持行范围 |
| `list_dir` | 只读 | 自动跳过 `.git`/`node_modules` 等 |
| `glob_files` | 只读 | 通配符查找 |
| `grep_files` | 只读 | 字面量内容搜索，跳过二进制与敏感文件 |
| `write_file` | 写 | 覆盖写入，父目录自动创建 |
| `edit_file` | 写 | 精确文本替换；匹配到多处时**拒绝**而非猜测 |
| `delete_file` | 写 | 只删单个文件，拒绝删目录 |
| `run_command` | 执行 | 不经 shell 解释器，超时杀进程组 |
| `update_plan` | 只读 | 维护任务计划 |

全部路径经 `Workspace.resolve()` 禁闭在工作区内。

### 1.3 安全

- **工作区禁闭**：先 `resolve()` 再判归属，同时挡住 `../` 穿越与符号链接逃逸
- **审批闸门**：四档策略 `gated`（默认）/ `auto` / `strict` / `readonly`
- **命令沙箱**：bubblewrap / Landlock 分层降级，隐藏 `$HOME`，默认切断网络
- **敏感文件保护**：`.env`、`*.pem`、`id_rsa` 等即便被精确指名也拒绝读取
- **认证与多租户**：JWT + 角色（服务端形态）

### 1.4 记忆与知识

| 层 | 存储 | 说明 |
|---|---|---|
| 短期记忆 | SQLite / PostgreSQL | 按 `thread_id` 续接上下文 |
| 长期记忆 | LangGraph Store | 跨会话的用户事实，语义检索 |
| 用户画像 | Neo4j | 兴趣 / 偏好图谱 |
| RAG 知识库 | LangGraph Store | 文档分块 + 向量检索，按租户隔离 |
| 对话日志 | MongoDB | 完整事件流，供统计与反思 |

### 1.5 协议与扩展

- **MCP**：既是 client（接第三方工具）也是 server（暴露自身工具）
- **A2A**：Agent 间发现与协作，带 SSRF 防护
- **Skill 系统**：声明式注册工具 + 提示词片段
- **多协议 LLM**：GLM / OpenAI / Anthropic 统一抽象

### 1.6 可观测

- **OpenTelemetry 链路追踪**，遵循 GenAI 语义约定（`gen_ai.*`）
- 日志 `trace_id` 与 span 打通，同一 id 可在日志 grep、在 Jaeger 搜索
- `/metrics` 运行时指标、`/stats/usage` token 用量与成本估算

---

## 二、快速开始

### 2.1 本地 CLI（推荐先试这个）

```bash
git clone <repo> && cd Self-Agent
pip install -e . && pip install -e clients/cli

cp .env.example .env          # 至少填 GLM_API_KEY
cd 你的项目目录
selfagent
```

不需要 Docker，不需要任何数据库。

### 2.2 服务端

```bash
cd infra && docker compose up -d      # PostgreSQL + Mongo + Redis + Neo4j + Jaeger
cd .. && cp .env.example .env         # 填 GLM_API_KEY，改 JWT_SECRET
uv sync                               # 或 pip install -e .
uv run uvicorn app.main:app --reload
```

- API 文档 http://localhost:8000/docs
- 链路追踪 http://localhost:16686（需 `OTEL_ENABLED=true`）

Web 前端：

```bash
cd clients/web && npm install && npm run dev   # http://localhost:5173
```

> **升级已有环境**：`init.sql` 只在数据卷首次创建时执行。老环境需手动跑
> `infra/postgres/migrations/001_fix_conversations_schema.sql`，
> 并把 Postgres 镜像换成 `pgvector/pgvector:0.8.7-pg16`（语义索引需要 vector 扩展）。
> 各数据库镜像跨版本升级的注意事项见 [infra/README.md](../../infra/README.md) 的「版本与升级」一节。

---

## 三、使用说明

### 3.1 CLI 本地模式

```bash
selfagent                        # 交互式
selfagent "把 README 补全"        # 单次任务
selfagent --cwd ~/proj "跑测试"   # 指定工作区
selfagent --approval readonly    # 只读模式，拒绝一切写与执行
selfagent -y "格式化所有文件"      # 跳过确认（仅限沙箱/CI）
selfagent --remote               # 改用远程后端（服务端形态）
```

启动后会显示当前环境：

```
╭─ 🤖 Self-Agent（本地模式）──────────────────────────╮
│ 工作区   /home/you/myproject                        │
│ 模型     glm                                        │
│ 沙箱     Landlock ABI v7（仅文件系统隔离）           │
│ 审批     gated  (写与执行前会询问)                   │
│ 工具     8 只读 · 3 写 · 1 执行                      │
│ 状态     ~/.local/share/selfagent/projects/…/state.db│
╰─────────────────────────────────────────────────────╯
```

**审批交互**——写文件或执行命令前会停下来：

```
╭─ 需要你的确认 ───────────╮
│ 工具：run_command        │
│ 风险：执行命令            │
╰──────────────────────────╯
 pytest tests/ -q
允许吗？ (y=允许 / n=拒绝 / a=本次会话总是允许该工具) [默认 n]
```

直接回车 = 拒绝。安全选项是默认值。

**任务计划**——多步任务会自动列计划并随进展更新：

```
╭─ 任务计划 1/3 ─╮
│ ✔ 读懂 a.py    │
│ ▶ 改写实现     │
│ ○ 验证结果     │
╰────────────────╯
```

**斜杠命令**：

| 命令 | 说明 |
|---|---|
| `/new` | 开始新对话（清空上下文） |
| `/plan` | 查看当前任务计划 |
| `/tools` | 列出工具及风险等级 |
| `/info` | 显示工作区 / 沙箱 / 审批状态 |
| `/trust` | 查看本次会话免问的工具 |
| `/help` `/exit` | — |

会话按项目分库存在 `~/.local/share/selfagent/projects/<路径哈希>/state.db`，
同项目历史能续上，换目录就是干净的新开始。

### 3.2 CLI 远程模式

```bash
selfagent --remote                    # 默认 http://localhost:8000
selfagent --remote http://host:8000
```

后端开了认证时先登录（token 存 `~/.config/selfagent/credentials.json`，权限 0600）：

```
/register <用户名>    /login <用户名>    /logout
/sessions             /resume <thread>   /history
/tools  /memory <关键词>  /profile  /status
```

### 3.3 HTTP API

```bash
# 一次性对话
curl -X POST localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","thread_id":"demo"}'

# SSE 流式（Web 端用）
curl -X POST localhost:8000/chat/stream -d '{...}'

# NDJSON 流式（CLI / 非浏览器用）
curl -X POST localhost:8000/chat/http-stream -d '{...}'
```

主要端点：

| 端点 | 说明 | 鉴权 |
|---|---|---|
| `POST /chat` `/chat/stream` `/chat/http-stream` | 对话 | 用户 |
| `POST /chat/cancel/{thread_id}` | 中断生成 | 用户（校验归属） |
| `GET/POST/PATCH/DELETE /sessions[/{id}]` | 会话管理 | 用户（校验归属） |
| `GET /history/{thread_id}` | 对话历史 | 用户（校验归属） |
| `POST /auth/register` `/auth/login` `GET /auth/me` | 认证 | — |
| `POST /rag/kb/{id}` `GET /rag/kb/{id}/search` `DELETE /rag/kb/{id}` | 知识库 | 用户（租户隔离） |
| `POST /memory` `GET /memory/{uid}[/all]` | 长期记忆 | 用户 |
| `GET /tools` `/skills` | 能力清单 | — |
| `POST /evolution/reflect` `GET /evolution/prompt` | 提示词自进化 | **管理员** |
| `GET /metrics` `/stats/usage` | 指标与用量 | **管理员** |

### 3.4 Web 前端

`clients/web`，React + Vite。登录后可对话、切换历史会话、查看工具调用过程。

---

## 四、项目结构

```
Self-Agent/
├── app/                          # Agent 内核 + 服务端
│   ├── core/
│   │   ├── config.py             # 全部配置项（pydantic-settings）
│   │   ├── logging.py            # 结构化日志，trace_id 与 span 打通
│   │   ├── telemetry.py          # OpenTelemetry 埋点助手
│   │   └── exceptions.py         # 统一异常体系与全局处理器
│   ├── agent/
│   │   ├── graph.py              # LangGraph 状态图组装；stream/resume 入口
│   │   ├── state.py              # AgentState（messages + plan）
│   │   ├── plan.py               # 任务计划工具与校验
│   │   ├── registry.py           # 工具注册表 + 风险分级
│   │   ├── context_manager.py    # 上下文压缩（摘要缓存 + 迟滞）
│   │   ├── cancel_registry.py    # 流式中断
│   │   ├── nodes/
│   │   │   ├── agent_node.py     # 调 LLM，流式产出 + 聚合 tool_calls
│   │   │   ├── tools_node.py     # 并发执行工具 + 审批闸门
│   │   │   └── bridge.py         # LangChain 消息 ↔ 统一 LLM 模型；工具 schema 缓存
│   │   ├── tools/
│   │   │   ├── __init__.py       # 内置工具（计算器/时间/天气）
│   │   │   ├── files.py          # 文件读写搜索
│   │   │   └── shell.py          # 命令执行
│   │   └── prompts/              # 系统提示词
│   ├── workspace.py              # ★ 工作区与路径禁闭
│   ├── sandbox.py                # ★ 命令沙箱（bwrap / Landlock）
│   ├── llm/                      # 多协议 LLM 抽象
│   │   ├── base.py               # LLMClient 协议
│   │   ├── models.py             # 统一消息/响应模型
│   │   ├── factory.py            # 按配置建客户端
│   │   └── providers/            # openai_like.py · anthropic.py
│   ├── memory/
│   │   ├── checkpointer.py       # 短期记忆（SQLite / Postgres / 内存）
│   │   ├── local_store.py        # ★ 本地 SQLite 存储，按项目分库
│   │   ├── pg.py                 # 全应用共享 psycopg 连接池（业务表 + LangGraph）
│   │   ├── store.py              # 长期记忆
│   │   └── embeddings.py         # 向量化（真实 embedding + 降级）
│   ├── rag/                      # 知识库：分块 · 检索 · 路由
│   ├── auth/                     # JWT · 角色 · 多租户
│   ├── mcp/                      # MCP client + server
│   ├── a2a/                      # A2A 协议
│   ├── skills/                   # Skill 系统
│   ├── evolution/                # Hermes 自进化
│   ├── profile/                  # 用户画像（Neo4j）
│   ├── services/                 # 会话 · 统计 · 指标
│   ├── middleware/               # 限流
│   ├── db/manager.py             # 四个数据库的连接生命周期
│   ├── api/                      # HTTP 路由与 schema
│   └── main.py                   # FastAPI 应用入口
├── clients/
│   ├── cli/selfagent_cli/
│   │   ├── main.py               # 入口与参数解析
│   │   ├── local.py              # ★ 本地模式引导
│   │   ├── localrepl.py          # ★ 本地交互循环
│   │   ├── render.py             # ★ 审批与计划渲染
│   │   ├── api.py                # 远程模式 HTTP 客户端
│   │   └── config.py             # 凭据持久化（0600）
│   └── web/                      # React + Vite 前端
├── infra/
│   ├── docker-compose.yml        # 4 个数据库 + Jaeger
│   └── postgres/                 # init.sql + migrations/
├── tests/                        # 190+ 条测试
│   ├── conftest.py               # 测试隔离（禁止写真实库）
│   ├── test_unit.py              # 单元
│   ├── test_perf_optimizations.py # 性能优化回归（schema/摘要/提示词缓存）
│   ├── test_prompt_caching.py     # 提示词缓存前缀
│   ├── test_structured_output.py  # 结构化输出契约
│   ├── test_api_smoke.py         # HTTP 冒烟
│   ├── test_regressions.py       # 历史缺陷回归
│   ├── test_client_contract.py   # 前后端协议契约
│   ├── test_telemetry.py         # 链路追踪
│   ├── test_coding_tools.py      # 编码工具安全边界
│   ├── test_sandbox.py           # 沙箱实际拦截效果
│   ├── test_local_mode.py        # 本地模式与审批往返
│   └── test_plan.py              # 任务计划
├── scripts/                      # 验证与运维脚本
└── docs/                         # 文档
```

★ = 编码 Agent 相关的核心新增模块

---

## 五、配置项

全部配置见 `.env.example`，以下是最常用的：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_DEFAULT_PROVIDER` | `glm` | `glm` / `openai` / `anthropic` |
| `GLM_API_KEY` | — | 同时用于对话与向量化 |
| `WORKSPACE_ROOT` | 当前目录 | 文件工具的活动范围 |
| `TOOL_APPROVAL_MODE` | `gated` | `gated` / `auto` / `strict` / `readonly` |
| `SANDBOX_ENABLED` | `true` | 命令沙箱总开关 |
| `SANDBOX_BACKEND` | `auto` | `auto` / `bwrap` / `landlock` / `none` |
| `SANDBOX_ALLOW_NETWORK` | `false` | 沙箱内是否放行网络 |
| `STORAGE_BACKEND` | `auto` | `auto`（Postgres）/ `sqlite` / `memory` |
| `AGENT_RECURSION_LIMIT` | `25`（CLI 本地 `80`） | agent⇄tools 最大步数 |
| `AUTH_ENABLED` | `true` | 服务端形态必须开 |
| `OTEL_ENABLED` | `false` | 链路追踪 |
| `OTEL_CAPTURE_CONTENT` | `false` | ⚠️ 是否把 prompt 正文写进 span |

---

## 六、安全模型

三层，互不替代：

```
第一层  工作区禁闭    路径解析后必须落在 root 内 —— 挡 ../ 穿越与 symlink 逃逸
第二层  审批闸门      写与执行前询问用户       —— 管「用户知不知情」
第三层  命令沙箱      限制可写范围、隐藏 $HOME —— 管「同意后能造成多大破坏」
```

第二、三层为什么都要：

> 审批通过的 `pytest` 也可能因为项目里有个恶意 `conftest.py` 而读走
> `~/.ssh/id_rsa` 并 POST 出去 —— 用户点同意时想的是"跑个测试"。

**几处刻意的 fail-closed**：

- 未声明风险的工具（尤其 MCP 发现来的第三方工具）默认按最高风险处理
- 审批结果解析不了 → 按拒绝
- `interrupt()` 拿不到图上下文 → 拒绝执行而非放行
- 审批交互的默认选项（直接回车）→ 拒绝

沙箱实测效果：

| 操作 | 无沙箱 | Landlock |
|---|---|---|
| 读工作区外的 `id_rsa` | 成功 | `Permission denied` |
| 写工作区外的文件 | 成功 | `cannot touch` |
| 工作区内读写 | 成功 | 成功 |

---

## 七、开发与测试

```bash
pip install -e ".[dev]"
pytest tests/ -q          # 184 passed，约 6 秒
python scripts/benchmark.py # 性能基准（框架层 QPS），报告见 docs/04-guides/性能基准报告.md
ruff check app/ tests/ scripts/ clients/cli
```

测试**不会写你的真实数据库**——`tests/conftest.py` 在任何 `app.*` 导入前把
四个数据库指向黑洞端口。历史上曾因此把测试对话灌进真实历史，清理脚本：

```bash
python scripts/cleanup_test_data.py            # 预览
python scripts/cleanup_test_data.py --apply    # 删除
```

测试组织原则：**断言行为而非配置**。沙箱测试真的去读工作区外的文件，
审批测试真的检查文件有没有被创建，协议测试用后端真实吐出的字节。

---

## 八、已知限制

这些是**当前实现的真实边界**，不是待办清单里的设想：

| 领域 | 限制 |
|---|---|
| 沙箱 | Landlock 后端只管文件系统**不限制网络**；两个后端都不做 syscall 过滤，未防提权 |
| 长任务 | 有计划层但仍是单层 ReAct，无子 Agent / 并行分解 |
| 流式契约 | `stream_agent` 事件流**必须消费完**，中途 break 会丢掉审批中断状态（有回归测试钉住） |
| 多副本 | `cancel_registry`、`/metrics`、`prompt_store` 都是进程内状态，多副本下不一致 |
| 可观测 | `/metrics` 非 Prometheus 格式，无法跨副本聚合 |
| JWT | 无吊销名单，改密码/登出无法使已签发 token 失效（token 里已留 `jti` 锚点） |
| 上传文件 | 扁平目录、无按用户分区；`/uploads` 静态目录不鉴权 |
| Hermes 进化 | 采纳与否只依据 LLM 自评分，没有评测集把关 |
| 多模态 | 图片能上传，但 `ChatMessage.content` 只支持纯文本，图片进不了对话 |
| 部署 | 无应用自身的 Dockerfile，无 CI |
| 能力管理 | MCP server / Skill 只能改配置文件或代码后重启，无运行时增删；知识库无列表接口 |

---

## 附：文档导航

- **[从零读懂 Self-Agent](02-从零读懂.md)** ← 新人从这里开始
- [架构总览](../01-architecture/README.md)
- [模块文档](../02-modules/)（LLM 层 · Agent 图 · 记忆 · MCP · Skill · A2A · RAG 等）
- [环境搭建](../03-development/01-setup.md)
- [基础设施](../../infra/README.md)
