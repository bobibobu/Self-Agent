"""
本地模式测试
============
覆盖三件事：SQLite 单文件存储、审批中断的完整往返、以及
「事件流必须消费完」这条容易踩的契约。

最后一条尤其要钉死：LangGraph 要等 astream 自然结束才把中断状态写进
checkpointer，拿到 approval_required 就 break 会让 resume 找不到可恢复的
中断——表现为「用户点了同意但什么都没发生」，而且不报任何错。

运行：pytest tests/test_local_mode.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clients", "cli"))


class _ToolThenTextLLM:
    """先要求写文件（触发审批），拿到工具结果后再出文本。"""

    provider_name = "stub"
    default_model = "stub-1"

    def __init__(self, path: str = "generated.py", content: str = "x = 1\n"):
        self.n = 0
        self.path, self.content = path, content

    async def stream_chat(self, request):
        from app.llm.models import StreamChunk, ToolCall, Usage

        self.n += 1
        if self.n == 1:
            yield StreamChunk(
                content="",
                tool_calls=[ToolCall(id="c1", name="write_file",
                                     arguments={"path": self.path, "content": self.content})],
                finish_reason="tool_calls", usage=Usage(), model="stub-1",
            )
            return
        for ch in "好了。":
            yield StreamChunk(content=ch)
        yield StreamChunk(content="", finish_reason="stop", usage=Usage(), model="stub-1")


@pytest.fixture
def local(tmp_path, monkeypatch):
    """把当前进程切到「本地模式 + 临时工作区 + 临时 SQLite」。"""
    from app.core.config import get_settings
    from app.workspace import get_workspace, set_workspace

    s = get_settings()
    saved = (s.storage_backend, s.sqlite_path, s.tool_approval_mode, s.coding_tools_enabled)
    s.storage_backend = "sqlite"
    s.sqlite_path = str(tmp_path / "state.db")
    s.tool_approval_mode = "gated"
    s.coding_tools_enabled = True
    set_workspace(tmp_path)

    # 注册编码工具（conftest 默认关掉了，这里按需打开）
    from app.agent.registry import ToolRisk, register_tools
    from app.agent.tools.files import READ_TOOLS, WRITE_TOOLS
    from app.agent.tools.shell import SHELL_TOOLS

    register_tools(READ_TOOLS, ToolRisk.READ)
    register_tools(WRITE_TOOLS, ToolRisk.WRITE)
    register_tools(SHELL_TOOLS, ToolRisk.EXEC)

    # checkpointer 是单例，切后端前必须清掉
    import app.agent.graph as graph_mod
    import app.memory.checkpointer as cp_mod

    cp_mod._checkpointer = None
    graph_mod._compiled_graph = None

    yield tmp_path

    (s.storage_backend, s.sqlite_path, s.tool_approval_mode, s.coding_tools_enabled) = saved
    cp_mod._checkpointer = None
    graph_mod._compiled_graph = None
    get_workspace.cache_clear()


async def _drain(stream) -> tuple[list[dict], dict | None]:
    """消费完整个流，返回 (全部事件, 审批请求)。"""
    events, approval = [], None
    async for ev in stream:
        events.append(ev)
        if ev.get("type") == "approval_required":
            approval = ev
    return events, approval


class TestSqliteStorage:
    @pytest.mark.asyncio
    async def test_uses_sqlite_not_postgres(self, local, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.memory.checkpointer import get_checkpointer

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        cp = await get_checkpointer()
        assert type(cp).__name__ == "AsyncSqliteSaver", f"应使用 SQLite，实际 {type(cp).__name__}"

    def test_per_workspace_database_paths(self, tmp_path):
        """不同项目各自一个库——换个目录就是干净的新开始。"""
        from app.memory.local_store import sqlite_path_for

        a, b = tmp_path / "proj-a", tmp_path / "proj-b"
        a.mkdir()
        b.mkdir()
        pa, pb = sqlite_path_for(a), sqlite_path_for(b)
        assert pa != pb
        # 目录名是哈希，旁边留可读记录，否则一堆哈希目录没法排查
        assert (pa.parent / "workspace.txt").read_text().strip() == str(a.resolve())

    @pytest.mark.asyncio
    async def test_state_persists_to_disk(self, local, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import get_compiled_graph, stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await _drain(stream_agent("你好", "persist-1"))

        graph = await get_compiled_graph()
        state = await graph.aget_state({"configurable": {"thread_id": "persist-1"}})
        assert state.values.get("messages"), "状态没有落到 SQLite"
        # 断言文件真的落盘了（这里是测试，同步 stat 无所谓阻塞）
        assert (local / "state.db").stat().st_size > 0  # noqa: ASYNC240


class TestApprovalRoundTrip:
    @pytest.mark.asyncio
    async def test_write_is_held_until_approved(self, local, monkeypatch):
        """核心：审批返回之前，文件绝不能被写。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        _events, approval = await _drain(stream_agent("建个文件", "hold-1"))

        assert approval is not None, "写文件应触发审批中断"
        assert approval["tool"] == "write_file"
        assert approval["risk"] == "write"
        assert not (local / "generated.py").exists(), "审批前文件就被写了"

    @pytest.mark.asyncio
    async def test_deny_prevents_write(self, local, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import resume_agent, stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await _drain(stream_agent("建个文件", "deny-1"))
        await _drain(resume_agent("deny-1", {"approved": False, "reason": "不需要"}))

        assert not (local / "generated.py").exists(), "拒绝后文件仍被创建"

    @pytest.mark.asyncio
    async def test_approve_performs_write(self, local, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import resume_agent, stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await _drain(stream_agent("建个文件", "ok-1"))
        events, _ = await _drain(resume_agent("ok-1", {"approved": True, "reason": ""}))

        assert (local / "generated.py").read_text() == "x = 1\n"
        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_no_done_event_while_awaiting_approval(self, local, monkeypatch):
        """挂起等审批时不能发 done——客户端会以为这轮答完了。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        events, _ = await _drain(stream_agent("建个文件", "nodone-1"))

        assert not any(e["type"] == "done" for e in events), "等待审批时不该发 done"

    @pytest.mark.asyncio
    async def test_breaking_early_loses_the_interrupt(self, local, monkeypatch):
        """回归护栏：拿到 approval_required 就 break 会让 resume 失效。

        这是实际踩过的坑——LangGraph 要等 astream 自然结束才把中断写进
        checkpointer，提前中止后 resume 什么也不做，而且不报错。
        本用例把这个差异钉死，防止有人"顺手优化"成提前退出。
        """
        import app.agent.nodes.agent_node as node
        from app.agent.graph import resume_agent, stream_agent

        llm = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        # 提前 break
        async for ev in stream_agent("建个文件", "brk-1"):
            if ev.get("type") == "approval_required":
                break
        await _drain(resume_agent("brk-1", {"approved": True}))
        broke_early = (local / "generated.py").exists()

        # 消费完整个流（换个全新的桩，让它重新从"要求写文件"开始）
        (local / "generated.py").unlink(missing_ok=True)
        llm2 = _ToolThenTextLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm2)
        await _drain(stream_agent("建个文件", "brk-2"))
        await _drain(resume_agent("brk-2", {"approved": True}))
        drained_fully = (local / "generated.py").exists()

        assert drained_fully, "消费完整个流后 resume 应当生效"
        assert not broke_early, (
            "提前 break 居然也生效了——若 LangGraph 行为变了，"
            "可以放宽 stream_agent 文档里「必须消费完」的要求"
        )


class TestLocalBootstrap:
    def test_bootstrap_presets_local_environment(self, tmp_path, monkeypatch):
        """本地模式不该要求任何数据库服务。"""
        for k in ("STORAGE_BACKEND", "AUTH_ENABLED", "A2A_ENABLED", "WORKSPACE_ROOT"):
            monkeypatch.delenv(k, raising=False)

        from selfagent_cli.local import bootstrap

        root = bootstrap(str(tmp_path))
        assert root == tmp_path.resolve()
        assert os.environ["STORAGE_BACKEND"] == "sqlite"
        assert os.environ["AUTH_ENABLED"] == "false"
        assert os.environ["A2A_ENABLED"] == "false"
        assert os.environ["WORKSPACE_ROOT"] == str(tmp_path.resolve())

    def test_bootstrap_respects_explicit_env(self, tmp_path, monkeypatch):
        """用户已显式配过的不覆盖——只有工作区以命令行为准。"""
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        from selfagent_cli.local import bootstrap

        bootstrap(str(tmp_path))
        assert os.environ["STORAGE_BACKEND"] == "memory"
