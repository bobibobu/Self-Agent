"""
短期记忆（Checkpointer）
------------------------
保存单次对话（thread）内的状态，支持多轮上下文续接。

持久化策略（改进）：
- 默认优先用 Postgres（dev/prod 一致），保证重启不丢、跨进程共享
- 仅当 Postgres 连不上时，回退到 MemorySaver（内存，重启丢失）

通过 thread_id 区分不同对话：同一 thread_id 自动续接上下文。
"""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings
from app.core.logging import get_logger
from app.memory.pg import get_pg_pool

logger = get_logger(__name__)

_checkpointer: object | None = None
_init_lock = asyncio.Lock()


async def get_checkpointer() -> object:
    """获取 checkpointer 单例。

    优先 Postgres 持久化；连不上则回退内存（开发期 DB 没起时的兜底）。
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    async with _init_lock:
        if _checkpointer is not None:
            return _checkpointer

        backend = get_settings().storage_backend

        # 本地形态（CLI）：单文件 SQLite，不依赖任何数据库服务
        if backend == "sqlite":
            from app.memory.local_store import create_sqlite_checkpointer

            _checkpointer = await create_sqlite_checkpointer()
            if _checkpointer is not None:
                return _checkpointer

        if backend == "memory":
            _checkpointer = MemorySaver()
            logger.info("短期记忆：MemorySaver（STORAGE_BACKEND=memory，退出即丢）")
            return _checkpointer

        # 服务端形态：优先 Postgres（dev/prod 一致，重启不丢）
        pool = await get_pg_pool() if backend in ("auto", "postgres") else None
        if pool is not None:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                # 注意：必须用构造函数传连接池，不能用 from_conn_string——
                # 后者是 @asynccontextmanager，返回上下文管理器而非 saver（详见 app/memory/pg.py）
                cp = AsyncPostgresSaver(pool)
                await cp.setup()  # 建表（首次）
                _checkpointer = cp
                logger.info("短期记忆：AsyncPostgresSaver（Postgres 持久化，重启不丢）")
            except Exception as e:  # noqa: BLE001
                logger.warning("短期记忆：AsyncPostgresSaver 初始化失败，回退内存：%s", e)

        if _checkpointer is None:
            # Postgres 不可用 → 回退内存（DB 没起时）
            _checkpointer = MemorySaver()
            logger.warning("短期记忆：回退 MemorySaver（内存，重启将丢失，多进程不共享）")

    return _checkpointer


async def reset_checkpointer() -> None:
    """释放 checkpointer 单例（应用关闭时调用）。"""
    global _checkpointer
    _checkpointer = None


def is_checkpointer_persistent() -> bool:
    """当前 checkpointer 是否持久化（Postgres）。"""
    cp = _checkpointer
    if cp is None:
        return False
    return type(cp).__name__ == "AsyncPostgresSaver"
