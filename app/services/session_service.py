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

    async def rename_session(
        self, thread_id: str, title: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> bool:
        """重命名会话（按租户 + 归属人校验）。"""
        try:
            pool = db_manager.postgres
            if pool is None:
                return False
            sql = ("UPDATE conversations SET title = $1, updated_at = now() "
                   "WHERE thread_id = $2 AND tenant_id = $3")
            args: list[Any] = [title, thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = $4"
                args.append(user_id)
            async with pool.acquire() as conn:
                result = await conn.execute(sql, *args)
            return self._affected(result) > 0
        except Exception as e:  # noqa: BLE001
            logger.warning("重命名会话失败：%s", e)
            return False

    async def delete_session(
        self, thread_id: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> bool:
        """删除会话（按租户 + 归属人校验，含清理 checkpointer 状态）。"""
        from app.auth.tenant import scoped_thread_id

        try:
            pool = db_manager.postgres
            if pool is None:
                return False
            scoped_tid = scoped_thread_id(tenant_id, thread_id)
            sql = "DELETE FROM conversations WHERE thread_id = $1 AND tenant_id = $2"
            args: list[Any] = [thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = $3"
                args.append(user_id)
            async with pool.acquire() as conn:
                result = await conn.execute(sql, *args)
            deleted = self._affected(result) > 0
            # 只有确实删掉了会话记录，才清理对应的对话状态——
            # 否则越权删除请求会连带把别人的历史清空
            if deleted:
                await self._purge_thread_state(scoped_tid)
                logger.info("删除会话 thread=%s tenant=%s", thread_id, tenant_id)
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
        except Exception as e:  # noqa: BLE001
            logger.warning("清理会话状态失败 thread=%s：%s", scoped_thread_id, e)

    async def get_session(
        self, thread_id: str, *, tenant_id: str = "default", user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """获取单个会话信息（按租户 + 归属人校验）。"""
        try:
            sql = ("SELECT id, thread_id, title, user_id, tenant_id, created_at, updated_at "
                   "FROM conversations WHERE thread_id = $1 AND tenant_id = $2")
            args: list[Any] = [thread_id, tenant_id]
            if user_id is not None:
                sql += " AND user_id = $3"
                args.append(user_id)
            rows = await self._exec(sql, *args)
            return self._row_to_dict(rows[0]) if rows else None
        except Exception as e:  # noqa: BLE001
            logger.warning("获取会话失败：%s", e)
            return None

    @staticmethod
    def _affected(status: str) -> int:
        """从 asyncpg 的命令状态串（如 "DELETE 1"）解析受影响行数。"""
        try:
            return int(status.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def touch_session(self, thread_id: str, user_id: str | None = None, tenant_id: str = "default") -> None:
        """更新会话的 updated_at（按租户 upsert）。"""
        try:
            pool = db_manager.postgres
            if pool is None:
                return
            async with pool.acquire() as conn:
                # 冲突键是 (tenant_id, thread_id)——thread_id 单列唯一会让两个租户
                # 用同一 thread_id 时互相覆盖（见 migrations/001）
                await conn.execute(
                    "INSERT INTO conversations (thread_id, user_id, title, tenant_id) "
                    "VALUES ($1, $2, '对话', $3) "
                    "ON CONFLICT (tenant_id, thread_id) DO UPDATE SET updated_at = now()",
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


_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    """获取 SessionService 单例。"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
