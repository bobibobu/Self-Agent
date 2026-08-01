"""
LangGraph 持久化层共享的 Postgres 连接池
========================================
checkpointer（短期记忆）与 store（长期记忆 / RAG）都基于 psycopg，
共用一个连接池，避免各开一条连接、也避免 from_conn_string 的单连接瓶颈。

为什么不用 `AsyncPostgresSaver.from_conn_string(...)`：
    它是 `@asynccontextmanager`，返回的是上下文管理器而不是 saver 实例。
    直接拿返回值调 `.setup()` 会 AttributeError（历史上这个错误被 except
    吞掉，导致持久化静默退化成内存态）。要用它必须 `async with`，
    但那样连接会在 with 块结束时关闭，撑不起应用级单例。
    所以这里直接走「自己管理的连接池 + 构造函数」这条官方推荐路径。

LangGraph 对连接的硬性要求（缺一不可）：
    autocommit=True        —— saver 内部自己控制事务
    prepare_threshold=0    —— 禁用隐式 prepared statement（否则 pgbouncer 等会炸）
    row_factory=dict_row   —— saver 按 dict 取列
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_pool: object | None = None
_pool_lock = asyncio.Lock()
# 记住「已经试过且失败了」，避免每次请求都去重连一个连不上的库
_pool_failed = False


async def get_pg_pool(*, timeout: float = 5.0):
    """获取共享 Postgres 连接池；不可用时返回 None（由调用方降级）。"""
    global _pool, _pool_failed
    if _pool is not None:
        return _pool
    if _pool_failed:
        return None

    async with _pool_lock:
        if _pool is not None:
            return _pool
        if _pool_failed:
            return None

        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            s = get_settings()
            pool = AsyncConnectionPool(
                conninfo=s.postgres_dsn_sync,
                min_size=1,
                max_size=s.postgres_pool_max_size,
                # open=False + 显式 open()：构造函数里隐式开池在新版 psycopg_pool 会告警，
                # 且拿不到「连不上」的明确失败点
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            # wait=True：等池子真的建起至少一条连接，连不上就在这里抛，快速失败
            await pool.open(wait=True, timeout=timeout)
            _pool = pool
            logger.info("LangGraph Postgres 连接池已就绪（max_size=%d）", s.postgres_pool_max_size)
            return _pool
        except Exception as e:  # noqa: BLE001
            _pool_failed = True
            logger.warning("LangGraph Postgres 连接池不可用，持久化将降级为内存：%s", e)
            return None


async def close_pg_pool() -> None:
    """关闭连接池（应用关闭时调用）。"""
    global _pool, _pool_failed
    if _pool is not None:
        try:
            await _pool.close()  # type: ignore[attr-defined]
            logger.info("LangGraph Postgres 连接池已关闭")
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭 Postgres 连接池失败：%s", e)
    _pool = None
    _pool_failed = False
