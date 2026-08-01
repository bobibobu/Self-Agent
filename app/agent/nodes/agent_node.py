"""
Agent 节点
----------
图的核心节点：调用 LLM，决定是回复用户还是调用工具。

支持 token 级流式（LangGraph 1.2.x）：
节点签名声明 writer: StreamWriter，LangGraph 自动注入。
节点内每产出一个 token 就 writer({...}) 推出去，消费端通过
graph.astream(stream_mode=["custom","updates"], version="v2") 实时收到。

实现说明：
- 一次流式调用同时拿到文本与 tool_calls。tool_call 的跨 chunk 增量由各
  provider 在 stream_chat 内部按 index 聚合完再吐出来（见 llm/providers/）。
- 系统提示由 config["configurable"]["system_prompt"] 传入，只拼进「发给 LLM
  的这一份」消息列表，不写回 state——否则 add_messages 每轮追加一条，
  第 N 轮的 prompt 里就有 N 份系统提示。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from app.agent.nodes.bridge import build_chat_request
from app.agent.state import AgentState
from app.core.logging import get_logger
from app.core.telemetry import finish_llm_span, llm_span, record_content
from app.llm.factory import get_llm_client

logger = get_logger(__name__)


def _preview_prompt(request) -> str:
    """把请求消息压成一段可读文本，供 span 事件记录（仅在开启正文捕获时调用）。"""
    return "\n".join(f"[{m.role}] {(m.content or '')[:500]}" for m in request.messages)


async def agent_node(state: AgentState, config: RunnableConfig, writer: StreamWriter) -> dict:
    """调用 LLM 生成下一步回复（支持 token 级流式推送）。

    返回 {"messages": [AIMessage]}，由 add_messages reducer 追加。
    """
    configurable = config.get("configurable", {})
    tools = configurable.get("tools", [])
    system_prompt = configurable.get("system_prompt")

    # 上下文窗口管理：消息过长时自动压缩早期消息为摘要
    from app.agent.context_manager import compress_if_needed
    messages = await compress_if_needed(state["messages"])

    # 系统提示只在「发给 LLM 的这一份」里出现，不写回 state——
    # 否则 add_messages 每轮追加一条，历史里会堆积 N 份系统提示
    if system_prompt:
        messages = [SystemMessage(content=system_prompt), *messages]

    request = build_chat_request(messages, tools)
    llm = get_llm_client()

    logger.debug("agent_node 调用 %s，消息数=%d", llm.provider_name, len(request.messages))

    # 单次流式调用同时拿到文本与 tool_calls。
    #
    # 这里原本是「先 stream_chat 出文本，再 chat() 复查 tool_calls」——
    # 两次独立采样，成本和延迟翻倍，而且两次结果可能不一致：流式已经把完整
    # 答案推给用户了，复查却决定调工具，界面上就会出现「答案 → 工具 → 第二个答案」。
    # 现在由各 provider 在流内聚合 tool_call 增量（见 providers/*.stream_chat）。
    #
    # span 里能直接看出这个问题：一个 turn 下若出现两条 chat span，就是退化了。
    content_parts: list[str] = []
    tool_calls_list: list = []
    usage = None
    model_name = request.model or ""
    finish_reason: str | None = None

    with llm_span(
        provider=llm.provider_name,
        # 请求没显式指定 model 时用 provider 的默认模型给 span 命名
        model=model_name or getattr(llm, "default_model", "") or "unknown",
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        message_count=len(request.messages),
        streaming=True,
    ) as sp:
        record_content(sp, "gen_ai.content.prompt", _preview_prompt(request))
        async for chunk in llm.stream_chat(request):
            if chunk.content:
                content_parts.append(chunk.content)
                writer({"type": "token", "text": chunk.content})
            if chunk.tool_calls:
                tool_calls_list = chunk.tool_calls
            if chunk.usage:
                usage = chunk.usage
            if chunk.model:
                model_name = chunk.model
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason

        full_text = "".join(content_parts)
        finish_llm_span(
            sp,
            usage=usage,
            model=model_name,
            finish_reason=finish_reason,
            tool_call_count=len(tool_calls_list),
        )
        record_content(sp, "gen_ai.content.completion", full_text)

    # 构造 AIMessage
    msg_kwargs: dict[str, Any] = {
        "content": full_text,
        "additional_kwargs": {
            "model": model_name,
            "usage": usage.model_dump() if usage else {},
            "provider": llm.provider_name,
        },
    }
    if tool_calls_list:
        msg_kwargs["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in tool_calls_list
        ]
        writer({
            "type": "tool_calls",
            "calls": [{"name": tc.name, "args": tc.arguments} for tc in tool_calls_list],
        })

    ai_msg = AIMessage(**msg_kwargs)
    return {"messages": [ai_msg]}
