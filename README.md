# Self-Agent

> 企业级 AI Agent —— 基于 LangGraph + MCP + A2A + 多协议 LLM 的完整实战项目。
> 面向**学习与企业面试**：每个模块都配有详细文档与设计说明。

---

## ✨ 项目特色

- **多协议 LLM 抽象层**：统一封装 GLM(智谱)、OpenAI、Anthropic 三套主流协议，GLM 走 OpenAI 兼容协议零适配接入
- **LangGraph 状态图编排**：基于最新 LangGraph 1.x 的 ReAct Agent，原生支持短期/长期记忆、子图、人机协同
- **MCP 工具生态**：基于官方 MCP 协议，既能暴露自身工具给外部 Agent，也能调用第三方 MCP 服务
- **A2A 协议互通**：基于 Google/Linux Foundation 的 A2A 标准，实现 Agent 间发现与协作
- **多类型记忆系统**：PostgreSQL(对话状态/长期记忆) + Redis(缓存) + Neo4j(用户画像图谱) + MongoDB(日志)
- **企业级工程化**：全程类型注解、结构化日志、配置即代码、Docker 一键起所有基础设施

## 🏗 技术栈

| 领域 | 技术 |
|---|---|
| Agent 编排 | LangGraph 1.x |
| LLM | GLM / OpenAI / Anthropic（统一抽象） |
| Web | FastAPI + Uvicorn + SSE 流式 |
| 数据库 | PostgreSQL · MongoDB · Redis · Neo4j |
| 协议 | MCP · A2A |
| 包管理 | uv |

## 🚀 5 分钟快速开始

### 1. 启动基础设施（4 个数据库一键拉起）

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

### 4. 启动服务

```bash
uv run uvicorn app.main:app --reload
# 或：python -m uvicorn app.main:app --reload
```

打开 http://localhost:8000/docs 查看交互式 API 文档。

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
├── infra/                # 基础设施（Docker 化的 4 个数据库）
├── docs/                 # 全部文档（架构/模块/开发/面试）
├── scripts/              # 验证脚本
└── tests/                # 测试（单元 + 集成）
```

## 💬 三种交互方式

### 1. Web 聊天页（React）
```bash
cd clients/web && npm install && npm run dev   # → http://localhost:5173
```
真·token 流式打字机效果 + 工具调用实时展示。

### 2. 命令行 CLI（类 Claude Code）
```bash
cd clients/cli && pip install -e .
selfagent              # 交互式 REPL
selfagent "你好"       # 单次查询
```

### 3. API 直接调用
```bash
curl -X POST http://localhost:8000/chat/stream ...   # SSE 流式
curl -X POST http://localhost:8000/chat/http-stream ... # NDJSON 流式
```

## 📚 文档导航

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

## 📄 License

MIT
