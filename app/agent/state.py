"""
Agent 状态定义
--------------
LangGraph 的核心概念：状态（State）是一个在节点间流转的 TypedDict。
每个节点接收当前状态、返回部分更新，由 reducer 合并。

`messages` 字段用 add_messages reducer：自动追加并按 ID 去重。
"""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def replace_plan(_old: list, new: list) -> list:
    """计划的 reducer：整份替换而不是追加。

    每次 update_plan 给的都是**完整的最新计划**（含各步状态），
    用 add 语义会把历次快照堆在一起。
    """
    return new


class AgentState(TypedDict):
    """Agent 流转的状态。

    Attributes:
        messages: 对话历史（含 user / assistant / tool 消息），
                  add_messages reducer 负责追加与去重。
        plan:     任务计划（多步任务的外部记事板，见 app/agent/plan.py）。
                  随 checkpointer 持久化，所以中断/续跑后还在。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    # NotRequired：历史 checkpoint 里没有这个字段，缺省也要合法
    plan: NotRequired[Annotated[list[dict], replace_plan]]
