"""
MCP（Model Context Protocol）集成
==================================
MCP 是 Anthropic 提出的开放标准，被誉为「AI 应用的 USB-C」：
让 Agent 与外部工具/资源用统一协议互通，解耦工具实现与 Agent 逻辑。

本模块实现 MCP 的两个方向：
- **client**：连接外部 MCP server，把它们的工具纳入本 Agent 可用工具集
- **server**：用 FastMCP 把本 Agent 的内置工具暴露出去，供其他 Agent 调用

架构关系：
    ┌──────────┐   MCP(client)   ┌────────────────┐
    │ 本 Agent │ ──────────────→ │ 外部 MCP server │ (如：文件系统、数据库、搜索)
    │          │ ←────────────── │  的工具         │
    └──────────┘                 └────────────────┘
         │
         │ MCP(server)
         ▼
    ┌────────────────┐
    │ 其他 Agent     │ 也能调用本 Agent 的工具
    └────────────────┘

桥接库：langchain-mcp-adapters 把 MCP 工具转成 LangChain BaseTool，
无缝接入我们已有的 tools_node（零改动）。
"""
