"""
工具执行节点
------------
接收 agent 节点产生的 AIMessage（含 tool_calls），
逐个执行对应工具，把结果作为 ToolMessage 追加到状态。

同时通过 writer 推送工具执行的中间事件（tool_start/tool_result），
让消费端能实时展示「正在调用 xx 工具... → 结果」。
"""

from __future__ import annotations

import asyncio
import uuid

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from app.agent.registry import get_tool
from app.agent.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _truncate(text: str, limit: int) -> str:
    """截断过长的工具输出。

    模型一次可能拿到 MB 级的工具结果（爬网页、读大文件、MCP 返回大 JSON），
    不截断的话单个结果就能把上下文顶爆，后续所有轮次都会连带失败。
    """
    if limit <= 0 or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n...[输出过长，已截断 {omitted} 字符]"


async def _run_one(call: dict, writer: StreamWriter, limit: int) -> ToolMessage:
    """执行单个 tool_call，任何异常都转成 ToolMessage 交回模型。"""
    name = call["name"]
    args = call.get("args", {})
    call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}"

    writer({"type": "tool_start", "name": name, "args": args})

    tool_fn = get_tool(name)
    if tool_fn is None:
        logger.warning("未知工具调用: %s", name)
        output = f"错误：未知工具 '{name}'"
    else:
        try:
            # 统一用 ainvoke：BaseTool 内部自动 dispatch 同步/异步
            output = await tool_fn.ainvoke(args)
            logger.info("工具调用 %s%s → %s", name, args, str(output)[:200])
        except Exception as e:  # noqa: BLE001
            # 工具失败不该中断整个 ReAct 循环——把错误交回模型，它可以换个参数重试
            logger.exception("工具 %s 执行异常", name)
            output = f"工具执行出错：{e}"

    output_str = _truncate(str(output), limit)
    writer({"type": "tool_result", "name": name, "content": output_str[:500]})
    return ToolMessage(content=output_str, tool_call_id=call_id, name=name)


async def tools_node(state: AgentState, config: RunnableConfig, writer: StreamWriter) -> dict:
    """执行最后一条 AIMessage 里的所有 tool_calls（并发）。

    模型一次返回多个 tool_call 时并发执行——原来是 for 循环里逐个 await，
    3 个各 2 秒的工具要跑 6 秒，现在约 2 秒。

    通过 writer 推送 tool_start / tool_result 事件供消费端实时展示。
    """
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if not tool_calls:
        return {"messages": []}

    limit = get_settings().tool_result_max_chars
    results = await asyncio.gather(*(_run_one(c, writer, limit) for c in tool_calls))
    # 顺序必须与 tool_calls 一致：OpenAI/Anthropic 都要求每个 tool_call_id
    # 有且仅有一条对应的结果消息，gather 保序正好满足
    return {"messages": list(results)}


def should_use_tools(state: AgentState) -> str:
    """条件路由：判断 agent 是否要调用工具。

    返回 "tools" 则进入工具节点，返回 "end" 则结束。
    """
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls:
        return "tools"
    return "end"
