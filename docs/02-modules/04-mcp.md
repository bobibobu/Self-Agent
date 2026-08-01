# MCP 协议集成

> MCP（Model Context Protocol）是 Anthropic 提出的开放标准，被称为「AI 应用的 USB-C」。本模块讲清楚：MCP 是什么、Self-Agent 怎么用、为什么这样设计。

---

## 一、MCP 是什么？

**一句话**：让 Agent 与外部工具/资源用统一协议通信的标准。

传统痛点：每个 Agent 框架（LangChain、AutoGen、各家私有框架）工具接口各不相同，写一个工具要在 N 个框架里适配 N 次。

MCP 解决：定义一套**统一的工具发现 + 调用协议**。任何 MCP server 暴露的工具，任何 MCP client（Agent）都能用。

```
┌──────────┐                    ┌─────────────┐
│  Agent   │  ── MCP 协议 ──→  │ MCP server  │
│ (client) │  ←─ JSON-RPC ──    │ (工具集合)   │
└──────────┘                    └─────────────┘
  任何框架                          任何语言
```

类比：USB-C 接口统一了充电线；MCP 统一了 Agent 的工具接口。

---

## 二、两个方向：Client 与 Server

Self-Agent 同时是工具的**使用者**和**提供者**：

| 角色 | 文件 | 职责 |
|---|---|---|
| **MCP Client** | `app/mcp/client.py` | 连接外部 MCP server，发现并调用它们的工具 |
| **MCP Server** | `app/mcp/server.py` | 把本 Agent 的工具暴露出去，供其他 Agent 调用 |

### Client：连接外部工具

```python
# app/mcp/client.py 核心
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "filesystem": {"transport": "stdio", "command": "npx", "args": ["..."]},
    "search": {"transport": "http", "url": "http://..."},
})
tools = await client.get_tools()  # → list[BaseTool]，无缝接入 Agent
```

`get_tools()` 返回的是标准 LangChain `BaseTool`，**直接塞进我们的工具注册表**，Agent 的 tools_node 零改动就能用。

### Server：暴露自身工具

```python
# app/mcp/server.py 核心
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("self-agent-tools")

@mcp.tool()
def calculator(expression: str) -> str:
    """数学计算。"""
    ...
```

启动方式：
```bash
python -m app.mcp.server          # stdio 传输（本地）
python -m app.mcp.server --http   # streamable-http 传输（远程可访问）
```

---

## 三、配置外部 MCP Server

复制 `mcp_servers.json.example` 为 `mcp_servers.json`，按需启用：

```json
{
  "servers": {
    "filesystem": {
      "enabled": true,
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    },
    "remote": {
      "enabled": true,
      "transport": "http",
      "url": "http://other-host:9000/mcp"
    }
  }
}
```

支持的 transport：
- `stdio`：本地子进程（最常用，如官方文件系统、GitHub server）
- `http`：streamable-http（远程，跨网络）

**优雅降级**：某个 server 连不上只告警，不影响其他和 Agent 整体运行。

---

## 四、关键架构：工具注册表（单一真相来源）

```
内置工具 ──┐
MCP 工具 ──┼──→ app.agent.registry（统一注册表）──→ Agent tools_node
Skill 工具 ┘
```

所有工具汇聚到 `registry.py`，tools_node 只从这里查找。
好处：**无论工具来源（内置/MCP/Skill），执行路径完全一致**。

---

## 五、版本策略（重要决策）

本项目 MCP 相关依赖版本：

| 包 | 版本 | 说明 |
|---|---|---|
| `mcp` | **1.29.0**（1.x 最新） | 2.0 是 2026-07 大重构版 |
| `langchain-mcp-adapters` | **0.3.1**（最新） | 官方桥接库 |

**为什么 mcp 锁 1.x 而不用 2.0？**

`langchain-mcp-adapters 0.3.1`（PyPI 最新 + GitHub main 分支）仍使用 mcp 1.x 的 `RequestContext`，**尚未适配 mcp 2.0**。若强行用 mcp 2.0 会导致导入崩溃。

已在 `pyproject.toml` 中用 `mcp>=1.24.0,<2.0` 约束并注释说明。待官方适配后解除上限即可。

这是工程权衡的典型案例：**追新不能违背兼容性现实**。

---

## 六、面试要点

**Q: MCP 和 A2A 有什么区别？**
A: MCP 是 **agent↔tool**（Agent 调用工具），A2A 是 **agent↔agent**（Agent 之间协作）。互补关系，本 Agent 既能用 MCP 调工具，也能（Phase 4）用 A2A 与其他 Agent 通信。

**Q: 为什么用 langchain-mcp-adapters 而不自己写桥接？**
A: 官方维护、经过测试、返回标准 BaseTool 无缝接入 LangGraph。自己写要处理 MCP 协议细节（会话、JSON-RPC、工具 schema 转换），约 150 行，没必要重复造轮子。

**Q: MCP 工具和内置工具有性能差异吗？**
A: 有。MCP stdio 传输走子进程管道，有序列化开销；内置工具是同进程函数调用。但对 LLM 对话场景（秒级响应），这点开销可忽略。若工具调用极频繁（如高频交易），应考虑内置或 http 传输。
