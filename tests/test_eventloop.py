"""
事件循环选择测试
================
psycopg 异步不支持 Windows 的 ProactorEventLoop。业务表与 LangGraph 共用 psycopg
连接池之后，Proactor 下登录、会话、对话历史持久化会一起失效，所以：
- 桌面客户端 / 脚本统一用 pg_loop_factory 建循环
- 服务启动时检测到 Proactor 要打 ERROR 并给出改法，而不是只剩一串降级告警

Linux 上没有 ProactorEventLoop，这里用 monkeypatch 模拟 Windows。

运行：pytest tests/test_eventloop.py -v
"""

from __future__ import annotations

import asyncio
import logging

import pytest


class TestLoopFactory:
    def test_windows_gets_selector_loop(self, monkeypatch):
        from app.core import eventloop

        monkeypatch.setattr(eventloop.sys, "platform", "win32")
        loop = eventloop.pg_loop_factory()
        try:
            assert isinstance(loop, asyncio.SelectorEventLoop)
        finally:
            loop.close()

    def test_non_windows_loop_runs_coroutines(self):
        from app.core.eventloop import pg_loop_factory

        async def _answer():
            return 42

        assert asyncio.run(_answer(), loop_factory=pg_loop_factory) == 42

    def test_uvicorn_can_import_factory_string(self):
        """uvicorn 的 --loop / Config(loop=...) 收的是导入串，必须能解析成可调用对象。"""
        from uvicorn.importer import import_from_string

        from app.core.eventloop import PG_LOOP_FACTORY, pg_loop_factory

        assert import_from_string(PG_LOOP_FACTORY) is pg_loop_factory

    def test_desktop_backend_uses_factory(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "clients/desktop/app.py").read_text(encoding="utf-8")
        assert "loop=PG_LOOP_FACTORY" in src, "桌面内嵌 uvicorn 必须显式指定 psycopg 兼容的事件循环"


class TestLoopCompatibilityCheck:
    @pytest.mark.asyncio
    async def test_compatible_loop(self):
        from app.core.eventloop import check_loop_compatibility

        assert check_loop_compatibility() is True

    @pytest.mark.asyncio
    async def test_proactor_is_reported(self, monkeypatch, caplog):
        from app.core.eventloop import check_loop_compatibility

        # 把「当前循环的类型」冒充成 ProactorEventLoop
        monkeypatch.setattr(asyncio, "ProactorEventLoop", type(asyncio.get_running_loop()), raising=False)
        with caplog.at_level(logging.ERROR, logger="app.core.eventloop"):
            assert check_loop_compatibility() is False
        assert "app.core.eventloop:pg_loop_factory" in caplog.text
