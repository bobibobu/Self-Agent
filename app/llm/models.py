"""
LLM 统一数据模型
----------------
与具体 provider（OpenAI / Anthropic）无关的消息与响应类型。
所有 provider 的实现负责把自己原生的请求/响应格式 ↔ 这套统一模型互转。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Literal

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
    """流式输出的单个片段。"""

    content: str = ""                        # 增量文本（可能为空）
    tool_calls: list[ToolCall] | None = None # 增量工具调用（多数在最后聚合）
    finish_reason: str | None = None


# 为了类型注解清晰，定义流式产出的类型别名
ChatStream = AsyncIterator[StreamChunk]
