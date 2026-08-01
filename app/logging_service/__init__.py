"""
对话日志服务（MongoDB）
----------------------
记录每轮对话的完整事件：输入、输出、工具调用、耗时、token 用量。
形态多变、写多读少，适合 Mongo 的无 schema 特性。

Mongo 不可用时静默跳过（日志记录失败不影响对话主流程）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)

COLLECTION = "conversation_events"


class ConversationLogger:
    """对话事件日志记录器。"""

    async def log_event(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        user_message: str,
        agent_reply: str,
        provider: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        tenant_id: str = "default",
    ) -> None:
        """记录一次对话事件（含 tenant_id 便于多租户审计）。

        设计为「即发即忘」：记录失败只记本地日志，不抛异常，
        避免日志逻辑影响对话主流程。
        """
        event = {
            "thread_id": thread_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "user_message": user_message,
            "agent_reply": agent_reply,
            "provider": provider,
            "tool_calls": tool_calls or [],
            "usage": usage or {},
            "duration_ms": duration_ms,
            "error": error,
            "ts": datetime.now(timezone.utc),
        }

        if db_manager.mongo is None:
            logger.debug("MongoDB 不可用，对话事件未持久化")
            return

        try:
            await db_manager.mongo[COLLECTION].insert_one(event)
            logger.debug("对话事件已记录 thread=%s", thread_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("对话事件记录失败（不影响主流程）：%s", e)

    async def get_history(self, thread_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """查询某会话的事件历史。"""
        if db_manager.mongo is None:
            return []
        try:
            cursor = db_manager.mongo[COLLECTION].find(
                {"thread_id": thread_id}
            ).sort("ts", -1).limit(limit)
            docs = await cursor.to_list(length=limit)
            # 倒序查正序返
            docs.reverse()
            # 转 id 为字符串
            for d in docs:
                d["_id"] = str(d["_id"])
                if "ts" in d and hasattr(d["ts"], "isoformat"):
                    d["ts"] = d["ts"].isoformat()
            return docs
        except Exception as e:  # noqa: BLE001
            logger.warning("查询对话历史失败：%s", e)
            return []


_conversation_logger: Optional[ConversationLogger] = None


def get_conversation_logger() -> ConversationLogger:
    """获取 ConversationLogger 单例。"""
    global _conversation_logger
    if _conversation_logger is None:
        _conversation_logger = ConversationLogger()
    return _conversation_logger
