"""
链路追踪测试
============
用 InMemorySpanExporter 抓真实 span，断言**树的形状**而不是「有没有调用埋点」。

为什么要断言父子关系：异步生成器（stream_agent）在 Python 里没有独立
context（PEP 568 未落地），生成器体在调用方的 context 里恢复执行。
span 跨 yield 存活这件事是"能工作但很微妙"，必须用测试锁住，
否则某次重构改成从别的任务迭代，span 树会静默变平（所有 span 变成兄弟）。

运行：pytest tests/test_telemetry.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def spans():
    """装一个内存 exporter，返回取 span 的函数。测试结束后恢复原 provider。"""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # trace.set_tracer_provider 只允许设一次，这里直接改内部引用绕开
    original = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = provider
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = original


class _EchoLLM:
    """不联网的 LLM 桩，可选地返回一次工具调用。"""

    def __init__(self, with_tool: bool = False):
        self.with_tool = with_tool
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "stub"

    async def stream_chat(self, request):
        from app.llm.models import StreamChunk, ToolCall, Usage

        self.calls += 1
        # 第一次带工具调用，第二次（工具结果回填后）出文本
        if self.with_tool and self.calls == 1:
            yield StreamChunk(
                content="",
                tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})],
                finish_reason="tool_calls",
                usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model="stub-model",
            )
            return
        for ch in "好的":
            yield StreamChunk(content=ch)
        yield StreamChunk(
            content="", finish_reason="stop",
            usage=Usage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
            model="stub-model",
        )


def _by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


def _children_of(exporter, parent_name: str):
    finished = exporter.get_finished_spans()
    parent = next((s for s in finished if s.name == parent_name), None)
    assert parent is not None, f"没找到 span {parent_name}，实际有：{[s.name for s in finished]}"
    pid = parent.context.span_id
    return [s for s in finished if s.parent and s.parent.span_id == pid]


# ==================== 非流式路径 ====================


class TestRunAgentTracing:
    @pytest.mark.asyncio
    async def test_turn_span_tree(self, spans, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        await run_agent("你好", thread_id="otel-1")

        names = _by_name(spans)
        assert "agent.turn" in names
        assert "context.build" in names
        assert "chat stub-model" in names or any(n.startswith("chat ") for n in names)

        # context.build 与 chat 都必须挂在 agent.turn 下，而不是各自成根
        child_names = {s.name for s in _children_of(spans, "agent.turn")}
        assert "context.build" in child_names, f"context.build 未挂在 turn 下：{child_names}"
        assert any(n.startswith("chat ") for n in child_names), f"chat 未挂在 turn 下：{child_names}"

    @pytest.mark.asyncio
    async def test_llm_span_has_genai_attributes(self, spans, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await run_agent("你好", thread_id="otel-2")

        chat = next(s for s in spans.get_finished_spans() if s.name.startswith("chat "))
        attrs = chat.attributes
        assert attrs["gen_ai.system"] == "stub"
        assert attrs["gen_ai.operation.name"] == "chat"
        # token 用量是成本归因的基础，必须落到 span 上
        assert attrs["gen_ai.usage.input_tokens"] == 20
        assert attrs["gen_ai.usage.output_tokens"] == 8
        assert attrs["gen_ai.response.finish_reasons"] == ("stop",)

    @pytest.mark.asyncio
    async def test_one_chat_span_per_turn(self, spans, monkeypatch):
        """回归护栏：「每轮调两次 LLM」那个 bug 会表现为一个 turn 里两条 chat span。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await run_agent("你好", thread_id="otel-3")

        chats = [s for s in spans.get_finished_spans() if s.name.startswith("chat ")]
        assert len(chats) == 1, f"一轮无工具对话应只有 1 条 chat span，实际 {len(chats)}"

    @pytest.mark.asyncio
    async def test_tool_span_nested_under_turn(self, spans, monkeypatch):
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM(with_tool=True)
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await run_agent("算一下 1+1", thread_id="otel-4")

        names = _by_name(spans)
        assert "execute_tool calculator" in names, f"实际 span：{list(names)}"
        tool = names["execute_tool calculator"]
        assert tool.attributes["gen_ai.tool.name"] == "calculator"
        assert tool.attributes["gen_ai.tool.call.id"] == "c1"
        # 有工具调用时应该是两次 LLM（决策 + 回填后总结），这是正常的
        chats = [s for s in spans.get_finished_spans() if s.name.startswith("chat ")]
        assert len(chats) == 2

    @pytest.mark.asyncio
    async def test_failed_turn_marks_span_error(self, spans, monkeypatch):
        """异常被吞成用户友好文案，但 span 必须标红，否则排查时看到的是"成功"。"""
        from opentelemetry.trace import StatusCode

        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        class _Boom:
            provider_name = "boom"

            async def stream_chat(self, request):
                raise RuntimeError("上游炸了")
                # 这行永不执行，但有 yield 才会被识别为异步生成器
                yield  # type: ignore[unreachable]

        boom = _Boom()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: boom)
        result = await run_agent("你好", thread_id="otel-5")

        assert "出错" in result["reply"]  # 用户拿到的是人话
        turn = _by_name(spans)["agent.turn"]
        assert turn.status.status_code == StatusCode.ERROR, "失败的 turn 必须标红"


