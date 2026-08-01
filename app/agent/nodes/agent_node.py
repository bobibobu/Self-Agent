"""
Agent 节点
----------
图的核心节点：调用 LLM，决定是回复用户还是调用工具。

支持 token 级流式（LangGraph 1.2.x）：
节点签名声明 writer: StreamWriter，LangGraph 自动注入。
节点内每产出一个 token 就 writer({...}) 推出去，消费端通过
graph.astream(stream_mode=["custom","updates"], version="v2") 实时收到。

实现说明：
- 流式文本通过 stream_chat 逐 token 推送（真·流式，不等节点结束）
- 工具调用决策：流式过程中 OpenAI/Anthropic 的 tool_calls 是增量跨 chunk 的，
  难以可靠聚合。为正确路由，这里在文本流完后用一次非流式 chat() 复查 tool_calls。
  代价是多一次 LLM 调用，换来 ReAct 路由的可靠性。
  （优化方向：后续可改为聚合流式 tool_call 增量，省掉复查）
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from app.agent.nodes.bridge import build_chat_request
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.llm.factory import get_llm_client

logger = get_logger(__name__)


async def agent_node(state: AgentState, config: RunnableConfig, writer: StreamWriter) -> dict:
    """调用 LLM 生成下一步回复（支持 token 级流式推送）。

    返回 {"messages": [AIMessage]}，由 add_messages reducer 追加。
    """
    tools = config.get("configurable", {}).get("tools", [])
    # 上下文窗口管理：消息过长时自动压缩早期消息为摘要
    from app.agent.context_manager import compress_if_needed
    messages = await compress_if_needed(state["messages"])
    request = build_chat_request(messages, tools)
    llm = get_llm_client()

    logger.debug("agent_node 调用 %s，消息数=%d", llm.provider_name, len(request.messages))

    # 流式收集文本 token，逐个推送（真·流式）
    content_parts: list[str] = []
    finish_reason = ""
    async for chunk in llm.stream_chat(request):
        if chunk.content:
            content_parts.append(chunk.content)
            writer({"type": "token", "text": chunk.content})
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason

    full_text = "".join(content_parts)

    # 工具调用决策：用一次非流式调用可靠获取 tool_calls
    # （流式的 tool_calls 增量跨 chunk，聚合逻辑因 provider 而异，不可靠）
    resp = await llm.chat(request)
    tool_calls_list = resp.tool_calls
    # 若流式有文本但非流式无文本，保留流式文本
    if not full_text and resp.content:
        full_text = resp.content
        # 这种情况（非流式有文本但流式没收到）推送一次完整文本
        writer({"type": "token", "text": full_text})

    # 构造 AIMessage
    msg_kwargs: dict[str, Any] = {
        "content": full_text,
        "additional_kwargs": {
            "model": resp.model,
            "usage": resp.usage.model_dump() if resp.usage else {},
            "provider": llm.provider_name,
        },
    }
    tool_calls = [
        {"id": tc.id, "name": tc.name, "args": tc.arguments}
        for tc in tool_calls_list
    ]
    if tool_calls:
        msg_kwargs["tool_calls"] = tool_calls
        writer({"type": "tool_calls", "calls": [{"name": tc.name, "args": tc.arguments} for tc in tool_calls_list]})

    ai_msg = AIMessage(**msg_kwargs)
    return {"messages": [ai_msg]}
