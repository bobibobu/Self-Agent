"""
限流中间件（Redis 滑动窗口）
----------------------------
按用户（已认证）或 IP（未认证）做请求频率限制，防止滥用。

机制：
- 每个请求进来，以 "rate:{identity}:{minute}" 为 key 在 Redis 计数
- 超过阈值返回 429 Too Many Requests
- Redis 不可用时放行（不因限流组件故障阻断服务）

实现为纯 ASGI 中间件（不继承 BaseHTTPMiddleware），避免缓冲流式响应。
"""

from __future__ import annotations

import time

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)

_EXEMPT_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json", "/auth/login", "/auth/register"}


class RateLimitMiddleware:
    """按用户/IP 的滑动窗口限流（纯 ASGI，兼容流式）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        s = get_settings()
        path = scope.get("path", "")

        # 豁免路径直接放行
        if not s.rate_limit_enabled or path in _EXEMPT_PATHS or path.startswith("/.well-known") or path.startswith("/uploads"):
            return await self.app(scope, receive, send)

        identity = _get_identity(scope)
        window_key = f"rate:{identity}:{int(time.time() // 60)}"

        # Redis 计数
        redis = db_manager.redis
        if redis is not None:
            try:
                count = await redis.incr(window_key)
                if count == 1:
                    await redis.expire(window_key, 65)
                if count > s.rate_limit_per_minute:
                    logger.warning("限流触发 identity=%s count=%d", identity, count)
                    await _send_429(send)
                    return
            except Exception as e:  # noqa: BLE001
                logger.debug("限流检查失败（放行）：%s", e)

        await self.app(scope, receive, send)


async def _send_429(send) -> None:
    """发送 429 响应。"""
    import orjson

    body = orjson.dumps({
        "error": "RATE_LIMITED",
        "message": "请求过于频繁",
        "retry_after": 60,
    })
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            [b"content-type", b"application/json"],
            [b"retry-after", b"60"],
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _get_identity(scope: dict) -> str:
    """从 ASGI scope 提取限流身份：JWT sub > 直连 IP。"""
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore")
    if auth.lower().startswith("bearer "):
        try:
            from app.auth.jwt_service import decode_token
            payload = decode_token(auth[7:])
            return "u:" + payload.get("sub", "unknown")
        except Exception:  # noqa: BLE001
            pass
    # 直连 IP（不信任 X-Forwarded-For，防伪造绕过限流）
    client = scope.get("client")
    return "ip:" + (client[0] if client else "unknown")
