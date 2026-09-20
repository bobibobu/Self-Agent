"""
RAG 服务
--------
- 文档分块（滑动窗口 + 重叠，可选 contextual 增强前缀）
- 入库（存入 BaseStore，复用语义索引）
- 检索（Hybrid：向量语义 + 关键词两路，RRF 融合）

知识库用 namespace 隔离：("kb", kb_id)。
不同知识库互不干扰。

Hybrid 检索（2026-09 升级）：
    原实现只有单路向量检索——孤立 chunk 脱离原文语境，专有名词/代号/编号
    这类「精确字面」查询经常排不进 top-k。现在加一条关键词通道：
    - 向量通道：store.asearch(query=...)，语义相近但字面不同的块
    - 关键词通道：直接查 PostgresStore 的 store 表（prefix 定位本知识库，
      value->>'content' 上做 ILIKE 子串命中，CJK 查询切二元组），
      字面精确命中但语义模型不认识的块
    两路排名用 Reciprocal Rank Fusion（RRF）融合，谁也不压谁。
    关键词通道依赖 Postgres（共享连接池），不可用时静默退化回纯向量检索，
    行为与升级前完全一致。

Contextual 分块（Anthropic Contextual Retrieval 思路）：
    入库时用 LLM 给每块生成一句「该块在全文中的位置与主题」前缀，
    与原块拼接后再向量化——embedding 看到的是「有上下文的块」而非孤立段落。
    每块一次 flash 模型调用（并发有界、总量有帽），失败回退原始块，
    不阻断入库。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from functools import lru_cache
from typing import Any

from app.core.logging import get_logger
from app.memory.store import get_store

logger = get_logger(__name__)

# 分块参数
CHUNK_SIZE = 500      # 每块约 500 字符
CHUNK_OVERLAP = 50    # 块间重叠 50 字符（保上下文连贯）

# delete_kb 每轮列举的块数
_DELETE_BATCH = 200

# ---------- Hybrid 检索参数 ----------
# RRF 常数（论文标准值）：排名越靠前贡献 1/(k+rank) 越大，k 越大排名差距越平缓
RRF_K = 60
# 关键词通道取回的候选数（比最终 limit 大，给融合留余地）
_KEYWORD_CANDIDATES = 20
# 一次检索最多提取的关键词数（防长查询拖慢 ILIKE）
_MAX_KEYWORD_TERMS = 16
# contextual 增强的并发上限（每个 ingest 调用内部）
_CONTEXTUAL_CONCURRENCY = 8

# CJK（汉字 + 日文假名）连续串，用于切二元组
_CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]+")
# 西文词（字母数字下划线，>=2 字符才有区分度）
_LATIN_WORD = re.compile(r"[A-Za-z0-9_]{2,}")


def _escape_attr(text: str) -> str:
    """转义要放进 XML 属性的文本，防止 source 里带引号把标签结构撑破。"""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def chunk_text(text: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """把长文本切成重叠的小块。

    滑动窗口：每块 size 字符，相邻块重叠 overlap 字符。
    重叠保证句子被切断时不丢上下文。
    """
    if not text.strip():
        return []
    # 防 overlap >= size 导致死循环/无进展
    if overlap >= size:
        overlap = max(0, size - 1)
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap  # 回退 overlap，制造重叠
    return chunks


def keyword_terms(query: str, *, max_terms: int = _MAX_KEYWORD_TERMS) -> list[str]:
    """把查询拆成关键词匹配用的 term（去重保序，截断到 max_terms）。

    - 西文：按词切，小写化（ILIKE 大小写不敏感，小写只是去重需要）
    - CJK：没有分词器，切二元 bigram——「机器学习」→ 机器/器学/学习。
      子串命中数（hits）天然构成相关度：含「机器学习」全文的块命中 3 个
      bigram，只沾边的块命中 1 个。单个字的 CJK 串保留原字。
    """
    terms: list[str] = []
    for w in _LATIN_WORD.findall(query):
        terms.append(w.lower())
    for run in _CJK_RUN.findall(query):
        if len(run) == 1:
            terms.append(run)
            continue
        for i in range(len(run) - 1):
            terms.append(run[i : i + 2])
    # 去重保序 + 截断
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:max_terms]


def rrf_fuse(rankings: list[list[str]], *, k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion：每个通道按排名给每个 key 贡献 1/(k+rank)，跨通道累加。

    输入是各通道的 key 排名列表（第 0 名排最前），输出 key → 融合分。
    只出现在一个通道的 key 也有分（不会因为另一通道没命中就被埋掉）。
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _escape_like(text: str) -> str:
    """转义 ILIKE 的元字符（% _ \\），让 term 按字面匹配。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def kb_namespace(kb_id: str, tenant_id: str = "default") -> tuple[str, ...]:
    """知识库命名空间（按租户隔离）。

    原实现是固定的 ("kb", kb_id)，不带租户——配合当时无鉴权的 RAG 路由，
    任何人只要猜到 kb_id 就能跨租户读写删他人知识库。
    """
    from app.core.config import get_settings

    if get_settings().multi_tenant_enabled:
        return ("tenant", tenant_id, "kb", kb_id)
    return ("kb", kb_id)


