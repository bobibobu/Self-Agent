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
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_checkpointer: Optional[object] = None
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

        s = get_settings()
        # 统一优先尝试 Postgres（dev/prod 一致，重启不丢）
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            cp = AsyncPostgresSaver.from_conn_string(s.postgres_dsn_sync)
            await cp.setup()  # 建表（首次）
            _checkpointer = cp
            logger.info("短期记忆：AsyncPostgresSaver（Postgres 持久化，重启不丢）")
        except Exception as e:  # noqa: BLE001
            # Postgres 不可用 → 回退内存（DB 没起时）
            _checkpointer = MemorySaver()
            logger.warning("短期记忆：Postgres 不可用，回退 MemorySaver（内存，重启将丢失）：%s", e)

    return _checkpointer


def is_checkpointer_persistent() -> bool:
    """当前 checkpointer 是否持久化（Postgres）。"""
    cp = _checkpointer
    if cp is None:
        return False
    return type(cp).__name__ == "AsyncPostgresSaver"
