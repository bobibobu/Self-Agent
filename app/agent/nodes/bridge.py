"""
LangChain 消息 ↔ 统一 LLM 模型 互转桥
--------------------------------------
LangGraph 的状态用 LangChain 的 AnyMessage（HumanMessage / AIMessage / ToolMessage），
而我们的多协议 LLM 层用统一的 ChatMessage。
本模块负责两者互转，是连接 LangGraph 与自研 LLM 层的桥梁。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.llm.models import ChatMessage, ChatRequest, ToolCall, ToolDefinition


def lc_to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """LangChain 消息 → 统一 ChatMessage。"""
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append(ChatMessage(role="system", content=str(m.content)))
        elif isinstance(m, HumanMessage):
            out.append(ChatMessage(role="user", content=str(m.content)))
        elif isinstance(m, AIMessage):
            # AIMessage 可能带 tool_calls（LangChain 格式）
            tool_calls = None
            lc_tcs = getattr(m, "tool_calls", None)
            if lc_tcs:
                tool_calls = [
                    ToolCall(id=str(tc.get("id", "")), name=tc["name"], arguments=tc.get("args", {}))
                    for tc in lc_tcs
                ]
            out.append(ChatMessage(role="assistant", content=str(m.content) or None, tool_calls=tool_calls))
        elif isinstance(m, ToolMessage):
            out.append(ChatMessage(
                role="tool",
                content=str(m.content),
                tool_call_id=str(getattr(m, "tool_call_id", "")),
                name=m.name,
            ))
        else:
            out.append(ChatMessage(role="user", content=str(m.content)))
    return out


def build_tool_definitions(tools: list[Any]) -> list[ToolDefinition]:
    """把 langchain @tool 工具转成统一的 ToolDefinition（OpenAI function schema）。"""
    defs: list[ToolDefinition] = []
    for t in tools:
        # langchain BaseTool 暴露 name / description / args_schema
        name = getattr(t, "name", str(t))
        description = getattr(t, "description", "")
        schema: dict[str, Any] = {}
        args_schema = getattr(t, "args_schema", None)
        if args_schema is not None:
            schema = args_schema.model_json_schema() if hasattr(args_schema, "model_json_schema") else {}
        defs.append(ToolDefinition(name=name, description=description, parameters=schema))
    return defs


def build_chat_request(
    messages: list[BaseMessage],
    tools: list[Any] | None,
    response_format: dict[str, Any] | None = None,
) -> ChatRequest:
    """组装一次 LLM 请求。

    response_format（可选）：OpenAI 风格的结构化输出 schema，形如
        {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}, "strict": True}}
    传入后，支持的 provider 会强制 LLM 输出符合 schema 的 JSON，治「格式幻觉」。
    """
    return ChatRequest(
        messages=lc_to_chat_messages(messages),
        tools=build_tool_definitions(tools) if tools else None,
        response_format=response_format,
    )
