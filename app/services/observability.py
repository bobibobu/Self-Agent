"""
可观测性（Observability）
-------------------------
收集运行时指标，通过 /metrics 端点暴露。

指标包括：
- 请求计数（按路径/状态码）
- 平均响应延迟
- 基础设施连通性

实现为纯 ASGI 中间件（不继承 BaseHTTPMiddleware），避免缓冲流式响应
（SSE/NDJSON 需要 token 逐个透传，BaseHTTPMiddleware 会破坏流式）。
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from app.db.manager import db_manager
from app.memory.checkpointer import is_checkpointer_persistent

# 指标存储（线程安全）
_lock = Lock()
_request_count: dict[str, int] = defaultdict(int)
_response_times: dict[str, list[float]] = defaultdict(list)
_start_time = time.time()


def record_request(path: str, duration_ms: float, status_code: int) -> None:
    """记录一次请求（由中间件调用）。"""
    with _lock:
        key = f"{path}:{status_code}"
        _request_count[key] += 1
        times = _response_times[path]
        times.append(duration_ms)
        if len(times) > 1000:
            del times[:500]


def get_metrics() -> dict:
    """收集并返回全部指标。"""
    with _lock:
        uptime = time.time() - _start_time
        avg_latencies = {}
        for path, times in _response_times.items():
            if times:
                avg_latencies[path] = round(sum(times) / len(times), 1)
        total_requests = sum(_request_count.values())
        req_snapshot = dict(_request_count)

    return {
        "uptime_seconds": round(uptime, 0),
        "total_requests": total_requests,
        "requests_by_path_status": req_snapshot,
        "avg_latency_ms": avg_latencies,
        "infrastructure": {
            "postgres": db_manager.postgres is not None,
            "mongo": db_manager.mongo is not None,
            "redis": db_manager.redis is not None,
            "neo4j": db_manager.neo4j is not None,
            "checkpointer_persistent": is_checkpointer_persistent(),
        },
    }


class MetricsMiddleware:
    """纯 ASGI 指标采集中间件（不缓冲响应，兼容流式）。

    记录每个请求的延迟和状态码。错误（500）也会被记录（通过异常路径）。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.time()
        status_code = 500  # 默认 500，正常路径会被覆盖

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.time() - start) * 1000
            path = scope.get("path", "unknown")
            record_request(path, duration_ms, status_code)
