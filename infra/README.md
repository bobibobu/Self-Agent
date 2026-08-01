# 基础设施 (infra/)

本目录集中管理 Self-Agent 用到的**全部基础设施**，目的是让你在学习时能一眼看清：
项目用了哪些中间件、每个是干什么的、怎么启动、数据存在哪。

> 设计原则：**所有服务 Docker 化，数据统一落在 `./data/` 下，一键启停，绝不散落系统各处。**

---

## 🚀 快速命令

```bash
cd infra

docker compose up -d       # 启动全部 4 个服务
docker compose ps          # 查看运行状态
docker compose logs -f     # 实时日志（全部）
docker compose logs -f postgres   # 单看某个服务

docker compose down        # 停止（保留数据）
docker compose down -v     # 停止并删除数据（重新开始）
```

---

## 📦 组件清单

| 服务 | 端口 | 用途 | 数据目录 |
|---|---|---|---|
| **PostgreSQL 16** | 5432 | 主库：对话状态、长期记忆、用户数据 | `data/postgres/` |
| **MongoDB 7** | 27017 | 文档库：事件日志、非结构化数据 | `data/mongo/` |
| **Redis 7** | 6379 | 缓存：LLM 响应缓存、限流、临时态 | `data/redis/` |
| **Neo4j 5** | 7474 / 7687 | 图库：用户画像、知识图谱 | `data/neo4j/` |

---

## 🔍 各组件详解

### 1. PostgreSQL —— "为什么用它当主库？"

**一句话**：LangGraph 的对话状态持久化（checkpointer）和长期记忆（store）**官方原生支持 PostgreSQL**，且 Postgres 的事务、JSONB、pgvector 让它既能当关系库又能做向量检索。

在本项目中它承担：
- **短期记忆**：每轮对话的状态快照（`PostgresSaver` 自动管理表）
- **长期记忆**：跨会话的用户记忆条目（`PostgresStore`，支持语义搜索）
- **业务数据**：用户表、会话元数据（见 `postgres/init.sql`）

**连接信息**（与 `.env` 一致）：
```
host=localhost port=5432 user=selfagent password=selfagent123 db=selfagent
```

可视化工具推荐：[DBeaver](https://dbeaver.io/) 或 [pgAdmin](https://www.pgadmin.org/)。

```bash
# 命令行连接
docker exec -it selfagent-postgres psql -U selfagent -d selfagent
```

### 2. MongoDB —— "为什么还要它？Postgres 不也能存 JSON 吗？"

**一句话**：对话会产生**形态多变、写多读少的事件流**（工具调用、原始 token、调试信息），Mongo 的无 schema 特性让日志写入零成本，且天然适合时序聚合。

在本项目中它承担：
- **对话事件日志**：每轮交互的完整记录（输入、输出、工具、耗时）
- **应用结构化日志**的落盘副本（可选）

**连接信息**：
```
mongodb://selfagent:selfagent123@localhost:27017
```

可视化：浏览器装 [MongoDB Compass](https://www.mongodb.com/products/tools/compass)，或：
```bash
docker exec -it selfagent-mongo mongosh -u selfagent -p selfagent123
```

### 3. Redis —— "它在这里干嘛？"

**一句话**：**内存级延迟**。用作 LLM 响应缓存（相同问题秒回）、API 限流计数器、会话临时态。

在本项目中它承担：
- **响应缓存**：对确定性请求的 LLM 结果缓存，省钱省时
- **限流**：按用户/IP 的请求频率控制
- **临时态**：单次会话内的中间变量

**连接信息**：`redis://localhost:6379/0`（开发态无密码）

```bash
docker exec -it selfagent-redis redis-cli
```

### 4. Neo4j —— "图数据库为什么需要？"

**一句话**：用户画像本质是**实体与关系的网络**（"用户 —喜欢→ 话题 —关联→ 文章"），用关系型数据库 JOIN 查多层关系会很慢，图数据库天生为关系优化。

在本项目中它承担：
- **用户画像**：兴趣、偏好、行为轨迹的关系建模
- **知识图谱**：Agent 掌握的领域知识（实体—关系）
- **协作拓扑**（Phase 4）：多 Agent 间的调用关系

**连接信息**：
```
URI:      bolt://localhost:7687
用户:     neo4j
密码:     selfagent123
浏览器:   http://localhost:7474
```

打开 http://localhost:7474 可用 Neo4j Browser 交互式查询（Cypher 语句）。

---

## 🗂 目录结构

```
infra/
├── docker-compose.yml     # 服务编排（唯一入口）
├── postgres/
│   └── init.sql           # 首次启动自动执行的建表脚本
├── mongo/
│   └── init.js            # 首次启动自动建集合与索引
├── data/                  # ★所有持久化数据（.gitignore 忽略）
│   ├── postgres/
│   ├── mongo/
│   ├── redis/
│   └── neo4j/
└── README.md              # 本文件
```

> ⚠️ `data/` 已在 `.gitignore` 中忽略，不会提交到仓库。
> 想彻底重置：`docker compose down -v` 后删除 `data/` 目录即可。

---

## ❓ 常见问题

**Q: 为什么不用 MySQL？**
LangGraph 的 checkpointer/store 官方只提供 Postgres 和 SQLite 实现。MySQL 需要自己实现整套 checkpointer 接口，工作量大且易踩坑。Postgres 在功能（JSONB、pgvector、事务）上完全覆盖 MySQL 场景，是企业级 Agent 的事实标准。

**Q: 这些服务跑起来占多少内存？**
约 1.5–2GB。Neo4j 最重（默认 512MB 堆）。开发时如果暂时不用某个服务，可在 compose 里注释掉。

**Q: 端口冲突怎么办？**
修改 `docker-compose.yml` 中对应服务的端口映射左侧（如 `5432:5432` → `5433:5432`），同时同步修改 `.env`。

**Q: 怎么确认服务都健康？**
```bash
docker compose ps   # STATUS 列显示 healthy 即可
```