# ---------- 关键词通道（Postgres） ----------


async def _keyword_search(
    pool: Any, ns: tuple[str, ...], terms: list[str], limit: int
) -> list[dict[str, Any]]:
    """在 PostgresStore 的 store 表上做关键词子串检索。

    直接查 LangGraph 管理的表而不是另建一份索引：单一存储、老数据天然可查。
    prefix 列就是 ".".join(namespace)（见 langgraph store/postgres/base.py 的
    _namespace_to_text），等值匹配走主键索引，只扫本知识库的行。

    抛出的任何异常由调用方捕获降级——langgraph 未来改表结构时，
    表现应是「退回纯向量检索」而不是报错。
    """
    patterns = [f"%{_escape_like(t)}%" for t in terms]
    sql = """
        SELECT key,
               value->>'content' AS content,
               value->>'source' AS source,
               (SELECT count(*) FROM unnest(%s::text[]) AS t(term)
                 WHERE value->>'content' ILIKE '%' || term || '%') AS hits
        FROM store
        WHERE prefix = %s
          AND value->>'content' ILIKE ANY(%s::text[])
        ORDER BY hits DESC, updated_at DESC
        LIMIT %s
    """
    params: list[Any] = [terms, ".".join(ns), patterns, limit]
    rows: list[dict[str, Any]] = []
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [
        {"key": r["key"], "content": r["content"] or "", "source": r["source"] or ""}
        for r in rows
    ]


# ---------- Contextual 分块（LLM 上下文前缀） ----------

_CONTEXT_SYSTEM_PROMPT = (
    "你是文档检索预处理助手。给你一篇文档的节选和其中一个片段，"
    "请用一句不超过 60 字的中文说明：该片段讲什么、在文档整体主题中的位置。"
    "只输出这一句话，不要任何前后缀、引号或解释。"
)


@lru_cache
def _utility_llm() -> tuple[Any, str, bool]:
    """contextual 分块用的工具型小任务客户端。

    返回 (async 客户端, 模型名, 是否关闭思考模式)。
    GLM 的 4.5 系列是推理模型，**默认开思考**——实测一个 150 token 的小任务
    思考阶段就要 25s+，直接把入库拖到分钟级，所以必须显式关掉
    （extra_body 透传 GLM 私有参数 thinking；OpenAI 会拒绝未知参数，不能带）。
    优先 GLM，退而 OpenAI；都没有时返回 (None, "", False)，
    由调用方回退到 LLMClient 抽象层（覆盖 anthropic 等其它 provider）。
    """
    from openai import AsyncOpenAI

    from app.core.config import get_settings

    s = get_settings()
    if s.glm_api_key:
        client = AsyncOpenAI(
            api_key=s.glm_api_key, base_url=s.glm_base_url,
            timeout=s.llm_timeout_seconds, max_retries=s.llm_max_retries,
        )
        return client, (s.rag_contextual_model or s.glm_model), True
    if s.openai_api_key:
        client = AsyncOpenAI(
            api_key=s.openai_api_key, base_url=s.openai_base_url,
            timeout=s.llm_timeout_seconds, max_retries=s.llm_max_retries,
        )
        return client, (s.rag_contextual_model or s.openai_model), False
    return None, "", False


