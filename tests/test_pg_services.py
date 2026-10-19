"""
业务表走 psycopg 共享连接池的契约测试
=====================================
2026-10 起 users / conversations 不再用 asyncpg，改走 app/memory/pg.py 的
psycopg 池（autocommit + dict_row）。两个驱动的 API 差异全是「静默失效」型：

- 占位符 asyncpg 是 $1，psycopg 是 %s——漏改一处，查询直接报语法错，
  而调用处的宽泛 except 会把它吞掉，表现为「接口 200 但列表永远为空」。
- 受影响行数 asyncpg 解析 "DELETE 1" 状态串，psycopg 看 cursor.rowcount——
  读错了，删除/重命名会永远返回 False，或者越权删除时连带清空别人的历史。

这里用一个假池把 SQL、参数和返回值钉死，不连真实数据库。

运行：pytest tests/test_pg_services.py -v
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.db.manager import db_manager


class _Cursor:
    def __init__(self, rows: list[dict], rowcount: int) -> None:
        self._rows = rows
        self.rowcount = rowcount

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def execute(self, sql, params=None):
        self._pool.calls.append((sql, params))
        if self._pool.exc is not None:
            raise self._pool.exc
        if self._pool.row_fn is not None:
            return _Cursor([self._pool.row_fn(params)], 1)
        rows, rowcount = self._pool.results.pop(0) if self._pool.results else ([], 0)
        return _Cursor(rows, rowcount)


class _FakePool:
    """模仿 psycopg_pool.AsyncConnectionPool：只有 connection() 一个入口。"""

    def __init__(self, results: list[tuple[list[dict], int]] | None = None, exc: Exception | None = None,
                 row_fn=None) -> None:
        self.results = list(results or [])
        self.exc = exc
        # 返回行依赖 SQL 参数时用（如 thread_id 是函数内生成的）
        self.row_fn = row_fn
        self.calls: list[tuple[str, object]] = []

    @asynccontextmanager
    async def connection(self):
        yield _Conn(self)


@pytest.fixture
def fake_pool(monkeypatch):
    def _install(results=None, exc=None, row_fn=None) -> _FakePool:
        pool = _FakePool(results, exc, row_fn)
        monkeypatch.setattr(db_manager, "_postgres", pool)
        return pool

    return _install


def _assert_psycopg_style(pool: _FakePool) -> None:
    """每条 SQL：没有 asyncpg 的 $n 占位符，%s 个数与参数个数一致。"""
    assert pool.calls, "没有发出任何 SQL"
    for sql, params in pool.calls:
        assert not re.search(r"\$\d", sql), f"残留 asyncpg 占位符：{sql}"
        assert sql.count("%s") == len(params or ()), f"占位符与参数个数不符：{sql} {params}"


_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


# ==================== DBManager ====================


class TestDBManagerPostgres:
    async def test_connect_reuses_shared_pool(self, monkeypatch):
        import app.memory.pg as pg

        pool = _FakePool()

        async def _get_pool(*args, **kwargs):
            return pool

        monkeypatch.setattr(pg, "get_pg_pool", _get_pool)
        monkeypatch.setattr(db_manager, "_postgres", None)
        await db_manager._connect_postgres()
        assert db_manager.postgres is pool

    async def test_connect_raises_when_pool_unavailable(self, monkeypatch):
        """池不可用必须抛出，让 _try 打 WARNING，而不是留下一个 None 当「已连接」。"""
        monkeypatch.setattr(db_manager, "_postgres", None)
        with pytest.raises(RuntimeError):
            await db_manager._connect_postgres()  # conftest 已把 get_pg_pool 打成返回 None
        assert db_manager.postgres is None


# ==================== UserService ====================


class TestUserService:
    async def test_register_returns_user_without_hash(self, fake_pool):
        from app.auth.user_service import UserService

        row = {"id": "0b0e5b6e-0000-4000-8000-000000000001", "username": "alice", "email": None,
               "tenant_id": "default", "created_at": _NOW}
        pool = fake_pool(results=[([row], 1)])
        user = await UserService().register(username="alice", password="pw-123456")
        assert user["username"] == "alice"
        assert "password_hash" not in user
        sql, params = pool.calls[0]
        assert sql.startswith("INSERT INTO users")
        assert params[0] == "alice" and params[2] != "pw-123456", "存进库的必须是哈希不是明文"
        _assert_psycopg_style(pool)

    async def test_register_duplicate_returns_none(self, fake_pool):
        from psycopg.errors import UniqueViolation

        from app.auth.user_service import UserService

        fake_pool(exc=UniqueViolation("duplicate key"))
        assert await UserService().register(username="alice", password="pw") is None

    async def test_authenticate(self, fake_pool):
        from app.auth.jwt_service import hash_password
        from app.auth.user_service import UserService

        row = {"id": "u1", "username": "alice", "email": None, "tenant_id": "default",
               "password_hash": hash_password("right")}
        pool = fake_pool(results=[([row], 1), ([row], 1), ([], 0)])
        svc = UserService()
        ok = await svc.authenticate("alice", "right")
        assert ok == {"id": "u1", "username": "alice", "email": None, "tenant_id": "default"}
        assert await svc.authenticate("alice", "wrong") is None
        assert await svc.authenticate("nobody", "x") is None
        _assert_psycopg_style(pool)

    async def test_get_by_id(self, fake_pool):
        from app.auth.user_service import UserService

        pool = fake_pool(results=[([{"id": "u1", "username": "a", "email": None, "tenant_id": "t"}], 1)])
        assert (await UserService().get_by_id("u1"))["id"] == "u1"
        _assert_psycopg_style(pool)


# ==================== SessionService ====================


class TestSessionService:
    async def test_list_serializes_timestamps(self, fake_pool):
        from app.services.session_service import SessionService

        row = {"id": "s1", "thread_id": "sess-1", "title": "t", "user_id": "u", "tenant_id": "default",
               "created_at": _NOW, "updated_at": _NOW}
        pool = fake_pool(results=[([row], 1), ([row], 1)])
        svc = SessionService()
        by_user = await svc.list_sessions("u")
        everyone = await svc.list_sessions()
        assert by_user[0]["created_at"] == _NOW.isoformat()
        assert everyone[0]["thread_id"] == "sess-1"
        _assert_psycopg_style(pool)

    async def test_create_returns_db_row(self, fake_pool):
        from app.services.session_service import SessionService

        pool = fake_pool(row_fn=lambda params: {
            "id": "s1", "thread_id": params[0], "title": "新对话", "user_id": "u",
            "tenant_id": "default", "created_at": _NOW, "updated_at": _NOW,
        })
        s = await SessionService().create_session(user_id="u")
        assert s["thread_id"].startswith("sess-") and "source" not in s
        _assert_psycopg_style(pool)

    async def test_create_falls_back_to_memory_when_pg_down(self, monkeypatch):
        from app.services.session_service import SessionService

        monkeypatch.setattr(db_manager, "_postgres", None)
        s = await SessionService().create_session(user_id="u")
        assert s["source"] == "memory"

    async def test_rename_uses_rowcount(self, fake_pool):
        from app.services.session_service import SessionService

        pool = fake_pool(results=[([], 1), ([], 0)])
        svc = SessionService()
        assert await svc.rename_session("sess-1", "新标题", user_id="u") is True
        assert await svc.rename_session("sess-x", "新标题") is False
        assert pool.calls[0][1][-1] == "u", "带归属人时 user_id 必须进 WHERE"
        _assert_psycopg_style(pool)

    async def test_delete_purges_state_only_when_row_deleted(self, fake_pool, monkeypatch):
        """越权删除（0 行）绝不能连带清空 checkpointer 里的对话历史。"""
        from app.services.session_service import SessionService

        purged: list[str] = []

        async def _purge(scoped):
            purged.append(scoped)

        monkeypatch.setattr(SessionService, "_purge_thread_state", staticmethod(_purge))
        pool = fake_pool(results=[([], 0), ([], 1)])
        svc = SessionService()
        assert await svc.delete_session("sess-1", user_id="intruder") is False
        assert purged == []
        assert await svc.delete_session("sess-1", user_id="owner") is True
        assert len(purged) == 1
        _assert_psycopg_style(pool)

    async def test_get_and_touch(self, fake_pool):
        from app.services.session_service import SessionService

        row = {"id": "s1", "thread_id": "sess-1", "title": "t", "user_id": "u", "tenant_id": "default",
               "created_at": _NOW, "updated_at": _NOW}
        pool = fake_pool(results=[([row], 1), ([], 0), ([], 1)])
        svc = SessionService()
        assert (await svc.get_session("sess-1", user_id="u"))["id"] == "s1"
        assert await svc.get_session("sess-404") is None
        await svc.touch_session("sess-1", "u")
        assert "ON CONFLICT (tenant_id, thread_id)" in pool.calls[-1][0]
        _assert_psycopg_style(pool)
