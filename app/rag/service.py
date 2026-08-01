"""
RAG 服务
--------
- 文档分块（滑动窗口 + 重叠）
- 入库（存入 BaseStore，复用语义索引）
- 检索（语义搜索相关块）

知识库用 namespace 隔离：("kb", kb_id)。
不同知识库互不干扰。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from app.core.logging import get_logger
from app.memory.store import get_store

logger = get_logger(__name__)

# 分块参数
CHUNK_SIZE = 500      # 每块约 500 字符
CHUNK_OVERLAP = 50    # 块间重叠 50 字符（保上下文连贯）

# delete_kb 每轮列举的块数
_DELETE_BATCH = 200


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


def kb_namespace(kb_id: str, tenant_id: str = "default") -> tuple[str, ...]:
    """知识库命名空间（按租户隔离）。

    原实现是固定的 ("kb", kb_id)，不带租户——配合当时无鉴权的 RAG 路由，
    任何人只要猜到 kb_id 就能跨租户读写删他人知识库。
    """
    from app.core.config import get_settings

    if get_settings().multi_tenant_enabled:
        return ("tenant", tenant_id, "kb", kb_id)
    return ("kb", kb_id)


class RagService:
    """RAG 知识库服务。"""

    async def ingest(self, kb_id: str, content: str, *, source: str = "", tenant_id: str = "default") -> int:
        """把文档内容分块后存入知识库。返回入库块数。"""
        chunks = chunk_text(content)
        if not chunks:
            return 0

        store = await get_store()
        ns = kb_namespace(kb_id, tenant_id)
        source_hash = hashlib.md5(content.encode()).hexdigest()[:8]

        for i, chunk in enumerate(chunks):
            key = f"{source_hash}_{i}"
            await store.aput(ns, key, {
                "content": chunk,
                "source": source,
                "chunk_index": i,
            })

        logger.info("RAG 入库 kb=%s tenant=%s：%d 块（来源=%s）", kb_id, tenant_id, len(chunks), source or "未知")
        return len(chunks)

    async def search(
        self, kb_id: str, query: str, *, limit: int = 4, tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        """语义检索知识库中与 query 相关的块。"""
        store = await get_store()
        ns = kb_namespace(kb_id, tenant_id)
        try:
            items = await store.asearch(ns, query=query, limit=limit)
            return [
                {
                    "content": (item.value or {}).get("content", ""),
                    "source": (item.value or {}).get("source", ""),
                    "score": getattr(item, "score", None),
                }
                for item in items
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 检索失败：%s", e)
            return []

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
