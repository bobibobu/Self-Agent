"""
任务计划（Plan / TODO）
=======================
单层 ReAct 循环扛不住「把这个模块重构一遍」这类任务：模型走到第七八步
就开始忘记最初要做什么，或者反复做同一件事直到撞上 recursion_limit。

解决办法不是加更多提示词，而是给它一块**外部记事板**：
把计划写下来、随进展更新状态。这样每一轮的上下文里都有一份
「全局要做什么 / 现在做到哪 / 还剩什么」，不依赖模型自己记住。

顺带解决用户侧的问题——长任务跑起来之后，人能看到它到底打算干什么，
而不是盯着一堆工具调用猜。

设计要点：
- 计划存在**图状态**里（随 checkpointer 持久化），不是存在提示词里，
  所以中断、续跑、换进程之后都还在。
- 同一时刻只允许一个 in_progress。允许多个的话，模型会把所有步骤
  一次性标成进行中，记事板就退化成了一张静态清单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.tools import tool

from app.core.logging import get_logger

logger = get_logger(__name__)

PlanStatus = Literal["pending", "in_progress", "completed"]
_VALID_STATUS = ("pending", "in_progress", "completed")

_STATUS_ICON = {"pending": "○", "in_progress": "▶", "completed": "✔"}

MAX_STEPS = 30


@dataclass
class StateUpdate:
    """工具的返回值容器：既给模型一段文本，又更新图状态。

    tools_node 认得这个类型：用 .text 构造 ToolMessage，把 .updates
    合并进节点返回的状态增量。比按工具名特判要通用，新工具想改状态
    照这个约定返回即可。
    """

    text: str
    updates: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # 兜底：万一被当普通结果处理也不会丢信息
        return self.text


def normalize(raw: Any) -> tuple[list[dict], str | None]:
    """校验并规整模型给的计划。返回 (计划, 错误信息)。

    模型给的东西千奇百怪，这里统一收口：
    非列表、缺字段、状态拼错、多个 in_progress —— 都在这里挡掉并
    把原因说清楚，让模型自己改，而不是塞一份坏数据进状态。
    """
    if not isinstance(raw, list):
        return [], "steps 必须是一个数组"
    if not raw:
        return [], "计划不能为空；任务结束时请把所有步骤标为 completed"
    if len(raw) > MAX_STEPS:
        return [], f"步骤过多（{len(raw)} > {MAX_STEPS}），请合并成更粗的粒度"

    steps: list[dict] = []
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"content": item, "status": "pending"}
        if not isinstance(item, dict):
            return [], f"第 {i} 步格式不对：应为 {{content, status}}"
        content = str(item.get("content") or "").strip()
        if not content:
            return [], f"第 {i} 步缺少 content"
        status = str(item.get("status") or "pending").strip()
        if status not in _VALID_STATUS:
            return [], f"第 {i} 步的 status='{status}' 无效，只能是 {'/'.join(_VALID_STATUS)}"
        steps.append({"id": str(i), "content": content[:200], "status": status})

    running = [s for s in steps if s["status"] == "in_progress"]
    if len(running) > 1:
        # 允许多个进行中的话，模型会把所有步骤一次性标成进行中，
        # 记事板就退化成一张静态清单，起不到"现在做到哪"的作用
        return [], f"同一时刻只能有一个步骤处于 in_progress，现在有 {len(running)} 个"

    return steps, None


def render(steps: list[dict]) -> str:
    """把计划渲染成模型和人都好读的形式。"""
    if not steps:
        return "（暂无计划）"
    done = sum(1 for s in steps if s["status"] == "completed")
    lines = [f"任务计划（{done}/{len(steps)} 已完成）"]
    for s in steps:
        lines.append(f"  {_STATUS_ICON.get(s['status'], '○')} {s['content']}")
    return "\n".join(lines)


@tool
async def update_plan(steps: list[dict]) -> StateUpdate:
    """创建或更新任务计划。多步骤任务必须先用它列出计划，之后随进展更新。

    什么时候用：任务需要三步以上、或涉及多个文件时，先调用它列出计划；
    每完成一步就再调一次，把该步标为 completed、下一步标为 in_progress。
    单步的简单任务不需要用。

    Args:
        steps: 步骤数组，每项形如
            {"content": "读取并理解 app/main.py", "status": "completed"}
            status 取值：pending（待办）/ in_progress（进行中）/ completed（已完成）
            同一时刻只能有一个步骤是 in_progress。
    """
    normalized, err = normalize(steps)
    if err:
        return StateUpdate(text=f"计划未更新：{err}")

    logger.info("计划已更新（%d 步，%d 完成）",
                len(normalized), sum(1 for s in normalized if s["status"] == "completed"))
    return StateUpdate(text=render(normalized), updates={"plan": normalized})


PLAN_TOOLS = [update_plan]
