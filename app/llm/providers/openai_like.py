"""
OpenAI 兼容协议 provider（同时支持 GLM / OpenAI）
=================================================
核心洞察：智谱 GLM 暴露了完全 OpenAI 兼容的 /chat/completions 端点，
只需把 base_url 换成智谱的，api_key 用智谱的，其余调用方式与 OpenAI 一模一样。
因此 GLM 和 OpenAI 共用同一份实现，仅配置不同。

GLM base_url：
    国内： https://open.bigmodel.cn/api/paas/v4/
    国际： https://api.z.ai/api/paas/v4/
OpenAI base_url：
    https://api.openai.com/v1/

使用 AsyncOpenAI 客户端，避免在 async 上下文里阻塞事件循环。
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

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


class OpenAILikeClient:
    """
    兼容 OpenAI 协议的 LLM 客户端。

    GLM、OpenAI、DeepSeek、Moonshot、零一万物等大部分国产/开源模型服务
    都提供 OpenAI 兼容端点，全部可用本类接入，只需换 base_url + api_key + model。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        provider_name: str = "openai_like",
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(f"{provider_name} 缺少 api_key", provider=provider_name)
        self._provider = provider_name
        self._default_model = default_model
        # timeout / max_retries 交给 SDK 内置机制：它对连接错误和 429/5xx 自带
        # 指数退避重试。没有超时的话，单次卡死的请求会一直占着连接不放。
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout if timeout is not None else 60.0,
            max_retries=max_retries if max_retries is not None else 2,
        )

    @property
    def provider_name(self) -> str:
        return self._provider

    # ---------- 消息格式转换 ----------
    def _to_openai_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """把统一 ChatMessage 转成 OpenAI 接口要求的 dict。"""
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                # 工具结果消息
                out.append({
                    "role": "tool",
                    "content": m.content or "",
                    "tool_call_id": m.tool_call_id or "",
                })
            elif m.role == "assistant" and m.tool_calls:
                # assistant 发起的工具调用
                out.append({
                    "role": "assistant",
                    "content": m.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": __import__("json").dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                })
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    def _to_openai_tools(self, request: ChatRequest) -> list[dict[str, Any]] | None:
        if not request.tools:
            return None
        return [
            {"type": "function", "function": t.model_dump()}
            for t in request.tools
        ]

    def _parse_response(self, resp, model: str) -> ChatResponse:
        """把 OpenAI 响应转成统一 ChatResponse。"""
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            import json

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = Usage()
        if resp.usage:
            usage = Usage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )

        return ChatResponse(
            content=msg.content,
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            finish_reason=choice.finish_reason or "",
            raw=None,
        )

    # ---------- 接口实现 ----------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._default_model
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=self._to_openai_messages(request.messages),  # type: ignore[arg-type]
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=self._to_openai_tools(request),
                tool_choice=request.tool_choice if request.tools else None,
            )
        except Exception as e:
            logger.exception("%s chat 调用失败", self._provider)
            raise LLMError(f"{self._provider} 调用失败: {e}", provider=self._provider) from e
        return self._parse_response(resp, model)

    async def stream_chat(self, request: ChatRequest):
        """流式对话，逐片段产出 StreamChunk。

        tool_calls 在 OpenAI 兼容协议里是**跨 chunk 的增量**：
            chunk1: tool_calls[0] = {index:0, id:"call_x", function:{name:"f", arguments:"{\\"a\\""}}
            chunk2: tool_calls[0] = {index:0, function:{arguments:":1}"}}
        每个增量带 index，按 index 把 arguments 字符串拼起来即可还原完整调用。
        聚合好的结果在流末尾一次性给出，所以调用方不需要再补一次非流式请求。
        """
        import json

        model = request.model or self._default_model
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=self._to_openai_messages(request.messages),  # type: ignore[arg-type]
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=self._to_openai_tools(request),
                tool_choice=request.tool_choice if request.tools else None,
                stream=True,
                # 让服务端在流末尾附带 usage（OpenAI 与 GLM 都支持；
                # 不支持的兼容端点会忽略该字段，此时 usage 为空，不影响主流程）
                stream_options={"include_usage": True},
            )
        except Exception as e:
            raise LLMError(f"{self._provider} 流式调用失败: {e}", provider=self._provider) from e

        # index → {id, name, args_buf}
        acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: Usage | None = None

        try:
            async for chunk in stream:
                # usage-only 的收尾 chunk 没有 choices
                if getattr(chunk, "usage", None):
                    usage = Usage(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                        total_tokens=chunk.usage.total_tokens or 0,
                    )
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                for tc in (getattr(delta, "tool_calls", None) or []):
                    # index 是增量归并的唯一依据；个别兼容端点不给 index，退化为 0
                    idx = tc.index if tc.index is not None else 0
                    slot = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if fn.name:
                            slot["name"] = fn.name
                        if fn.arguments:
                            slot["args"] += fn.arguments

                if delta.content:
                    yield StreamChunk(content=delta.content)
        except Exception as e:
            raise LLMError(f"{self._provider} 流式读取失败: {e}", provider=self._provider) from e

        # 收尾 chunk：把聚合好的 tool_calls / usage / model 一次性交出去
        tool_calls: list[ToolCall] = []
        for idx in sorted(acc):
            slot = acc[idx]
            if not slot["name"]:
                continue
            raw = slot["args"] or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                # 参数 JSON 不完整（模型被截断等）：保留原文，交由上层工具报错，
                # 不要在这里静默丢掉整个调用
                logger.warning("%s tool_call 参数解析失败：%s", self._provider, raw[:200])
                args = {"_raw": raw}
            tool_calls.append(ToolCall(
                id=slot["id"] or f"call_{idx}",
                name=slot["name"],
                arguments=args if isinstance(args, dict) else {"_raw": raw},
            ))

        yield StreamChunk(
            content="",
            tool_calls=tool_calls or None,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
        )
