"""
CLI 后端 API 客户端
-------------------
接后端的 Streamable HTTP（NDJSON）流式端点 /chat/http-stream。
逐行读取 JSON 事件，实时 yield 给上层渲染。

NDJSON 比 SSE 更适合 CLI/非浏览器：用 httpx stream 逐行读，无需解析 SSE 协议。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


async def stream_chat(
    api_url: str,
    message: str,
    thread_id: str,
    user_id: str,
    *,
    timeout: float = 120.0,
) -> AsyncIterator[dict[str, Any]]:
    """流式对话，逐事件 yield。

    用 httpx stream 逐行读 NDJSON，每行一个事件 dict。
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{api_url}/chat/http-stream",
            json={"message": message, "thread_id": thread_id, "user_id": user_id},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


async def get_json(api_url: str, path: str) -> dict[str, Any]:
    """GET 请求，返回 JSON。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{api_url}{path}")
        resp.raise_for_status()
        return resp.json()
