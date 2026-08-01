"""
统一异常体系
------------
- 自定义业务异常基类与子类
- FastAPI 全局异常处理器，把异常转为统一 JSON 响应
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """所有应用业务异常的基类。"""

    def __init__(self, message: str, *, code: str = "APP_ERROR", status_code: int = 500, details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class ConfigError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="CONFIG_ERROR", status_code=500)


class LLMError(AppError):
    """LLM 调用相关异常。"""

    def __init__(self, message: str, *, provider: str | None = None, details: Any = None):
        super().__init__(message, code="LLM_ERROR", status_code=502, details=details)
        self.provider = provider


class AgentError(AppError):
    """Agent 执行相关异常。"""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message, code="AGENT_ERROR", status_code=500, details=details)


def register_exception_handlers(app: FastAPI) -> None:
    """把全局异常处理器挂到 FastAPI app 上。"""
    from app.core.config import get_settings
    from app.core.logging import get_logger

    logger = get_logger(__name__)

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError):
        settings = get_settings()
        # 生产环境不暴露 details（可能含内部信息）
        details = exc.details if settings.is_dev else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "details": details},
        )

    @app.exception_handler(Exception)
    async def _handle_unknown(_: Request, exc: Exception):
        settings = get_settings()
        # 服务端记完整堆栈
        logger.exception("未预期异常")
        # 生产环境只返回通用错误，开发环境返回详情便于调试
        msg = str(exc) if settings.is_dev else "服务器内部错误，请联系管理员"
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": msg},
        )
