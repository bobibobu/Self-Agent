"""
LLM 统一数据模型
----------------
与具体 provider（OpenAI / Anthropic）无关的消息与响应类型。
所有 provider 的实现负责把自己原生的请求/响应格式 ↔ 这套统一模型互转。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------- 消息 ----------------


class ToolCall(BaseModel):
    """模型发起的一次工具调用请求。"""

    id: str                           # 调用 ID（用于把工具结果回填给模型）
    name: str                         # 工具名
    arguments: dict[str, Any]         # 工具参数（已解析的 dict）


class ChatMessage(BaseModel):
    """统一的对话消息。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    # 仅 assistant 携带：模型要调用的工具
    tool_calls: list[ToolCall] | None = None
    # 仅 tool 携带：回填的工具结果对应的调用 ID
    tool_call_id: str | None = None
    name: str | None = None           # tool 消息的工具名


# ---------------- 工具定义 ----------------


class ToolDefinition(BaseModel):
    """暴露给模型的工具 schema（OpenAI function 格式）。"""

    name: str
    description: str
    parameters: dict[str, Any]        # JSON Schema


# ---------------- 响应 ----------------


class Usage(BaseModel):
    """token 用量与成本估算。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatRequest(BaseModel):
    """统一的对话请求。"""

    messages: list[ChatMessage]
    model: str | None = None            # None 则用 provider 默认模型
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: str = "auto"           # auto / none / required / 具体工具名
    # ★ 结构化输出契约（2026-08）：要求 LLM 返回符合该 JSON Schema 的对象。
    # OpenAI/GLM 用 response_format={"type":"json_schema","json_schema":{...}}，
    # Anthropic 用 tool_use 约束（见 providers/anthropic.py）。
    # None 表示自由文本输出（默认，向后兼容）。这是治「格式幻觉」的手段——
    # 让模型必须输出合法 JSON，而非可能拼错的裸文本。注意它治格式不治内容：
    # 一个语法合法的 JSON 仍可能含编造的值。
    response_format: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    """一次完整的（非流式）LLM 响应。"""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    finish_reason: str = ""
    raw: Any | None = Field(None, description="原始 provider 响应，调试用")


# ---------------- 流式片段 ----------------


class StreamChunk(BaseModel):
    """流式输出的单个片段。

    tool_calls / usage / model 只在**流结束时的最后一个 chunk**上出现：
    provider 内部把跨 chunk 的 tool_call 增量按 index 聚合完再一次性给出，
    这样调用方一次流式请求就能同时拿到文本和工具调用决策，
    不需要再补一次非流式调用去「复查」。
    """

    content: str = ""                        # 增量文本（可能为空）
    tool_calls: list[ToolCall] | None = None # 聚合完成的工具调用（仅末尾 chunk）
    finish_reason: str | None = None
    usage: Usage | None = None               # token 用量（仅末尾 chunk）
    model: str = ""                          # 实际使用的模型（仅末尾 chunk）


# 为了类型注解清晰，定义流式产出的类型别名
ChatStream = AsyncIterator[StreamChunk]
