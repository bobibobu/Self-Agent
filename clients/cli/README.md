# Self-Agent CLI 客户端

类 Claude Code 的命令行交互式对话客户端，接后端 Streamable HTTP（NDJSON）流式接口。

## 特性

- **真·token 级流式输出**：逐字实时渲染（rich Live）
- **工具调用过程实时展示**：决定调用 → 执行中 → 结果
- **命令系统**：`/new` `/user` `/tools` `/memory` `/profile` `/status` `/help` `/exit`
- **Markdown 渲染**：rich 渲染最终回复
- **输入历史**：上下键回溯历史输入

## 安装与启动

```bash
cd clients/cli
pip install -e .          # 安装（注册 selfagent 命令）

# 先启动后端（项目根目录）
cd ../../
uv run uvicorn app.main:app --reload

# 使用
selfagent                 # 交互式 REPL
selfagent "你好"          # 单次查询
```

## 命令一览

| 命令 | 说明 |
|---|---|
| `/new` | 开始新对话（重置会话 ID） |
| `/user <id>` | 设置用户 ID（影响记忆/画像） |
| `/tools` | 列出可用工具 |
| `/memory <关键词>` | 查询当前用户的长期记忆 |
| `/profile [id]` | 查看用户画像 |
| `/status` | 查看当前会话状态 |
| `/help` | 帮助 |
| `/exit` | 退出 |

## 配置

后端地址通过环境变量：
```bash
# PowerShell
$env:AGENT_API_URL = "http://localhost:8000"

# CMD
set AGENT_API_URL=http://localhost:8000
```

## 工作原理

```
CLI ──POST /chat/http-stream──→ 后端（NDJSON 流）
     httpx stream 逐行读          ↓
     每行一个 JSON 事件         LangGraph stream_chat
     rich Live 实时渲染
```

NDJSON（每行一个 JSON）比 SSE 更适合 CLI：httpx 原生支持逐行读取，无需解析 SSE 协议格式。

## 为什么 CLI 用 NDJSON 而 Web 用 SSE？

- **SSE**：浏览器有原生 EventSource，但只支持 GET；Web 用 fetch+ReadableStream 手动解析
- **NDJSON**：CLI 用 httpx 逐行读最简单，无需事件协议解析，更轻量

两种传输后端共用同一个 `stream_agent` 生成器，只是编码不同。
