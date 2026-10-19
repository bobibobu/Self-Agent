"""
性能优化回归测试
================
锁住三项热路径优化的行为（2026-08 性能改造）：

1. 工具 schema 缓存（bridge.build_tool_definitions）
2. 上下文摘要缓存 + 迟滞（context_manager.compress_if_needed）
3. 提示词文件读取缓存（prompt_store.get_current_prompt）
"""

from __future__ import annotations

import asyncio as _asyncio
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

# ==================== 1. 工具 schema 缓存 ====================


class TestToolDefinitionCache:
    def test_same_tools_return_cached_instance(self):
        """同一批工具重复调用应命中缓存：返回同一对象，不再重算 schema。"""
        from app.agent.nodes import bridge
        from app.agent.tools import ALL_TOOLS

        bridge._tool_def_cache.clear()
        first = bridge.build_tool_definitions(ALL_TOOLS)
        second = bridge.build_tool_definitions(ALL_TOOLS)
        assert first == second
        # 缓存命中返回的是同一个 ToolDefinition 实例（未重新构造）
        assert first[0] is second[0]

    def test_cache_invalidation_on_schema_change(self, monkeypatch):
        """换了 args_schema 类（如 MCP 重建工具）应失效重算。"""
        from langchain_core.tools import tool
        from pydantic import BaseModel

        from app.agent.nodes import bridge

        class ArgsV1(BaseModel):
            x: int

        class ArgsV2(BaseModel):
            x: int
            y: int = 0

        holder = {"schema": ArgsV1}

        @tool("cache_probe_tool", args_schema=holder["schema"])
        def probe(x: int) -> int:
            """探测工具。"""
            return x

        bridge._tool_def_cache.clear()
        d1 = bridge.build_tool_definitions([probe])
        assert "x" in d1[0].parameters.get("properties", {})

        # 换 schema 类后重新注册同名工具 → 缓存必须失效
        holder["schema"] = ArgsV2

        @tool("cache_probe_tool", args_schema=holder["schema"])
        def probe2(x: int, y: int = 0) -> int:
            """探测工具。"""
            return x + y

        d2 = bridge.build_tool_definitions([probe2])
        assert "y" in d2[0].parameters.get("properties", {})


# ==================== 2. 上下文摘要缓存 ====================


def _mk_dialog(n: int, id_prefix: str = "m") -> list:
    """构造 n 条带 id 的 user/assistant 交替对话。"""
    msgs = []
    for i in range(n):
        role = HumanMessage if i % 2 == 0 else AIMessage
        m = role(content=f"消息{i}")
        m.id = f"{id_prefix}-{i}"
        msgs.append(m)
    return msgs


class _SummaryCountingLLM:
    """计数 mock：记录摘要 LLM 被调几次、每次是否带增量基摘要。"""

    def __init__(self):
        self.calls = 0
        self.base_summaries: list[bool] = []

    @property
    def provider_name(self):
        return "mock"

    async def chat(self, request):
        self.calls += 1
        prompt = request.messages[0].content
        self.base_summaries.append("[此前对话的已有摘要]" in prompt)
        from app.llm.models import ChatResponse, Usage
        return ChatResponse(
            content=f"摘要第{self.calls}版",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="mock", finish_reason="stop",
        )


