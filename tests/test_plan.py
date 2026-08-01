"""
任务计划测试
============
计划是长任务的外部记事板：模型走到第七八步时不靠记忆，而是读状态。

这里重点测两件事：
1. 校验足够严——模型给的东西千奇百怪，坏数据不能进状态；
2. 计划真的落进图状态并随 checkpointer 持久化，而不是只出现在某条消息里。

运行：pytest tests/test_plan.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNormalize:
    def test_accepts_well_formed_plan(self):
        from app.agent.plan import normalize

        steps, err = normalize([
            {"content": "读懂现有实现", "status": "completed"},
            {"content": "改写核心逻辑", "status": "in_progress"},
            {"content": "补测试", "status": "pending"},
        ])
        assert err is None
        assert [s["status"] for s in steps] == ["completed", "in_progress", "pending"]
        assert [s["id"] for s in steps] == ["1", "2", "3"]

    def test_accepts_plain_strings(self):
        """模型常常直接给字符串数组，容忍它并默认 pending。"""
        from app.agent.plan import normalize

        steps, err = normalize(["第一步", "第二步"])
        assert err is None
        assert all(s["status"] == "pending" for s in steps)

    def test_rejects_multiple_in_progress(self):
        """允许多个进行中的话，模型会把所有步骤一次性标成进行中，
        记事板就退化成一张静态清单。"""
        from app.agent.plan import normalize

        _steps, err = normalize([
            {"content": "a", "status": "in_progress"},
            {"content": "b", "status": "in_progress"},
        ])
        assert err and "只能有一个" in err

    @pytest.mark.parametrize("bad,keyword", [
        ("不是数组", "数组"),
        ([], "不能为空"),
        ([{"status": "pending"}], "缺少 content"),
        ([{"content": "x", "status": "做完了"}], "无效"),
        ([{"content": f"step{i}"} for i in range(50)], "过多"),
    ])
    def test_rejects_malformed(self, bad, keyword):
        from app.agent.plan import normalize

        steps, err = normalize(bad)
        assert steps == []
        assert err and keyword in err, f"错误信息应说明原因，实际：{err}"

    def test_error_messages_are_actionable(self):
        """错误要让模型能自己改对，而不是一句「无效」。"""
        from app.agent.plan import normalize

        _s, err = normalize([{"content": "x", "status": "doing"}])
        assert "pending" in err and "in_progress" in err and "completed" in err


class TestUpdatePlanTool:
    @pytest.mark.asyncio
    async def test_returns_state_update(self):
        from app.agent.plan import StateUpdate, update_plan

        out = await update_plan.ainvoke({"steps": [
            {"content": "第一步", "status": "completed"},
            {"content": "第二步", "status": "in_progress"},
        ]})
        assert isinstance(out, StateUpdate)
        assert out.updates["plan"][0]["content"] == "第一步"
        assert "1/2 已完成" in out.text

    @pytest.mark.asyncio
    async def test_invalid_plan_does_not_touch_state(self):
        """校验失败时不能写状态——坏数据进去比不更新更糟。"""
        from app.agent.plan import update_plan

        out = await update_plan.ainvoke({"steps": [
            {"content": "a", "status": "in_progress"},
            {"content": "b", "status": "in_progress"},
        ]})
        assert out.updates == {}
        assert "计划未更新" in out.text

    def test_render_shows_progress(self):
        from app.agent.plan import render

        text = render([
            {"id": "1", "content": "做完的", "status": "completed"},
            {"id": "2", "content": "在做的", "status": "in_progress"},
            {"id": "3", "content": "没做的", "status": "pending"},
        ])
        assert "1/3 已完成" in text
        assert "✔" in text and "▶" in text and "○" in text


class TestPlanReachesGraphState:
    """计划必须进图状态并随 checkpointer 持久化，不能只留在某条消息里。"""

    @pytest.mark.asyncio
    async def test_tools_node_merges_plan_into_state(self):
        from app.agent.nodes.tools_node import tools_node
        from app.agent.plan import PLAN_TOOLS
        from app.agent.registry import ToolRisk, register_tools

        register_tools(PLAN_TOOLS, ToolRisk.READ)

        class _Msg:
            tool_calls = [{
                "id": "c1", "name": "update_plan",
                "args": {"steps": [{"content": "唯一一步", "status": "in_progress"}]},
            }]

        out = await tools_node({"messages": [_Msg()]}, {}, lambda _e: None)
        assert "plan" in out, f"tools_node 应把计划并进状态，实际返回 {list(out)}"
        assert out["plan"][0]["content"] == "唯一一步"

    @pytest.mark.asyncio
    async def test_plan_event_is_emitted(self):
        """单独推 plan_updated 事件，客户端才能把计划渲染成常驻面板。"""
        from app.agent.nodes.tools_node import tools_node
        from app.agent.plan import PLAN_TOOLS
        from app.agent.registry import ToolRisk, register_tools

        register_tools(PLAN_TOOLS, ToolRisk.READ)
        events = []

        class _Msg:
            tool_calls = [{
                "id": "c1", "name": "update_plan",
                "args": {"steps": [{"content": "一步", "status": "pending"}]},
            }]

        await tools_node({"messages": [_Msg()]}, {}, events.append)
        assert any(e.get("type") == "plan_updated" for e in events), f"实际事件：{events}"

    def test_plan_reducer_replaces_not_appends(self):
        """每次给的都是完整快照，用追加语义会把历次堆在一起。"""
        from app.agent.state import replace_plan

        old = [{"id": "1", "content": "旧", "status": "pending"}]
        new = [{"id": "1", "content": "新", "status": "completed"}]
        assert replace_plan(old, new) == new

    @pytest.mark.asyncio
    async def test_plan_survives_checkpoint(self, tmp_path, monkeypatch):
        """跨轮次持久化：第二轮还能读到第一轮写的计划。"""
        import app.agent.graph as graph_mod
        import app.agent.nodes.agent_node as node
        import app.memory.checkpointer as cp_mod
        from app.agent.plan import PLAN_TOOLS
        from app.agent.registry import ToolRisk, register_tools
        from app.core.config import get_settings
        from app.llm.models import StreamChunk, ToolCall, Usage

        register_tools(PLAN_TOOLS, ToolRisk.READ)
        s = get_settings()
        saved = (s.storage_backend, s.sqlite_path)
        s.storage_backend, s.sqlite_path = "sqlite", str(tmp_path / "p.db")
        cp_mod._checkpointer = None
        graph_mod._compiled_graph = None

        class _Stub:
            provider_name = "stub"
            default_model = "s"

            def __init__(self):
                self.n = 0

            async def stream_chat(self, request):
                self.n += 1
                if self.n == 1:
                    yield StreamChunk(
                        content="", finish_reason="tool_calls", usage=Usage(), model="s",
                        tool_calls=[ToolCall(id="c1", name="update_plan", arguments={
                            "steps": [{"content": "被持久化的一步", "status": "in_progress"}]})],
                    )
                    return
                yield StreamChunk(content="好")
                yield StreamChunk(content="", finish_reason="stop", usage=Usage(), model="s")

        stub = _Stub()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: stub)

        try:
            from app.agent.graph import get_compiled_graph, stream_agent

            async for _ in stream_agent("做点事", "plan-persist-1"):
                pass

            graph = await get_compiled_graph()
            state = await graph.aget_state({"configurable": {"thread_id": "plan-persist-1"}})
            plan = state.values.get("plan")
            assert plan, "计划没有落进 checkpoint"
            assert plan[0]["content"] == "被持久化的一步"
        finally:
            s.storage_backend, s.sqlite_path = saved
            cp_mod._checkpointer = None
            graph_mod._compiled_graph = None
