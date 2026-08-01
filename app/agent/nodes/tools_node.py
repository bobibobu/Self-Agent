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
from langgraph.types import StreamWriter, interrupt
from opentelemetry.trace import StatusCode

from app.agent.plan import StateUpdate
from app.agent.registry import ToolRisk, get_risk, get_tool
from app.agent.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.telemetry import ATTR_TOOL_RESULT_CHARS, ATTR_TOOL_TRUNCATED, record_content, tool_span

logger = get_logger(__name__)


def _parse_decision(decision: object) -> tuple[bool, str]:
    """解析客户端回传的审批结果，兼容几种写法。

    接受：True / "approve" / "yes" / {"approved": bool, "reason": str}
    **无法识别时一律按拒绝处理**——审批环节的默认值必须是"不执行"，
    否则一个格式不对的回包就会变成静默放行。
    """
    if isinstance(decision, bool):
        return decision, "" if decision else "用户拒绝"
    if isinstance(decision, str):
        ok = decision.strip().lower() in {"approve", "approved", "yes", "y", "true", "同意"}
        return ok, "" if ok else f"用户拒绝（{decision}）"
    if isinstance(decision, dict):
        ok = bool(decision.get("approved"))
        return ok, str(decision.get("reason") or ("" if ok else "用户拒绝"))
    return False, f"无法识别的审批结果（{type(decision).__name__}），按拒绝处理"


def _truncate(text: str, limit: int) -> str:
    """截断过长的工具输出。

    模型一次可能拿到 MB 级的工具结果（爬网页、读大文件、MCP 返回大 JSON），
    不截断的话单个结果就能把上下文顶爆，后续所有轮次都会连带失败。
    """
    if limit <= 0 or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n\n...[输出过长，已截断 {omitted} 字符]"


def needs_approval(name: str) -> bool:
    """按策略判断这个工具执行前要不要问用户。

    策略（TOOL_APPROVAL_MODE）：
        auto     全部放行——仅限沙箱/CI
        gated    WRITE 与 EXEC 要问（默认）
        strict   全部都问
        readonly 只读放行，其余直接拒绝（不问，见 _denied_by_policy）
    """
    s = get_settings()
    mode = s.tool_approval_mode
    if mode == "auto":
        return False
    if name in {n.strip() for n in (s.tool_auto_approve or "").split(",") if n.strip()}:
        return False
    if mode == "strict":
        return True
    return get_risk(name) is not ToolRisk.READ


def _denied_by_policy(name: str) -> str | None:
    """readonly 模式下直接拒绝写与执行，不打扰用户。"""
    if get_settings().tool_approval_mode == "readonly" and get_risk(name) is not ToolRisk.READ:
        return (f"当前为只读模式（TOOL_APPROVAL_MODE=readonly），"
                f"拒绝执行 {get_risk(name).value} 级工具 {name}")
    return None


async def _run_one(call: dict, writer: StreamWriter, limit: int) -> tuple[ToolMessage, dict]:
    """执行单个 tool_call，任何异常都转成 ToolMessage 交回模型。"""
    name = call["name"]
    args = call.get("args", {})
    call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}"

    # 策略硬拒绝：不弹审批，直接把理由交回模型
    denial = _denied_by_policy(name)
    if denial:
        logger.warning("工具 %s 被策略拒绝", name)
        writer({"type": "tool_denied", "name": name, "reason": denial})
        return ToolMessage(content=f"错误：{denial}", tool_call_id=call_id, name=name), {}

    # 人在回路：写文件、跑命令这类不可逆操作，执行前必须让用户确认。
    # interrupt() 会挂起整张图并把 payload 抛给客户端，用户决策后
    # 以 Command(resume=...) 续跑，本函数从 interrupt() 处原地返回。
    if needs_approval(name):
        try:
            decision = interrupt({
                "type": "tool_approval",
                "tool": name,
                "risk": get_risk(name).value,
                "args": args,
                "call_id": call_id,
            })
        except RuntimeError as e:
            # interrupt() 需要图上下文与 checkpointer。拿不到就说明没法征求用户意见——
            # 此时必须**拒绝**而不是放行：审批环节失效时默认执行，
            # 等于安全机制一坏就自动全开。
            logger.error("无法发起审批（%s），按拒绝处理：%s", e, name)
            writer({"type": "tool_denied", "name": name, "reason": "审批通道不可用"})
            return ToolMessage(
                content=f"错误：{name} 需要用户审批，但当前环境无法发起审批（{e}）。已拒绝执行。",
                tool_call_id=call_id, name=name,
            ), {}
        approved, reason = _parse_decision(decision)
        if not approved:
            logger.info("用户拒绝了工具调用 %s：%s", name, reason)
            writer({"type": "tool_denied", "name": name, "reason": reason})
            # 把拒绝原因交回模型，它可以换个做法而不是硬撞
            return ToolMessage(
                content=f"用户拒绝了此操作。原因：{reason}", tool_call_id=call_id, name=name,
            ), {}

    writer({"type": "tool_start", "name": name, "args": args})

    with tool_span(name=name, call_id=call_id) as sp:
        record_content(sp, "gen_ai.tool.arguments", str(args))
        tool_fn = get_tool(name)
        if tool_fn is None:
            logger.warning("未知工具调用: %s", name)
            output = f"错误：未知工具 '{name}'"
            # 未知工具是真错误（多半是注册表与 LLM 看到的声明不一致），标红
            sp.set_status(StatusCode.ERROR, f"未知工具 {name}")
        else:
            try:
                # 统一用 ainvoke：BaseTool 内部自动 dispatch 同步/异步
                output = await tool_fn.ainvoke(args)
                logger.info("工具调用 %s%s → %s", name, args, str(output)[:200])
            except Exception as e:  # noqa: BLE001
                # 工具失败不该中断整个 ReAct 循环——把错误交回模型，它可以换个参数重试。
                # 但 span 要标红：对模型是「可恢复」，对排查的人是「这里出事了」。
                logger.exception("工具 %s 执行异常", name)
                sp.record_exception(e)
                sp.set_status(StatusCode.ERROR, str(e))
                output = f"工具执行出错：{e}"

        # 工具可以返回 StateUpdate 来同时更新图状态（如 update_plan 维护任务计划）。
        # 用统一约定而不是按工具名特判：以后再有需要改状态的工具照此返回即可。
        state_updates: dict = {}
        if isinstance(output, StateUpdate):
            state_updates = output.updates
            output = output.text

        raw = str(output)
        output_str = _truncate(raw, limit)
        sp.set_attribute(ATTR_TOOL_RESULT_CHARS, len(raw))
        sp.set_attribute(ATTR_TOOL_TRUNCATED, len(output_str) < len(raw))
        record_content(sp, "gen_ai.tool.result", output_str)

    writer({"type": "tool_result", "name": name, "content": output_str[:500]})
    if "plan" in state_updates:
        # 单独推一个事件，让客户端能把计划渲染成常驻面板而不是滚动日志
        writer({"type": "plan_updated", "plan": state_updates["plan"]})
    return ToolMessage(content=output_str, tool_call_id=call_id, name=name), state_updates


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
    messages = [msg for msg, _ in results]
    # 合并各工具产生的状态更新（如 update_plan 写入的 plan）
    updates: dict = {}
    for _, upd in results:
        updates.update(upd)
    return {"messages": messages, **updates}


def should_use_tools(state: AgentState) -> str:
    """条件路由：判断 agent 是否要调用工具。

    返回 "tools" 则进入工具节点，返回 "end" 则结束。
    """
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls:
        return "tools"
    return "end"
