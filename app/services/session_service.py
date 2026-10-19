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
from typing import Any

from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)


class SessionService:
    """会话管理（按租户+用户隔离）。

    走 db_manager.postgres（psycopg 共享连接池，autocommit + dict_row）：
    占位符是 %s，受影响行数看 cursor.rowcount。
    """

    _COLS = "id, thread_id, title, user_id, tenant_id, created_at, updated_at"

    async def list_sessions(
        self, user_id: str | None = None, *, tenant_id: str = "default", limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出会话（按 tenant_id 必过滤，可按 user_id 过滤），按更新时间倒序。"""
        logger.info("[sessions] list 入参 user=%s tenant=%s limit=%d", user_id, tenant_id, limit)
        try:
            pool = db_manager.postgres
            if pool is None:
                logger.warning("[sessions] list 跳过：PostgreSQL 不可用，返回空列表")
                return []
            if user_id:
                sql = (f"SELECT {self._COLS} FROM conversations WHERE tenant_id = %s AND user_id = %s "
                       "ORDER BY updated_at DESC LIMIT %s")
                params: tuple[Any, ...] = (tenant_id, user_id, limit)
            else:
                sql = f"SELECT {self._COLS} FROM conversations WHERE tenant_id = %s ORDER BY updated_at DESC LIMIT %s"
                params = (tenant_id, limit)
            async with pool.connection() as conn:
                cur = await conn.execute(sql, params)
                rows = await cur.fetchall()
            result = [self._row_to_dict(r) for r in rows]
            logger.info("[sessions] list 返回 %d 条 thread=%s", len(result), [r.get("thread_id") for r in result])
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("列出会话失败：%s", e)
            return []

    async def create_session(
        self, *, user_id: str | None = None, title: str = "新对话", tenant_id: str = "default",
    ) -> dict[str, Any]:
        """新建会话，返回含 thread_id 的会话信息（带 tenant_id）。"""
        thread_id = f"sess-{uuid.uuid4().hex[:12]}"
        logger.info("[sessions] create 入参 user=%s tenant=%s title=%s → thread=%s", user_id, tenant_id, title, thread_id)
        fallback = {"thread_id": thread_id, "title": title, "user_id": user_id, "tenant_id": tenant_id, "source": "memory"}
        try:
            pool = db_manager.postgres
            if pool is None:
                logger.warning("[sessions] create 降级：PostgreSQL 不可用，返回内存会话 %s", fallback)
                return fallback
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO conversations (thread_id, user_id, title, tenant_id) VALUES (%s, %s, %s, %s) "
                    f"RETURNING {self._COLS}",
                    (thread_id, user_id, title, tenant_id),
                )
                row = await cur.fetchone()
            result = self._row_to_dict(row)
            logger.info("新建会话 thread=%s user=%s tenant=%s 返回=%s", thread_id, user_id, tenant_id, result)
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("创建会话记录失败（仍返回可用 thread_id）：%s", e)
            return fallback

    async def rename_session(
        self, thread_id: str, title: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> bool:
        """重命名会话（按租户 + 归属人校验）。"""
        logger.info("[sessions] rename 入参 thread=%s title=%s tenant=%s user=%s", thread_id, title, tenant_id, user_id)
        try:
            pool = db_manager.postgres
            if pool is None:
                logger.warning("[sessions] rename 跳过：PostgreSQL 不可用")
                return False
            sql = ("UPDATE conversations SET title = %s, updated_at = now() "
                   "WHERE thread_id = %s AND tenant_id = %s")
            params: list[Any] = [title, thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = %s"
                params.append(user_id)
            async with pool.connection() as conn:
                cur = await conn.execute(sql, params)
                affected = cur.rowcount
            logger.info("[sessions] rename 返回 affected=%d thread=%s", affected, thread_id)
            return affected > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("重命名会话失败：%s", e)
            return False

    async def delete_session(
        self, thread_id: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> bool:
        """删除会话（按租户 + 归属人校验，含清理 checkpointer 状态）。"""
        from app.auth.tenant import scoped_thread_id

        logger.info("[sessions] delete 入参 thread=%s tenant=%s user=%s", thread_id, tenant_id, user_id)
        try:
            pool = db_manager.postgres
            if pool is None:
                logger.warning("[sessions] delete 跳过：PostgreSQL 不可用")
                return False
            scoped_tid = scoped_thread_id(tenant_id, thread_id)
            sql = "DELETE FROM conversations WHERE thread_id = %s AND tenant_id = %s"
            params: list[Any] = [thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = %s"
                params.append(user_id)
            async with pool.connection() as conn:
                cur = await conn.execute(sql, params)
                deleted = cur.rowcount > 0
            # 只有确实删掉了会话记录，才清理对应的对话状态——
            # 否则越权删除请求会连带把别人的历史清空
            if deleted:
                await self._purge_thread_state(scoped_tid)
                logger.info("删除会话 thread=%s tenant=%s", thread_id, tenant_id)
            logger.info("[sessions] delete 返回 deleted=%s thread=%s", deleted, thread_id)
            return deleted
        except Exception as e:  # noqa: BLE001
            logger.warning("删除会话失败：%s", e)
            return False

    @staticmethod
    async def _purge_thread_state(scoped_thread_id: str) -> None:
        """清理 LangGraph checkpointer 里该 thread 的状态。

        走 checkpointer 的 adelete_thread()，不再手写 DELETE FROM checkpoints...——
        那些表名是 LangGraph 的内部实现，版本升级会悄悄失效。
        """
        try:
            from app.memory.checkpointer import get_checkpointer

            cp = await get_checkpointer()
            deleter = getattr(cp, "adelete_thread", None)
            if deleter is not None:
                await deleter(scoped_thread_id)
                logger.info("[sessions] 已清理 checkpointer 状态 thread=%s", scoped_thread_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("清理会话状态失败 thread=%s：%s", scoped_thread_id, e)

    async def get_session(
        self, thread_id: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """获取单个会话信息（按租户 + 归属人校验）。"""
        logger.info("[sessions] get 入参 thread=%s tenant=%s user=%s", thread_id, tenant_id, user_id)
        try:
            pool = db_manager.postgres
            if pool is None:
                raise RuntimeError("PostgreSQL 不可用")
            sql = f"SELECT {self._COLS} FROM conversations WHERE thread_id = %s AND tenant_id = %s"
            params: list[Any] = [thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = %s"
                params.append(user_id)
            async with pool.connection() as conn:
                cur = await conn.execute(sql, params)
                row = await cur.fetchone()
            result = self._row_to_dict(row) if row else None
            logger.info("[sessions] get 返回=%s", result)
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("获取会话失败：%s", e)
            return None

    async def touch_session(self, thread_id: str, user_id: str | None = None, tenant_id: str = "default") -> None:
        """更新会话的 updated_at（按租户 upsert）。"""
        logger.info("[sessions] touch 入参 thread=%s user=%s tenant=%s", thread_id, user_id, tenant_id)
        try:
            pool = db_manager.postgres
            if pool is None:
                logger.info("[sessions] touch 跳过：PostgreSQL 不可用")
                return
            async with pool.connection() as conn:
                # 冲突键是 (tenant_id, thread_id)——thread_id 单列唯一会让两个租户
                # 用同一 thread_id 时互相覆盖（见 migrations/001）
                cur = await conn.execute(
                    "INSERT INTO conversations (thread_id, user_id, title, tenant_id) "
                    "VALUES (%s, %s, '对话', %s) "
                    "ON CONFLICT (tenant_id, thread_id) DO UPDATE SET updated_at = now()",
                    (thread_id, user_id, tenant_id),
                )
            logger.info("[sessions] touch 完成 thread=%s affected=%d", thread_id, cur.rowcount)
        except Exception as e:  # noqa: BLE001
            logger.warning("touch_session 失败（不影响对话）：%s", e)

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        d = dict(row)
        for k in ("created_at", "updated_at"):
            if k in d and d[k] is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        return d


_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    """获取 SessionService 单例。"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
