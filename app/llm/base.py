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

    @property
    def default_model(self) -> str:
        """未在请求里显式指定 model 时使用的默认模型名。

        追踪层要用它给 span 命名（GenAI 约定是 `chat {model}`）。
        暴露成协议的一部分，免得调用方去摸各实现的私有属性。
        """
        ...

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """一次性（非流式）对话。"""
        ...

    def stream_chat(self, request: ChatRequest) -> ChatStream:
        """流式对话，返回异步迭代器，逐片段产出。

        注意这里**不是** `async def`：各 provider 的实现都是异步生成器
        （`async def` + `yield`），调用后直接返回 AsyncIterator 而非协程，
        所以协议签名必须是普通函数返回 ChatStream。
        写成 `async def ... -> ChatStream` 会让类型检查认为要先 await 一次，
        与 `async for chunk in llm.stream_chat(req)` 的真实用法对不上。
        """
        ...
