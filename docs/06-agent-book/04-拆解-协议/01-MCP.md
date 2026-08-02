# 第 1 章：MCP（Model Context Protocol）

> Anthropic 2024 年提出的开放标准，连接 AI 应用与外部数据源/工具。
> 被称为「AI 应用的 USB-C」。是 Self-Agent 工具层基石。

---

## 1.1 它是什么

规范最新版 2025-03-26，地址 modelcontextprotocol.io。Anthropic 2024 年提出，现已是事实标准——Cline、Cursor、Claude Code 等都原生支持。

---

## 1.2 client-host-server 三层架构

```
┌─────────────────────────────────────────┐
│  Host（如 AI IDE、Agent 应用）            │
│  ├─ MCP Client A ──→ MCP Server A（工具集）│
│  ├─ MCP Client B ──→ MCP Server B（工具集）│
│  └─ MCP Client C ──→ MCP Server C（工具集）│
└─────────────────────────────────────────┘
```

- **Host**：运行多个 client 的应用（如 Claude Desktop、Self-Agent）
- **Client**：每个连一个 server，**1:1**
- **Server**：暴露工具/资源/提示的进程，**任何语言实现**

### 为什么 client 和 server 是 1:1

每个 server 是独立进程（隔离故障、独立升级），host 用多个 client 各连一个。一个 server 崩了不影响其他。

---

## 1.3 三大原语

| 原语 | 是什么 | 用途 |
|---|---|---|
| **Tools** | 可调用函数 | **最常用**，模型决定调用 |
| **Resources** | 可读数据（文件式） | 模型读取上下文 |
| **Prompts** | 可复用提示模板 | 标准化提示 |

Self-Agent 主要用 Tools（全书第 10 章）。

---

## 1.4 两种传输

### stdio（本地子进程，最常用）

Host 启动 server 子进程，走 stdin/stdout 管道。

```
Host ──stdin──→ Server
     ←─stdout──
```

有序列化开销（每次调用要 JSON-RPC 编解码 + 管道传输），但简单、隔离好。

### streamable-http（远程跨网络）

HTTP + SSE 流式。适合 server 在远程、跨网络的场景。

### 性能差异

MCP stdio 走子进程管道有序列化开销，内置工具是同进程函数调用。但 LLM 对话是秒级响应，这点开销可忽略。**高频调用场景**（如高频交易）应考虑内置或 http 传输。

---

## 1.5 动态发现

Client 运行时发现 server 暴露的能力，而非硬编码。

连上 server 后调 `tools/list` 拿到工具清单：

```json
{
  "tools": [
    {"name": "search_issues", "description": "...", "inputSchema": {...}},
    ...
  ]
}
```

模型才能用这些工具。这意味着 server 加了新工具，client 不用改代码就能用。

---

## 1.6 Self-Agent 怎么用 MCP（双向）

### 作为 Client（`app/mcp/client.py`）

1. 读 `mcp_servers.json` 配置
2. 用 `MultiServerMCPClient`（langchain-mcp-adapters）连接各 server
3. `get_tools()` 发现工具，转成 LangChain BaseTool
4. `refresh_from_mcp` 塞进 Agent 工具注册表

```python
class MCPClientManager:
    async def connect(self):
        servers = self._load_servers_config()
        self._client = MultiServerMCPClient(servers)
        self._tools = await self._client.get_tools()  # 发现工具
```

设计要点：
- **单个 server 连不上不阻断其他**（优雅降级）
- **工具按 server名_工具名 前缀防命名冲突**
- **懒加载**：首次 get_tools() 才连接

### 作为 Server（`app/mcp/server.py`）

```python
mcp = FastMCP("self-agent-tools")

@mcp.tool()
def some_tool(...): ...
```

把本 Agent 工具暴露出去供其他 Agent 调用。两种启动：`python -m app.mcp.server`（stdio）/ `--http`（远程）。

---

## 1.7 ★ 版本锁定决策（工程诚实）

Self-Agent 的 `pyproject.toml`：`mcp>=1.24.0,<2.0`，**锁 1.x 不用 2.0**。

### 原因

`langchain-mcp-adapters 0.3.1` 仍用 mcp 1.x 的 `RequestContext`，**未适配 mcp 2.0**（2026-07 大重构）。强行用 2.0 会导入崩溃。

### 教训

**追新不能违背兼容性现实**。等官方适配后解除上限。这是工程诚实——不为了「用最新版」引入崩溃。

`pyproject.toml` 用约束 + 注释说明，待官方适配后解除上限。

---

## 1.8 为什么用 langchain-mcp-adapters 不自己写

官方维护、经过测试、返回标准 BaseTool 无缝接入 LangGraph。

自己写要处理 MCP 协议细节（会话、JSON-RPC、schema 转换）约 150 行，没必要重复造轮子。

---

## 1.9 MCP vs function calling（详见第 4 章）

MCP 不是替代 function calling，是在它之上加了**动态发现 + 标准化 + 规模化**。function calling 是单次调用语义，MCP 是工具的发现/连接/运行的标准协议。

---

## 1.10 给 Self-Agent 的借鉴

### 借鉴①：MCP server 运行时增删

当前 MCP server 只能改配置后重启。可做成热加载——运行时增删 server，不中断服务。

### 借鉴②：MCP server 工具风险声明

MCP 发现的第三方工具，Self-Agent 默认按最高风险（EXEC）处理（保守默认）。可以让 MCP server 在工具元数据里声明风险等级，避免一刀切都问用户。

---

## 1.11 事实声明

- 三层架构、三原语、两传输、动态发现：modelcontextprotocol.io 官方规范（2025-03-26）
- Self-Agent 用法：基于本项目代码 `app/mcp/`
- 版本锁定：基于本项目 pyproject.toml

→ [下一章：A2A](02-A2A.md)
