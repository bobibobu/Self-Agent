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
# app/mcp/client.py 核心（langchain.mcp，底层 fastmcp 4.x + mcp 2.x）
from langchain.mcp import MCPAdapter

adapter = MCPAdapter({"mcpServers": {
    "filesystem": {"command": "npx", "args": ["..."]},   # 有 command → stdio
    "search": {"url": "http://..."},                      # http(s) URL → streamable-http
}})
await adapter.__aenter__()            # 进入上下文并保持连接，session 跨请求可用
tools = await adapter.list_tools()    # → list[BaseTool]，无缝接入 Agent
```

`list_tools()` 返回的是标准 LangChain `BaseTool`，**直接塞进我们的工具注册表**，Agent 的 tools_node 零改动就能用。
`mcp_servers.json` 里的 `{"servers": {...}}` 由 `MCPClientManager._to_mcp_config()` 翻译成上面的标准格式。

### Server：暴露自身工具

```python
# app/mcp/server.py 核心（独立包 fastmcp；mcp 2.0 已移除内置的 mcp.server.fastmcp）
from fastmcp import FastMCP

mcp = FastMCP("self-agent-tools")

for tool in ALL_TOOLS:                       # 内置 LangChain 工具逐一暴露
    wrapper = _build_typed_wrapper(tool)     # 按 args_schema 生成带类型签名的包装
    mcp.tool(name=tool.name, description=tool.description)(wrapper)
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

**降级行为（当前实现）**：MCP 工具发现是整批的——任何一个 server 连不上，本轮所有 MCP 工具都会被丢弃（内置工具不受影响，Agent 整体仍可用），启动日志有 WARNING。按 server 粒度隔离失败是已知改进项（`app/mcp/client.py` 的 connect()）。

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

## 五、版本策略（2026-09 已迁移到 MCP 2.x）

本项目 MCP 相关依赖版本：

| 包 | 版本 | 说明 |
|---|---|---|
| `mcp` | **2.3.0**（2.x） | 2026-07-28 规范大版本：stateless core、extensions、Tasks（SEP-2663 尚未随 SDK 落地） |
| `langchain[mcp]` | **1.4.6** | 官方桥接迁入 langchain 主包 `langchain.mcp` 命名空间（`langchain-mcp-adapters` 仓库已于 2026-09-17 归档） |
| `fastmcp` | **4.1.1** | `langchain[mcp]` extra 的实际底层（独立维护的 FastMCP 框架）；server 侧也用它 |

> 版本号为 2026-10-19 `uv lock --upgrade` 后的锁定值，后续由 Renovate 跟进，以 `uv.lock` 为准。

**迁移了什么：**

- **Client 侧**（`app/mcp/client.py`）：`MultiServerMCPClient(servers).get_tools()`
  → `MCPAdapter(mcp_config).list_tools()`。配置从 `{"servers": {...}}` 翻译成
  fastmcp 的标准 `{"mcpServers": {...}}`（stdio 看 command、http 看 url，无需显式 transport）。
  adapter 在 connect 时进入异步上下文并**保持连接**，disconnect 时退出——
  工具的 session 跨请求可用。
- **Server 侧**（`app/mcp/server.py`）：官方 mcp SDK 2.0 移除了内置 FastMCP
  （`mcp.server.fastmcp` 导入会指向迁移指南），改用独立包 `from fastmcp import FastMCP`
  （装饰器 API 兼容，`mcp.run(transport="http", host=..., port=...)`）。
- **顺手修掉一个隐患**：旧实现用 `async def _wrapped(**kwargs)` 注册工具——
  `**kwargs` 签名推不出参数 schema，注册出去的是**无参工具**。现在从
  LangChain 工具的 `args_schema` 动态生成带真实类型签名的包装函数
  （fastmcp 用 `inspect.signature` + `get_type_hints` 推导 schema）。

**stdio 的铁律（本次迁移踩到的真坑）：**

stdout 被 JSON-RPC 协议独占。任何落进 stdout 的日志行都会被 client 当成
协议响应，直接 `Connection closed`。因此：

- 全局日志根通道走 **stderr**（`app/core/logging.py`，12-factor 惯例）；
- stdio 模式启动加 `show_banner=False`；
- 测试 `tests/test_mcp_v2.py::test_cross_process_stdio_roundtrip` 用真实
  stdio 子进程钉住这条规则。

**注意**：`langchain.mcp` 目前是 beta（API 可能变动），locked 在
`langchain[mcp]>=1.4.2,<2.0` 上界内随小版本跟进。

---

## 六、面试要点

**Q: MCP 和 A2A 有什么区别？**
A: MCP 是 **agent↔tool**（Agent 调用工具），A2A 是 **agent↔agent**（Agent 之间协作）。互补关系，本 Agent 既能用 MCP 调工具，也能（Phase 4）用 A2A 与其他 Agent 通信。

**Q: 为什么用 langchain.mcp（原 langchain-mcp-adapters）而不自己写桥接？**
A: 官方维护、经过测试、返回标准 BaseTool 无缝接入 LangGraph。自己写要处理 MCP 协议细节（会话、JSON-RPC、工具 schema 转换），约 150 行，没必要重复造轮子。原独立包已归档并迁入 langchain 主包的 `langchain.mcp` 命名空间（底层 fastmcp 4.x + mcp 2.x），本项目已跟进迁移。

**Q: MCP 工具和内置工具有性能差异吗？**
A: 有。MCP stdio 传输走子进程管道，有序列化开销；内置工具是同进程函数调用。但对 LLM 对话场景（秒级响应），这点开销可忽略。若工具调用极频繁（如高频交易），应考虑内置或 http 传输。
