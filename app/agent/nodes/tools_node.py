"""
工具执行节点
------------
接收 agent 节点产生的 AIMessage（含 tool_calls），
逐个执行对应工具，把结果作为 ToolMessage 追加到状态。

同时通过 writer 推送工具执行的中间事件（tool_start/tool_result），
让消费端能实时展示「正在调用 xx 工具... → 结果」。
"""

from __future__ import annotations

import uuid

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from app.agent.registry import get_tool
from app.agent.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)


async def tools_node(state: AgentState, config: RunnableConfig, writer: StreamWriter) -> dict:
    """执行最后一条 AIMessage 里的所有 tool_calls。

    通过 writer 推送 tool_start / tool_result 事件供消费端实时展示。
    """
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []

    results: list[ToolMessage] = []
    for call in tool_calls:
        name = call["name"]
        args = call.get("args", {})
        call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}"

        # 推送工具开始事件
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
                logger.exception("工具 %s 执行异常", name)
                output = f"工具执行出错：{e}"

        output_str = str(output)
        # 推送工具结果事件
        writer({"type": "tool_result", "name": name, "content": output_str[:500]})

        results.append(ToolMessage(
            content=output_str,
            tool_call_id=call_id,
            name=name,
        ))

    return {"messages": results}


def should_use_tools(state: AgentState) -> str:
    """条件路由：判断 agent 是否要调用工具。

    返回 "tools" 则进入工具节点，返回 "end" 则结束。
    """
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls:
        return "tools"
    return "end"