# ==================== 流式路径（异步生成器，最容易出问题的地方）====================


class TestStreamAgentTracing:
    @pytest.mark.asyncio
    async def test_span_survives_async_generator_yields(self, spans, monkeypatch):
        """span 必须跨越整个生成器生命周期，且子 span 正确挂在它下面。

        异步生成器体在调用方 context 里恢复执行，如果哪天改成从不同任务
        迭代，这里会退化成「所有 span 都是根 span」的扁平结构。
        """
        import app.agent.nodes.agent_node as node
        from app.agent.graph import stream_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        events = [e async for e in stream_agent("你好", thread_id="otel-stream-1")]
        assert any(e["type"] == "done" for e in events)

        names = _by_name(spans)
        assert "agent.turn" in names
        turn = names["agent.turn"]
        assert turn.attributes["selfagent.streaming"] is True

        child_names = {s.name for s in _children_of(spans, "agent.turn")}
        assert "context.build" in child_names, f"流式下 context.build 脱离了 turn：{child_names}"
        assert any(n.startswith("chat ") for n in child_names), f"流式下 chat 脱离了 turn：{child_names}"

    @pytest.mark.asyncio
    async def test_all_spans_share_one_trace(self, spans, monkeypatch):
        """一轮对话的所有 span 必须在同一条 trace 上，否则 Jaeger 里会散成多条。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import stream_agent

        llm = _EchoLLM(with_tool=True)
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        [e async for e in stream_agent("算一下 1+1", thread_id="otel-stream-2")]

        trace_ids = {s.context.trace_id for s in spans.get_finished_spans()}
        assert len(trace_ids) == 1, f"span 分散在 {len(trace_ids)} 条 trace 上，应该只有 1 条"


# ==================== 开关与隐私 ====================


class TestTelemetryToggles:
    def test_disabled_by_default(self):
        from app.core.config import get_settings

        assert get_settings().otel_enabled is False, "追踪默认应关闭"
        assert get_settings().otel_capture_content is False, "正文捕获默认必须关闭"

    @pytest.mark.asyncio
    async def test_content_not_recorded_by_default(self, spans, monkeypatch):
        """默认配置下，prompt/completion 正文不能出现在 span 里。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
        await run_agent("我的身份证号是 110101199001011234", thread_id="otel-priv")

        for s in spans.get_finished_spans():
            for ev in s.events:
                assert "110101199001011234" not in str(dict(ev.attributes)), (
                    f"正文泄漏进了 span 事件 {ev.name}"
                )

    @pytest.mark.asyncio
    async def test_content_recorded_when_enabled(self, spans, monkeypatch):
        import app.core.config as cfg
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        s = cfg.get_settings()
        orig = s.otel_capture_content
        s.otel_capture_content = True
        try:
            llm = _EchoLLM()
            monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)
            await run_agent("独特标记词ABC", thread_id="otel-priv-2")
            blob = "".join(
                str(dict(ev.attributes)) for sp in spans.get_finished_spans() for ev in sp.events
            )
            assert "独特标记词ABC" in blob, "开启后应记录正文"
        finally:
            s.otel_capture_content = orig

    def test_noop_tracer_without_provider(self):
        """未初始化时 span 应是 no-op，不抛异常也不产生成本。"""
        from app.core.telemetry import span

        with span("some.work", **{"selfagent.thread_id": "x"}) as sp:
            assert sp is not None  # no-op span 也是合法对象
