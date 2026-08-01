"""
流式中断（取消生成）支持
------------------------
允许客户端中断正在进行的流式生成。

机制：
- 维护一个 thread_id → asyncio.Event 的取消注册表
- stream_agent 每产出一个事件前检查取消标志，若被取消则提前结束
- 客户端调 /chat/cancel/{thread_id} 设置取消标志

为什么不用 asyncio.Task.cancel()：
LangGraph 的 astream 内部管理自己的任务，外部直接 cancel 不一定干净。
用协作式取消标志更可控、更安全。
"""

from __future__ import annotations

import asyncio

# thread_id → 取消事件（set 表示已请求取消）
_cancel_events: dict[str, asyncio.Event] = {}
_lock = asyncio.Lock()


async def register_stream(thread_id: str) -> asyncio.Event:
    """注册一个流式任务，返回其取消事件。"""
    async with _lock:
        ev = asyncio.Event()
        _cancel_events[thread_id] = ev
        return ev


async def request_cancel(thread_id: str) -> bool:
    """请求取消指定 thread 的流式生成。返回是否找到该任务。"""
    async with _lock:
        ev = _cancel_events.get(thread_id)
        if ev is not None:
            ev.set()
            return True
        return False


async def unregister_stream(thread_id: str) -> None:
    """流式任务结束后注销（清理）。"""
    async with _lock:
        _cancel_events.pop(thread_id, None)


def is_cancelled(thread_id: str) -> bool:
    """检查是否已被请求取消。"""
    ev = _cancel_events.get(thread_id)
    return ev is not None and ev.is_set()
