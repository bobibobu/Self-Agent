"""
Agent 状态定义
--------------
LangGraph 的核心概念：状态（State）是一个在节点间流转的 TypedDict。
每个节点接收当前状态、返回部分更新，由 reducer 合并。

`messages` 字段用 add_messages reducer：自动追加并按 ID 去重。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Agent 流转的状态。

    Attributes:
        messages: 对话历史（含 user / assistant / tool 消息），
                  add_messages reducer 负责追加与去重。
    """

    messages: Annotated[list[AnyMessage], add_messages]