async def _generate_chunk_context(doc_excerpt: str, chunk: str) -> str:
    """调 LLM 生成单个 chunk 的上下文前缀。失败抛异常由调用方回退。"""
    client, model, disable_thinking = _utility_llm()
    if client is not None:
        kwargs: dict[str, Any] = {}
        if disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _CONTEXT_SYSTEM_PROMPT},
                {"role": "user", "content": f"【文档节选（开头）】\n{doc_excerpt}\n\n【片段】\n{chunk}"},
            ],
            temperature=0.0,
            max_tokens=150,
            **kwargs,
        )
        return (resp.choices[0].message.content or "").strip()

    # 其它 provider（anthropic 等）：走统一 LLMClient 抽象层
    from app.llm.base import ChatRequest  # noqa: PLC0415
    from app.llm.factory import get_llm_client  # noqa: PLC0415
    from app.llm.models import ChatMessage  # noqa: PLC0415

    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=_CONTEXT_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"【文档节选（开头）】\n{doc_excerpt}\n\n【片段】\n{chunk}"),
        ],
        temperature=0.0,
        max_tokens=150,
    )
    resp = await get_llm_client().chat(req)
    return (resp.content or "").strip()


async def _contextualize(chunks: list[str]) -> list[str]:
    """给每块拼上下文前缀。关闭/无 key/超帽/失败的块回退原始块，绝不阻断入库。"""
    from app.core.config import get_settings

    s = get_settings()
    if not s.rag_contextual_chunking:
        return chunks
    # 没有任何 LLM key 时跳过（测试环境 / 纯离线部署）——
    # 没有模型可用，增强无从谈起，也没有必要打日志刷屏
    if not (s.glm_api_key or s.openai_api_key or s.anthropic_api_key):
        return chunks

    cap = max(0, s.rag_contextual_max_chunks)
    if not chunks or cap <= 0:
        return chunks
    targets = range(min(len(chunks), cap))

    # 文档节选给模型当「全文」用：截太短定位不了位置，太长浪费 token
    doc_excerpt = "\n".join(chunks[:3])[:1500]

    sem = asyncio.Semaphore(_CONTEXTUAL_CONCURRENCY)

    async def _one(i: int) -> tuple[int, str]:
        try:
            async with sem:
                ctx = await asyncio.wait_for(
                    _generate_chunk_context(doc_excerpt, chunks[i]), timeout=s.llm_timeout_seconds
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("chunk %d 上下文生成失败，用原始块：%s", i, e)
            return i, chunks[i]
        # 模型偶尔不听话输出引号包裹或空串——剥掉外壳、空串回退
        ctx = ctx.strip().strip('"「」').strip()
        if not ctx:
            return i, chunks[i]
        return i, f"{ctx}\n\n{chunks[i]}"

    results = await asyncio.gather(*(_one(i) for i in targets))
    out = list(chunks)
    for i, enriched in results:
        out[i] = enriched
    if len(chunks) > cap:
        logger.info("contextual 分块：共 %d 块，仅增强前 %d 块（RAG_CONTEXTUAL_MAX_CHUNKS=%d）",
                    len(chunks), cap, cap)
    return out


# ---------- 主服务 ----------


class RagService:
    """RAG 知识库服务。"""

    async def ingest(self, kb_id: str, content: str, *, source: str = "", tenant_id: str = "default") -> int:
        """把文档内容分块后存入知识库。返回入库块数。"""
        base_chunks = chunk_text(content)
        if not base_chunks:
            return 0
        chunks = await _contextualize(base_chunks)

        store = await get_store()
        ns = kb_namespace(kb_id, tenant_id)
        source_hash = hashlib.md5(content.encode()).hexdigest()[:8]

        for i, enriched in enumerate(chunks):
            key = f"{source_hash}_{i}"
            # raw 是未增强的原文；content 是（可能带上下文前缀的）实际被向量化的文本
            await store.aput(ns, key, {
                "content": enriched,
                "raw": base_chunks[i],
                "source": source,
                "chunk_index": i,
            })

        logger.info("RAG 入库 kb=%s tenant=%s：%d 块（来源=%s）", kb_id, tenant_id, len(chunks), source or "未知")
        return len(chunks)

    async def search(
        self, kb_id: str, query: str, *, limit: int = 4, tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        """Hybrid 检索知识库：向量语义 + 关键词两路，RRF 融合。

        Postgres 不可用或关键词通道出错时，自动退化为纯向量检索
        （与升级前行为一致）。返回按融合分排序的块列表。
        """
        store = await get_store()
        ns = kb_namespace(kb_id, tenant_id)
        try:
            dense_items = await store.asearch(ns, query=query, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 检索失败：%s", e)
            return []

        dense_ranking = [item.key for item in dense_items]
        rankings = [dense_ranking]
        # key → 块数据。向量通道的数据直接取自返回项；关键词通道的稍后补进
        by_key: dict[str, dict[str, Any]] = {
            item.key: {
                "content": (item.value or {}).get("content", ""),
                "source": (item.value or {}).get("source", ""),
            }
            for item in dense_items
        }
        matched: dict[str, set[str]] = {k: {"dense"} for k in dense_ranking}

        await self._merge_keyword_channel(ns, query, rankings, by_key, matched)

        scores = rrf_fuse(rankings)
        ordered = sorted(scores, key=lambda k: scores[k], reverse=True)[:limit]
        return [
            {
                "content": by_key[k]["content"],
                "source": by_key[k]["source"],
                "score": round(scores[k], 4),
                "match": sorted(matched[k]),
            }
            for k in ordered
            if by_key[k]["content"]
        ]

    async def _merge_keyword_channel(
        self,
        ns: tuple[str, ...],
        query: str,
        rankings: list[list[str]],
        by_key: dict[str, dict[str, Any]],
        matched: dict[str, set[str]],
    ) -> None:
        """把关键词通道的结果并进融合输入。任何失败都静默跳过（退化为纯向量）。"""
        from app.core.config import get_settings

        if not get_settings().rag_hybrid_search:
            return
        terms = keyword_terms(query)
        if not terms:
            return
        try:
            # 函数内 import：conftest 把 pg.get_pg_pool 打成 None 后，
            # 这里在调用时才解析，测试环境拿到的就是 None → 干净跳过
            from app.memory.pg import get_pg_pool

            pool = await get_pg_pool()
            if pool is None:
                return
            rows = await _keyword_search(pool, ns, terms, _KEYWORD_CANDIDATES)
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 关键词通道不可用，退化纯向量检索：%s", e)
            return

        kw_ranking = [r["key"] for r in rows]
        rankings.append(kw_ranking)
        for r in rows:
            if r["key"] not in by_key:
                by_key[r["key"]] = {"content": r["content"], "source": r["source"]}
            matched.setdefault(r["key"], set()).add("keyword")

    async def build_context(
        self, kb_ids: list[str], query: str, *, limit_per_kb: int = 3, tenant_id: str = "default",
    ) -> str:
        """为对话构建 RAG 上下文（并发检索多个知识库，拼接成文本）。

        检索到的内容会被包进 <document> 标签——它是不可信输入，
        必须和系统指令有明确边界，否则投毒文档可以直接改写 Agent 的行为。
        """
        if not kb_ids:
            return ""

        # 多个知识库并发检索，而不是串行 await（原来 N 个 kb 就是 N 倍延迟）
        results_per_kb = await asyncio.gather(
            *(self.search(kb_id, query, limit=limit_per_kb, tenant_id=tenant_id) for kb_id in kb_ids),
            return_exceptions=True,
        )

        all_chunks: list[str] = []
        # strict=True：gather 保序且长度一致，若不等说明逻辑出错，宁可直接炸也别静默错配来源
        for kb_id, results in zip(kb_ids, results_per_kb, strict=True):
            if isinstance(results, BaseException):
                logger.warning("知识库 %s 检索异常：%s", kb_id, results)
                continue
            for r in results:
                content = (r.get("content") or "").strip()
                if not content:
                    continue
                src = r.get("source") or kb_id
                all_chunks.append(
                    f'<document source="{_escape_attr(str(src))}">\n{content}\n</document>'
                )
        return "\n".join(all_chunks)

    async def delete_kb(self, kb_id: str, *, tenant_id: str = "default") -> int:
        """删除整个知识库。返回实际删除的块数。

        用 asearch 分页列举再逐个删——aget 是「按 key 取单条」，
        签名 aget(namespace, key)，没有 limit 参数（原写法必抛 TypeError，
        被 except 吞掉后表现为「删除成功但一条没删」）。
        """
        store = await get_store()
        ns = kb_namespace(kb_id, tenant_id)
        count = 0
        try:
            while True:
                # 每轮都从头查：删掉一批后剩余项会前移，用 offset 反而会漏
                items = await store.asearch(ns, limit=_DELETE_BATCH)
                if not items:
                    break
                for item in items:
                    await store.adelete(ns, item.key)
                    count += 1
                if len(items) < _DELETE_BATCH:
                    break
            logger.info("RAG 删除 kb=%s tenant=%s：%d 块", kb_id, tenant_id, count)
            return count
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 删除失败（已删 %d 块）：%s", count, e)
            return count


_rag_service: RagService | None = None


def get_rag_service() -> RagService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service


def reset_rag_utility_llm() -> None:
    """清空 contextual 分块的客户端缓存（lru_cache 持有旧 key/模型）。

    供运行时配置热替换（/admin/llm-config）调用。
    """
    _utility_llm.cache_clear()
