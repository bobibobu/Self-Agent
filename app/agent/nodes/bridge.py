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


# 工具 schema 缓存：name+description+schema类 → ToolDefinition。
# 工具注册表在运行期基本静态（启动时注册，MCP 发现后固定），
# 而 model_json_schema 是纯 CPU 的 Pydantic 遍历——实测占 /chat 热路径
# 近两成 CPU（14 个工具 × 每次 LLM 调用）。
# key 里带上 schema 类本身（langchain 的 args_schema 就是 Pydantic 模型类）：
# 同一工具重复调用命中；换了 schema 类（如 MCP 重建工具）自动失效重算。
# 注意不能写 type(args_schema)——所有 Pydantic 模型的元类都是同一个
# ModelMetaclass，起不到区分作用（tests/test_perf_optimizations.py 锁此行为）。
_tool_def_cache: dict[tuple[str, str, Any], ToolDefinition] = {}
_TOOL_DEF_CACHE_MAX = 512


def _tool_definition_cached(t: Any) -> ToolDefinition:
    name = getattr(t, "name", str(t))
    description = getattr(t, "description", "")
    args_schema = getattr(t, "args_schema", None)
    # 只有 schema 是类（标准 Pydantic 用法）才可安全做缓存 key；
    # 少见的实例型 schema 不缓存，直接现算
    cacheable = isinstance(args_schema, type)
    key = (name, description, args_schema) if cacheable else None
    if key is not None:
        cached = _tool_def_cache.get(key)
        if cached is not None:
            return cached
    schema: dict[str, Any] = {}
    if args_schema is not None:
        schema = args_schema.model_json_schema() if hasattr(args_schema, "model_json_schema") else {}
    defn = ToolDefinition(name=name, description=description, parameters=schema)
    if key is not None:
        if len(_tool_def_cache) >= _TOOL_DEF_CACHE_MAX:
            _tool_def_cache.clear()
        _tool_def_cache[key] = defn
    return defn


def build_tool_definitions(tools: list[Any]) -> list[ToolDefinition]:
    """把 langchain @tool 工具转成统一的 ToolDefinition（OpenAI function schema）。"""
    return [_tool_definition_cached(t) for t in tools]


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
