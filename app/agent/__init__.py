"""
LangGraph 核心 Agent
=====================
基于 LangGraph 状态图实现 ReAct（Reasoning + Acting）循环：
    用户消息 → [agent节点: LLM思考] → 是否要调用工具？
                          ├─ 是 → [tools节点: 执行工具] → 回到 agent节点
                          └─ 否 → 结束

关键设计：因为 LLM 用自研多协议抽象层（非 LangChain ChatModel），
所以这里手动构建状态图，而非使用 create_react_agent。
这样能完全掌控消息格式转换、流式输出与短期记忆接入。
"""
