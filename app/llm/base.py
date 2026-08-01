"""
LLM 客户端统一接口（Protocol）
------------------------------
所有 provider 实现都遵循这套接口，上层 Agent 只依赖 `LLMClient`，
不感知底层是 GLM、OpenAI 还是 Anthropic。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.llm.models import ChatRequest, ChatResponse, ChatStream


@runtime_checkable
class LLMClient(Protocol):
    """LLM 客户端统一契约。"""

    @property
    def provider_name(self) -> str:
        """provider 标识，如 'glm' / 'openai' / 'anthropic'。"""
        ...

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """一次性（非流式）对话。"""
        ...

    async def stream_chat(self, request: ChatRequest) -> ChatStream:
        """流式对话，返回异步迭代器，逐片段产出。"""
        ...