class TestSummaryCache:
    @pytest.fixture()
    def counting_llm(self, monkeypatch):
        llm = _SummaryCountingLLM()
        import app.agent.context_manager as cm
        monkeypatch.setattr(cm, "get_llm_client", lambda provider=None: llm)
        cm._summary_cache.clear()
        return llm

    def test_short_history_no_compression(self, counting_llm):
        from app.agent.context_manager import compress_if_needed
        msgs = _mk_dialog(10)
        out = asyncio_run(compress_if_needed(msgs, thread_key="t1"))
        assert out == msgs
        assert counting_llm.calls == 0

    def test_cache_reuses_summary_within_hysteresis(self, counting_llm):
        """迟滞窗口内（新增早期消息 < _COMPRESS_EVERY）复用旧摘要，不再调 LLM。"""
        from app.agent import context_manager as cm

        out1 = asyncio_run(cm.compress_if_needed(_mk_dialog(30), thread_key="t2"))
        assert counting_llm.calls == 1
        assert out1[0].content.startswith("【早期对话摘要】")

        # 同一会话追加 2 条新消息 → 触发压缩但复用缓存摘要
        msgs2 = _mk_dialog(32)
        out2 = asyncio_run(cm.compress_if_needed(msgs2, thread_key="t2"))
        assert counting_llm.calls == 1  # 没有新的 LLM 调用
        assert "摘要第1版" in out2[0].content

    def test_incremental_summary_after_threshold(self, counting_llm):
        """攒够 _COMPRESS_EVERY 条新早期消息后做一次增量摘要（带旧摘要）。"""
        from app.agent import context_manager as cm

        asyncio_run(cm.compress_if_needed(_mk_dialog(30), thread_key="t3"))
        assert counting_llm.calls == 1

        msgs2 = _mk_dialog(30 + cm._COMPRESS_EVERY + 2)
        out2 = asyncio_run(cm.compress_if_needed(msgs2, thread_key="t3"))
        assert counting_llm.calls == 2  # 恰好一次增量摘要
        assert counting_llm.base_summaries[-1] is True  # 增量：prompt 里有旧摘要
        assert "摘要第2版" in out2[0].content

    def test_cache_miss_on_thread_mismatch(self, counting_llm):
        """不同 thread_key 不共享缓存：各自全量摘要一次。"""
        from app.agent.context_manager import compress_if_needed
        asyncio_run(compress_if_needed(_mk_dialog(30), thread_key="ta"))
        asyncio_run(compress_if_needed(_mk_dialog(30), thread_key="tb"))
        assert counting_llm.calls == 2

    def test_cache_invalidated_on_boundary_id_mismatch(self, counting_llm):
        """边界消息 id 变了（会话重置）→ 缓存作废，全量重摘。"""
        from app.agent import context_manager as cm
        asyncio_run(cm.compress_if_needed(_mk_dialog(30, "a"), thread_key="t4"))
        # 前缀相同但 id 序列不同 → 视为不同历史
        asyncio_run(cm.compress_if_needed(_mk_dialog(30, "b"), thread_key="t4"))
        assert counting_llm.calls == 2

    def test_tool_message_boundary_safety(self, counting_llm):
        """近期消息不能以 ToolMessage 开头（其配对的 AIMessage 不能被摘要掉）。"""
        from app.agent.context_manager import compress_if_needed
        msgs = _mk_dialog(30)
        tm = ToolMessage(content="结果", tool_call_id="c1", name="calc")
        tm.id = "tool-1"
        msgs.append(tm)  # 末尾一条 ToolMessage，切点必须跳过它
        out = asyncio_run(compress_if_needed(msgs, thread_key="t5"))
        assert out[-1] is tm  # ToolMessage 保留在近期

    def test_no_thread_key_still_works(self, counting_llm):
        """不传 thread_key（兼容旧调用方）→ 走全量摘要，行为不变。"""
        from app.agent.context_manager import compress_if_needed
        out = asyncio_run(compress_if_needed(_mk_dialog(30)))
        assert counting_llm.calls == 1
        assert out[0].content.startswith("【早期对话摘要】")


# ==================== 3. 提示词文件缓存 ====================


class TestPromptStoreCache:
    def test_cache_invalidates_on_save(self, tmp_path, monkeypatch):
        """save_version 写入新版本后，下一次读取必须拿到新内容（缓存失效）。"""
        import app.evolution.prompt_store as ps

        monkeypatch.setattr(ps, "_PROMPTS_DIR", tmp_path)
        monkeypatch.setattr(ps, "_CURRENT_FILE", tmp_path / "current.json")
        ps._current_prompt_cache = None

        ps.save_version("第一版提示词", source="test")
        assert ps.get_current_prompt() == "第一版提示词"

        ps.save_version("第二版提示词", source="test")
        assert ps.get_current_prompt() == "第二版提示词"  # mtime 变化 → 缓存失效

    def test_missing_file_falls_back_to_builtin(self, tmp_path, monkeypatch):
        import app.evolution.prompt_store as ps
        from app.agent.prompts import SYSTEM_PROMPT

        monkeypatch.setattr(ps, "_PROMPTS_DIR", tmp_path)
        monkeypatch.setattr(ps, "_CURRENT_FILE", tmp_path / "current.json")
        ps._current_prompt_cache = None
        assert ps.get_current_prompt() == SYSTEM_PROMPT


# ==================== helpers ====================

def asyncio_run(coro):
    return _asyncio.run(coro)
