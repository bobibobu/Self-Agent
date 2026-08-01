"""
结构化日志
----------
统一日志格式，含 trace_id 便于全链路追踪。
所有模块通过 `get_logger(__name__)` 获取 logger。
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

from app.core.config import get_settings

# 全链路追踪 ID（每次请求注入，日志自动带上）
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class TraceIdFilter(logging.Filter):
    """把当前 trace_id 注入到每条日志记录中。

    优先用 OpenTelemetry 活动 span 的 trace_id：这样同一个 id 既能在日志里
    grep，也能直接在 Jaeger/Tempo 里搜到对应的调用树，日志与链路对得上。
    没有活动 span（未启用追踪、或在后台任务里）时回退到自己生成的 id。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _otel_trace_id() or trace_id_var.get()
        return True


def _otel_trace_id() -> str | None:
    """取当前 OTel span 的 trace_id，未启用追踪时返回 None。"""
    try:
        from app.core.telemetry import current_trace_id

        return current_trace_id()
    except Exception:  # noqa: BLE001
        # 日志过滤器绝不能抛异常，否则每条日志都会炸
        return None


def _build_formatter() -> logging.Formatter:
    """彩色（开发）vs JSON（生产）日志格式。"""
    settings = get_settings()
    if settings.app_env == "prod":
        # 生产：单行紧凑，便于日志采集
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | trace=%(trace_id)s | %(message)s"
    else:
        # 开发：带颜色对齐
        fmt = "\033[90m%(asctime)s\033[0m | %(levelname)-8s | \033[36m%(name)s\033[0m | %(trace_id)s | %(message)s"
    return logging.Formatter(fmt, datefmt="%H:%M:%S")


def setup_logging() -> None:
    """初始化根 logger。应用启动时调用一次。"""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_build_formatter())
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # 收敛第三方库的噪音
    for noisy in ("httpx", "httpcore", "openai", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger。"""
    return logging.getLogger(name)


def new_trace_id() -> str:
    """生成并设置新的 trace_id，返回它。"""
    tid = uuid.uuid4().hex[:12]
    trace_id_var.set(tid)
    return tid
