"""
会话管理服务（SessionService）
------------------------------
管理对话会话的元数据（列表/新建/重命名/删除），用 Postgres 的 conversations 表。

会话 = 一个 thread_id + 元信息（标题、用户、租户、时间）。
会话的「内容」（消息历史）由 checkpointer 管理，这里只管「会话本身」。

多租户隔离：所有查询按 (tenant_id, user_id) 过滤，写入带 tenant_id。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)


class SessionService:
    """会话管理（按租户+用户隔离）。"""

    async def list_sessions(
        self, user_id: str | None = None, *, tenant_id: str = "default", limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出会话（按 tenant_id 必过滤，可按 user_id 过滤），按更新时间倒序。"""
        try:
            pool = db_manager.postgres
            if pool is None:
                return []
            async with pool.acquire() as conn:
                if user_id:
                    rows = await conn.fetch(
                        "SELECT id, thread_id, title, user_id, tenant_id, created_at, updated_at "
                        "FROM conversations WHERE tenant_id = $1 AND user_id = $2 "
                        "ORDER BY updated_at DESC LIMIT $3",
                        tenant_id, user_id, limit,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT id, thread_id, title, user_id, tenant_id, created_at, updated_at "
                        "FROM conversations WHERE tenant_id = $1 ORDER BY updated_at DESC LIMIT $2",
                        tenant_id, limit,
                    )
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:  # noqa: BLE001
            logger.warning("列出会话失败：%s", e)
            return []

    async def create_session(
        self, *, user_id: str | None = None, title: str = "新对话", tenant_id: str = "default",
    ) -> dict[str, Any]:
        """新建会话，返回含 thread_id 的会话信息（带 tenant_id）。"""
        thread_id = f"sess-{uuid.uuid4().hex[:12]}"
        try:
            pool = db_manager.postgres
            if pool is None:
                return {"thread_id": thread_id, "title": title, "user_id": user_id, "tenant_id": tenant_id, "source": "memory"}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO conversations (thread_id, user_id, title, tenant_id) VALUES ($1, $2, $3, $4) "
                    "RETURNING id, thread_id, title, user_id, tenant_id, created_at, updated_at",
                    thread_id, user_id, title, tenant_id,
                )
            logger.info("新建会话 thread=%s user=%s tenant=%s", thread_id, user_id, tenant_id)
            return self._row_to_dict(row)
        except Exception as e:  # noqa: BLE001
            logger.warning("创建会话记录失败（仍返回可用 thread_id）：%s", e)
            return {"thread_id": thread_id, "title": title, "user_id": user_id, "tenant_id": tenant_id, "source": "memory"}

    async def rename_session(self, thread_id: str, title: str, *, tenant_id: str = "default") -> bool:
        """重命名会话（按租户校验归属）。"""
        try:
            pool = db_manager.postgres
            if pool is None:
                return False
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE conversations SET title = $1, updated_at = now() "
                    "WHERE thread_id = $2 AND tenant_id = $3",
                    title, thread_id, tenant_id,
                )
            return "UPDATE 1" in result or int(result.split()[-1]) > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("重命名会话失败：%s", e)
            return False

    async def delete_session(self, thread_id: str, *, tenant_id: str = "default") -> bool:
        """删除会话（按租户校验归属，含清理 checkpointer 状态）。"""
        from app.auth.tenant import scoped_thread_id

        try:
            pool = db_manager.postgres
            if pool is None:
                return False
            scoped_tid = scoped_thread_id(tenant_id, thread_id)
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM conversations WHERE thread_id = $1 AND tenant_id = $2",
                    thread_id, tenant_id,
                )
                # 清理 LangGraph checkpointer 中该 scoped thread 的状态
                try:
                    await conn.execute("DELETE FROM checkpoints WHERE thread_id = $1", scoped_tid)
                    await conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = $1", scoped_tid)
                    await conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = $1", scoped_tid)
                except Exception:  # noqa: BLE001
                    pass
            deleted = "DELETE 1" in result or int(result.split()[-1]) > 0
            if deleted:
                logger.info("删除会话 thread=%s tenant=%s", thread_id, tenant_id)
            return deleted
        except Exception as e:  # noqa: BLE001
            logger.warning("删除会话失败：%s", e)
            return False

    async def get_session(self, thread_id: str, *, tenant_id: str = "default") -> dict[str, Any] | None:
        """获取单个会话信息（按租户校验归属）。"""
        try:
            rows = await self._exec(
                "SELECT id, thread_id, title, user_id, tenant_id, created_at, updated_at "
                "FROM conversations WHERE thread_id = $1 AND tenant_id = $2",
                thread_id, tenant_id,
            )
            return self._row_to_dict(rows[0]) if rows else None
        except Exception as e:  # noqa: BLE001
            logger.warning("获取会话失败：%s", e)
            return None

    async def touch_session(self, thread_id: str, user_id: str | None = None, tenant_id: str = "default") -> None:
        """更新会话的 updated_at（按租户 upsert）。"""
        try:
            pool = db_manager.postgres
            if pool is None:
                return
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO conversations (thread_id, user_id, title, tenant_id) "
                    "VALUES ($1, $2, '对话', $3) "
                    "ON CONFLICT (thread_id) DO UPDATE SET updated_at = now()",
                    thread_id, user_id, tenant_id,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("touch_session 失败（不影响对话）：%s", e)

    async def _exec(self, sql: str, *args) -> Any:
        """执行 SQL（需 Postgres 可用）。"""
        pool = db_manager.postgres
        if pool is None:
            raise RuntimeError("PostgreSQL 不可用")
        async with pool.acquire() as conn:
            return await conn.fetch(sql, *args) if sql.strip().upper().startswith("SELECT") else await conn.execute(sql, *args)

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        d = dict(row)
        for k in ("created_at", "updated_at"):
            if k in d and d[k] is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        return d


_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """获取 SessionService 单例。"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
