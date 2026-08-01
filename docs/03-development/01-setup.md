# 环境搭建指南

> 从零开始把 Self-Agent 跑起来。按顺序操作，约 15 分钟。

---

## 前置条件

| 工具 | 版本要求 | 检查命令 |
|---|---|---|
| Python | ≥ 3.12 | `python --version` |
| Docker | ≥ 24.0 | `docker --version` |
| Docker Compose | ≥ v2 | `docker compose version` |
| uv（推荐） | 任意 | `uv --version` |

> Windows 用户建议用 Git Bash 或 WSL。Docker 需先启动 Docker Desktop。

---

## 第一步：启动基础设施（4 个数据库）

```bash
cd infra
docker compose up -d
```

验证全部健康：
```bash
docker compose ps
# 期望看到 4 个服务都是 healthy（neo4j 启动较慢，约 30 秒）
```

各服务控制台地址：
- Neo4j Browser: http://localhost:7474 （账号 neo4j / 密码 selfagent123）
- 其余通过代码或客户端工具连接（见 [基础设施说明](../../infra/README.md)）

> 详见 `infra/README.md`。

---

## 第二步：安装 Python 依赖

**方式 A：用 uv（推荐，最快）**
```bash
pip install uv              # 如果还没装 uv
uv venv                     # 创建虚拟环境
uv pip install -e .         # 安装项目依赖（含开发依赖）
```

**方式 B：用传统 pip**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .
```

---

## 第三步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，**至少填入 LLM 密钥**：

```ini
# 必填：GLM API Key（去 https://open.bigmodel.cn 控制台获取）
GLM_API_KEY=你的真实key

# 模型默认用免费的 glm-4.5-flash，也可改 glm-4.6 / glm-5.2
GLM_MODEL=glm-4.5-flash
```

其余数据库连接信息默认指向本地 Docker 服务，无需改动。

> 想用 OpenAI 或 Anthropic？把 `LLM_DEFAULT_PROVIDER` 改成 `openai` / `anthropic` 并填对应 key 即可。

---

## 第四步：启动服务

```bash
uv run uvicorn app.main:app --reload
# 或不用 uv：
python -m uvicorn app.main:app --reload
```

看到如下输出即成功：
```
🚀 Self-Agent 启动中 (env=dev, provider=glm)
✅ PostgreSQL 已连接 / MongoDB 已连接 / Redis 已连接 / Neo4j 已连接
✅ 基础设施就绪
Application startup complete.
Uvicorn running on http://127.0.0.1:8000
```

> 即便某些数据库没连上，服务也能启动（优雅降级），只是对应功能不可用。

---

## 第五步：验证

**交互式文档**：浏览器打开 http://localhost:8000/docs ，可直接在页面上测试接口。

**命令行测试**：
```bash
# 健康检查
curl http://localhost:8000/health

# 一次对话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "现在几点了？", "thread_id": "demo-001"}'

# 触发工具调用（天气查询）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "北京天气怎么样？", "thread_id": "demo-001"}'

# 多轮对话（同 thread_id 会记住上文）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "那上海呢？", "thread_id": "demo-001"}'
```

---

## 验证核心逻辑（无需数据库和真实 key）

如果只想快速验证 Agent 逻辑是否正常（用 Mock LLM，不依赖外部服务）：

```bash
python scripts/verify_agent.py
```

这会用模拟的 LLM 跑通完整 ReAct 循环 + 短期记忆，输出 `✅ 全部验证通过` 即代表核心代码无误。

---

## 常见问题

**Q: `docker compose up` 报 "daemon not running"？**
A: Docker Desktop 没启动。Windows 下打开 Docker Desktop 应用，等托盘图标变绿再重试。

**Q: 端口被占用（5432/27017/6379/7474/8000）？**
A: 改 `infra/docker-compose.yml` 中端口映射左侧（如 `5432:5432` → `5433:5432`），同步改 `.env`。

**Q: GLM 调用报 401？**
A: `GLM_API_KEY` 没填或填错。去 https://open.bigmodel.cn 控制台 → API Keys 复制。

**Q: Windows 下中文日志乱码？**
A: 控制台编码问题，不影响功能。可执行 `export PYTHONIOENCODING=utf-8` 或用 Windows Terminal。

**Q: 怎么彻底重置数据库？**
A: `cd infra && docker compose down -v`，然后删除 `infra/data/` 目录，再 `docker compose up -d`。
