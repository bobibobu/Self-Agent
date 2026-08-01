"""
A2A（Agent2Agent）协议集成
==========================
A2A 是 Google/Linux Foundation 主导的开放标准，让独立 Agent 之间能互相发现与协作。
与 MCP 互补：MCP 是 agent↔tool，A2A 是 agent↔agent。

本模块实现 A2A 的两个方向：
- **server**：把本 Agent 暴露为标准 A2A agent（其他 Agent 可通过 JSON-RPC 与它对话）
- **client**：本 Agent 作为客户端，发现并调用其他 A2A agent

协议要点：
- 传输：JSON-RPC 2.0 over HTTP，SSE 流式
- 发现：Agent Card 在 /.well-known/agent-card.json（v1.0 协议路径）
- 语义：Agent 之间是「不透明对等体」——共享输入输出，不共享内部工具/记忆

架构关系：
    ┌──────────┐   A2A    ┌──────────────┐
    │ 本 Agent │ ←──────→ │ 其他 Agent   │ (如：翻译Agent、分析Agent)
    └──────────┘          └──────────────┘
         │  也可作为 A2A server 被外部调用
         ▼
    ┌──────────────┐
    │ 外部 Agent   │
    └──────────────┘
"""
