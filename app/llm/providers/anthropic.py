"""
Anthropic 原生协议 provider
============================
Anthropic 的消息格式与 OpenAI 有几处关键差异：
1. system 消息是顶层参数，不混在 messages 数组里
2. 工具调用：assistant 用 content blocks (type=tool_use)，
   工具结果用 role=user + content blocks (type=tool_result)
3. usage 字段名不同：input_tokens / output_tokens

本类负责这些互转，对外仍暴露统一的 chat / stream_chat。
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    ToolCall,
    Usage,
)

logger = get_logger(__name__)


class AnthropicClient:
    """Anthropic 原生协议客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("anthropic 缺少 api_key", provider="anthropic")
        self._default_model = default_model
        # 同 OpenAI provider：超时与重试交给 SDK 内置机制
        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout if timeout is not None else 60.0,
            max_retries=max_retries if max_retries is not None else 2,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._default_model

    # ---------- 消息格式转换 ----------
    def _split_system(self, messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
        """Anthropic 的 system 是顶层参数，需从消息列表里抽出来。"""
        system_parts = [m.content or "" for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        return "\n\n".join(system_parts), rest

    def _to_anthropic_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """把统一消息转成 Anthropic 的 content-blocks 格式。"""
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant" and m.tool_calls:
                # assistant 的工具调用：content blocks
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:

                    blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                out.append({"role": "assistant", "content": blocks})
            elif m.role == "assistant":
                out.append({"role": "assistant", "content": m.content or ""})
            elif m.role == "tool":
                # 工具结果在 Anthropic 里是 user 角色 + tool_result block
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content or "",
                    }],
                })
        return out

    def _to_anthropic_tools(self, request: ChatRequest) -> list[dict[str, Any]] | None:
        if not request.tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters or {"type": "object", "properties": {}},
            }
            for t in request.tools
        ]

    def _parse_response(self, resp, model: str) -> ChatResponse:
        """把 Anthropic 响应转成统一 ChatResponse。"""

        content_text: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                content_text.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {"_raw": block.input},
                ))

        usage = Usage()
        if resp.usage:
            usage = Usage(
                prompt_tokens=getattr(resp.usage, "input_tokens", 0),
                completion_tokens=getattr(resp.usage, "output_tokens", 0),
                total_tokens=getattr(resp.usage, "input_tokens", 0) + getattr(resp.usage, "output_tokens", 0),
            )

        return ChatResponse(
            content="\n".join(content_text) if content_text else None,
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            finish_reason=resp.stop_reason or "",
            raw=None,
        )

    # ---------- 接口实现 ----------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._default_model
        system, msgs = self._split_system(request.messages)
        try:
            resp = await self._client.messages.create(
                model=model,
                system=system,
                messages=self._to_anthropic_messages(msgs),
                temperature=request.temperature,
                max_tokens=request.max_tokens or 4096,
                tools=self._to_anthropic_tools(request),
            )
        except Exception as e:
            logger.exception("anthropic chat 调用失败")
            raise LLMError(f"anthropic 调用失败: {e}", provider="anthropic") from e
        return self._parse_response(resp, model)

    async def stream_chat(self, request: ChatRequest):
        """流式对话。Anthropic 用 events 流，这里聚合为 StreamChunk。

        SDK 的 get_final_message() 已经帮我们把 tool_use block 的
        input_json_delta 聚合好了，直接复用 _parse_response 解析即可——
        原实现拿到 final 却只取了 stop_reason，把 tool_use 丢了，
        所以上层才不得不再补一次非流式调用。
        """
        model = request.model or self._default_model
        system, msgs = self._split_system(request.messages)
        try:
            async with self._client.messages.stream(
                model=model,
                system=system,
                messages=self._to_anthropic_messages(msgs),
                temperature=request.temperature,
                max_tokens=request.max_tokens or 4096,
                tools=self._to_anthropic_tools(request),
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(content=text)
                final = await stream.get_final_message()
        except Exception as e:
            raise LLMError(f"anthropic 流式调用失败: {e}", provider="anthropic") from e

        parsed = self._parse_response(final, model)
        yield StreamChunk(
            content="",
            tool_calls=parsed.tool_calls or None,
            finish_reason=parsed.finish_reason,
            usage=parsed.usage,
            model=model,
        )
