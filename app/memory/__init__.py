"""
记忆系统
========
短期记忆：保存单次对话（thread）内的状态，支持多轮上下文。
长期记忆：跨会话的用户记忆（Phase 3 接入）。

短期记忆用 LangGraph 的 checkpointer 实现：
- MemorySaver：进程内，重启丢失（开发/测试用）
- PostgresSaver：Postgres 持久化（生产用，重启不丢）
"""
