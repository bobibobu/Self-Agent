"""RAG Hybrid 检索 + Contextual 分块 + Agentic RAG 工具
=====================================================
覆盖 2026-09 RAG 升级的三块新能力：

1. keyword_terms / rrf_fuse：关键词通道的查询拆词（CJK 二元组）与
   Reciprocal Rank Fusion 纯函数。
2. hybrid search：ingest → search 往返，结果带 match 通道标记；
   Postgres 不可用时（conftest 把连接池打成 None）干净退化纯向量。
3. search_knowledge_base 工具：configurable 注入 kb_ids/tenant_id、
   越权防护（未关联的 kb 拒绝）、config 不漏进工具 schema。

测试环境（见 conftest）：InMemoryStore + 哈希伪向量 + 无 LLM key，
所以 contextual 分块默认跳过——增强路径用假 LLM 显式打开来测。
"""

from __future__ import annotations

import pytest


# ==================== 1. 纯函数 ====================


class TestKeywordTerms:
    def test_latin_words_lowercased(self):
        from app.rag.service import keyword_terms

        assert keyword_terms("Self-Agent API v2") == ["self", "agent", "api", "v2"]

    def test_cjk_bigrams(self):
        from app.rag.service import keyword_terms

        # 「机器学习」→ 3 个二元组，全部有序去重
        assert keyword_terms("机器学习") == ["机器", "器学", "学习"]

    def test_cjk_single_char_kept(self):
        from app.rag.service import keyword_terms

        assert keyword_terms("猫") == ["猫"]

    def test_mixed_and_dedup(self):
        from app.rag.service import keyword_terms

        terms = keyword_terms("RAG 检索 检索")
        assert terms.count("检索") == 1  # 去重保序
        assert "rag" in terms

    def test_max_terms_truncates(self):
        from app.rag.service import keyword_terms

        assert len(keyword_terms("一二三四五六七八九十甲乙丙丁戊己庚辛壬癸")) <= 16


class TestRrfFuse:
    def test_single_channel_preserves_order(self):
        from app.rag.service import rrf_fuse

        scores = rrf_fuse([["a", "b", "c"]])
        assert sorted(scores, key=scores.get, reverse=True) == ["a", "b", "c"]
        assert scores["a"] == pytest.approx(1 / 61)

    def test_both_channels_beats_single(self):
        from app.rag.service import rrf_fuse

        # b 在两个通道都出现 → 融合分必须高于只在单通道出现的 a/c
        scores = rrf_fuse([["a", "b"], ["c", "b"]])
        assert scores["b"] > scores["a"]
        assert scores["b"] > scores["c"]
        assert scores["b"] == pytest.approx(1 / 62 + 1 / 62)

    def test_empty_channels(self):
        from app.rag.service import rrf_fuse

        assert rrf_fuse([]) == {}
        assert rrf_fuse([[]]) == {}


class TestEscapeLike:
    def test_escapes_metacharacters(self):
        from app.rag.service import _escape_like

        assert _escape_like("100%") == "100\\%"
        assert _escape_like("a_b") == "a\\_b"
        assert _escape_like("c:\\path") == "c:\\\\path"


# ==================== 2. Hybrid search 往返 ====================


class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_ingest_search_roundtrip_with_match_info(self):
        """ingest → search 往返：结果带 match 通道标记，InMemory 下退化为纯 dense。"""
        from app.rag.service import get_rag_service

        rag = get_rag_service()
        n = await rag.ingest("kb_hybrid", "自注意力机制是 Transformer 的核心组件" * 20, source="attn.md")
        assert n > 0

        results = await rag.search("kb_hybrid", "Transformer 自注意力", limit=4)
        assert results, "小知识库至少应返回刚入库的块"
        for r in results:
            assert r["content"]
            assert r["match"] == ["dense"]  # Postgres 不可用 → 只剩向量通道
            assert 0 < r["score"] <= 0.02  # 单通道 RRF 首名 = 1/61 ≈ 0.0164

    @pytest.mark.asyncio
    async def test_search_empty_kb_returns_empty(self):
        from app.rag.service import get_rag_service

        assert await get_rag_service().search("kb_empty_xyz", "随便") == []


