"""
CLI 后端 API 客户端
-------------------
接后端的 Streamable HTTP（NDJSON）流式端点 /chat/http-stream。
逐行读取 JSON 事件，实时 yield 给上层渲染。

NDJSON 比 SSE 更适合 CLI/非浏览器：用 httpx stream 逐行读，无需解析 SSE 协议。

认证：后端 AUTH_ENABLED=true 时所有业务端点都要带 Bearer token，
所以这里统一走 auth_headers()，401 抛 AuthRequired 让上层提示 /login。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class AuthRequired(Exception):
    """需要登录（401）。上层据此提示用户执行 /login。"""


def auth_headers(token: str | None, extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _raise_for_auth(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise AuthRequired("未登录或登录已过期，请执行 /login <用户名>")


async def login(api_url: str, username: str, password: str) -> dict:
    """登录，返回 {access_token, user}。

    凭据走请求体而不是 query 参数——query string 会被服务端访问日志明文记录。
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_url}/auth/login",
            json={"username": username, "password": password},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise RuntimeError(_error_message(data, "登录失败"))
    return data


async def register(api_url: str, username: str, password: str) -> dict:
    """注册并直接返回 token。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_url}/auth/register",
            json={"username": username, "password": password},
        )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise RuntimeError(_error_message(data, "注册失败"))
    return data


def _error_message(data: Any, fallback: str) -> str:
    """业务异常是 {error, message}，FastAPI 校验失败是 {detail: [...]}，两种都兜住。"""
    if isinstance(data, dict):
        if isinstance(data.get("message"), str):
            return data["message"]
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list) and detail:
            return detail[0].get("msg", fallback)
    return fallback


async def stream_chat(
    api_url: str,
    message: str,
    thread_id: str,
    user_id: str,
    *,
    token: str | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[dict[str, Any]]:
    """流式对话，逐事件 yield。

    用 httpx stream 逐行读 NDJSON，每行一个事件 dict。
    """
    async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
        "POST",
        f"{api_url}/chat/http-stream",
        json={"message": message, "thread_id": thread_id, "user_id": user_id},
        headers=auth_headers(token),
    ) as resp:
        if resp.status_code == 401:
            raise AuthRequired("未登录或登录已过期，请执行 /login <用户名>")
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


async def get_json(
    api_url: str, path: str, *, token: str | None = None, params: dict | None = None,
) -> dict[str, Any]:
    """GET 请求，返回 JSON。

    查询参数走 params 交给 httpx 编码——手工拼字符串遇到空格/中文/& 会拼坏。
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{api_url}{path}", headers=auth_headers(token), params=params,
        )
        _raise_for_auth(resp)
        resp.raise_for_status()
        return resp.json()


async def post_json(
    api_url: str, path: str, *, token: str | None = None, params: dict | None = None,
) -> dict[str, Any]:
    """POST 请求（无 body，参数走 query），返回 JSON。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{api_url}{path}", headers=auth_headers(token), params=params)
        _raise_for_auth(resp)
        resp.raise_for_status()
        return resp.json()
