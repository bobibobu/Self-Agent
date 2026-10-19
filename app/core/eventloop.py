"""
事件循环选择（Windows 上兼容 psycopg）
-------------------------------------
psycopg 的异步模式**不支持** Windows 默认的 ProactorEventLoop，连接时直接抛
InterfaceError。而 uvicorn 在 Windows 上不开 --reload 时选的恰恰是 Proactor
（桌面客户端内嵌的 uvicorn 也是）。

2026-10 起业务表（users / conversations）和 LangGraph checkpointer/store 共用
psycopg 连接池，Proactor 下会**全部**不可用：登录注册失败、会话列表为空、
对话历史退回内存。以前业务表走 asyncpg（兼容 Proactor），只有 LangGraph 静默降级，
所以这个坑一直没暴露。

用法：
    uvicorn app.main:app --loop app.core.eventloop:pg_loop_factory
    uvicorn.Config(app, loop="app.core.eventloop:pg_loop_factory")
    asyncio.run(main(), loop_factory=pg_loop_factory)

代价：Windows 的 SelectorEventLoop 不支持 asyncio 子进程。
- shell 工具遇到 NotImplementedError 会退到线程里跑 subprocess.run（app/agent/tools/shell.py）
- MCP stdio client 由 mcp SDK 自带的 FallbackProcess 兜底（mcp/os/win32/utilities.py）
"""

from __future__ import annotations

import asyncio
import sys

from app.core.logging import get_logger

logger = get_logger(__name__)

# 给 uvicorn --loop / uvicorn.Config(loop=...) 用的导入串
PG_LOOP_FACTORY = "app.core.eventloop:pg_loop_factory"


def pg_loop_factory() -> asyncio.AbstractEventLoop:
    """新建一个 psycopg 兼容的事件循环。

    Windows → SelectorEventLoop；其他平台与 uvicorn 的 auto 一致（有 uvloop 用 uvloop）。
    """
    if sys.platform == "win32":
        logger.info("事件循环：SelectorEventLoop（Windows，兼容 psycopg 异步）")
        return asyncio.SelectorEventLoop()
    try:
        import uvloop
    except ImportError:
        logger.info("事件循环：asyncio 默认（未安装 uvloop）")
        return asyncio.new_event_loop()
    logger.info("事件循环：uvloop")
    return uvloop.new_event_loop()


def check_loop_compatibility() -> bool:
    """当前运行中的循环能否跑 psycopg 异步。不能时打 ERROR 并给出改法。

    返回 True 表示兼容。只做告警不抛异常：Postgres 不可用时应用本来就会降级运行。
    """
    proactor = getattr(asyncio, "ProactorEventLoop", None)  # 只有 Windows 上存在
    loop = asyncio.get_running_loop()
    if proactor is not None and isinstance(loop, proactor):
        logger.error(
            "当前事件循环是 ProactorEventLoop，psycopg 异步不支持它：用户/会话表与对话历史持久化都将不可用。"
            "启动时加 `--loop %s`（或开 --reload），桌面客户端已内置该设置",
            PG_LOOP_FACTORY,
        )
        return False
    logger.info("事件循环兼容 psycopg：%s", type(loop).__name__)
    return True