# ==================== 3. Contextual 分块 ====================


class TestContextualChunking:
    @pytest.mark.asyncio
    async def test_enrichment_prepends_context(self, monkeypatch):
        """开关键与 LLM 可用性都满足时，块内容应带上生成的上下文前缀。"""
        from app.core.config import get_settings
        from app.rag.service import get_rag_service
        from app.rag import service as rag_mod

        async def _fake_ctx(doc_excerpt: str, chunk: str) -> str:
            return "本片段出自 Transformer 论文，讨论自注意力机制。"

        monkeypatch.setattr(rag_mod, "_generate_chunk_context", _fake_ctx)

        s = get_settings()
        saved = (s.rag_contextual_chunking, s.rag_contextual_max_chunks, s.glm_api_key)
        s.rag_contextual_chunking = True
        s.rag_contextual_max_chunks = 64
        s.glm_api_key = "test-key"  # conftest 清空了 key，显式打开走增强路径
        try:
            rag = get_rag_service()
            await rag.ingest("kb_ctx_enrich", "注意力就是一切你需要的" * 30, source="paper.md")
            results = await rag.search("kb_ctx_enrich", "注意力", limit=4)
        finally:
            s.rag_contextual_chunking, s.rag_contextual_max_chunks, s.glm_api_key = saved

        assert results
        assert results[0]["content"].startswith("本片段出自 Transformer 论文")

    @pytest.mark.asyncio
    async def test_skipped_without_llm_key(self):
        """没有 LLM key（conftest 默认环境）：入库内容就是原始块，不增强。"""
        from app.rag.service import _contextualize, chunk_text

        chunks = chunk_text("纯文本内容" * 100)
        out = await _contextualize(chunks)
        assert out == chunks

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_raw_chunk(self, monkeypatch):
        """单块 LLM 调用失败：该块回退原文，不阻断入库。"""
        from app.rag.service import _contextualize, chunk_text

        async def _boom(doc_excerpt: str, chunk: str) -> str:
            raise RuntimeError("LLM 挂了")

        monkeypatch.setattr("app.rag.service._generate_chunk_context", _boom)

        from app.core.config import get_settings

        s = get_settings()
        saved = (s.rag_contextual_chunking, s.glm_api_key)
        s.rag_contextual_chunking, s.glm_api_key = True, "test-key"
        try:
            chunks = chunk_text("内容" * 100)
            out = await _contextualize(chunks)
        finally:
            s.rag_contextual_chunking, s.glm_api_key = saved
        assert out == chunks


# ==================== 4. search_knowledge_base 工具 ====================


class TestKbSearchTool:
    def test_config_not_in_tool_schema(self):
        """RunnableConfig 注入参数不能漏进给 LLM 的 schema，否则模型会去填它。"""
        from app.agent.tools import search_knowledge_base

        fields = search_knowledge_base.get_input_schema().model_fields
        assert "query" in fields
        assert "config" not in fields

    @pytest.mark.asyncio
    async def test_no_kb_attached(self):
        from app.agent.tools import search_knowledge_base

        out = await search_knowledge_base.ainvoke(
            {"query": "测试"}, config={"configurable": {"kb_ids": []}},
        )
        assert "没有关联知识库" in out

    @pytest.mark.asyncio
    async def test_cannot_search_unassociated_kb(self):
        """越权防护：模型指定的 kb_id 不在本次对话关联列表里 → 拒绝。"""
        from app.agent.tools import search_knowledge_base

        out = await search_knowledge_base.ainvoke(
            {"query": "测试", "kb_id": "kb_other"},
            config={"configurable": {"kb_ids": ["kb_mine"], "tenant_id": "default"}},
        )
        assert "未关联" in out

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self):
        from app.agent.tools import search_knowledge_base
        from app.rag.service import get_rag_service

        await get_rag_service().ingest("kb_tool", "向量数据库 pgvector 支持近似最近邻检索" * 20, source="pg.md")
        out = await search_knowledge_base.ainvoke(
            {"query": "pgvector 近似检索"},
            config={"configurable": {"kb_ids": ["kb_tool"], "tenant_id": "default"}},
        )
        assert "pg.md" in out  # 来源标注
        assert "dense" in out  # 命中通道标记
