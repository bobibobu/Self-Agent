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

import hashlib
import uuid
from typing import Any, Optional

from app.core.logging import get_logger
from app.memory.store import get_store

logger = get_logger(__name__)

# 分块参数
CHUNK_SIZE = 500      # 每块约 500 字符
CHUNK_OVERLAP = 50    # 块间重叠 50 字符（保上下文连贯）


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


def kb_namespace(kb_id: str) -> tuple[str, str]:
    """知识库命名空间。"""
    return ("kb", kb_id)


class RagService:
    """RAG 知识库服务。"""

    async def ingest(self, kb_id: str, content: str, *, source: str = "") -> int:
        """把文档内容分块后存入知识库。返回入库块数。"""
        chunks = chunk_text(content)
        if not chunks:
            return 0

        store = await get_store()
        ns = kb_namespace(kb_id)
        source_hash = hashlib.md5(content.encode()).hexdigest()[:8]

        for i, chunk in enumerate(chunks):
            key = f"{source_hash}_{i}"
            await store.aput(ns, key, {
                "content": chunk,
                "source": source,
                "chunk_index": i,
            })

        logger.info("RAG 入库 kb=%s：%d 块（来源=%s）", kb_id, len(chunks), source or "未知")
        return len(chunks)

    async def search(self, kb_id: str, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        """语义检索知识库中与 query 相关的块。"""
        store = await get_store()
        ns = kb_namespace(kb_id)
        try:
            items = await store.asearch(ns, query=query, limit=limit)
            return [
                {
                    "content": item.value.get("content", ""),
                    "source": item.value.get("source", ""),
                    "score": getattr(item, "score", None),
                }
                for item in items
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 检索失败：%s", e)
            return []

    async def build_context(self, kb_ids: list[str], query: str, *, limit_per_kb: int = 3) -> str:
        """为对话构建 RAG 上下文（检索多个知识库，拼接成文本）。"""
        if not kb_ids:
            return ""
        all_chunks: list[str] = []
        for kb_id in kb_ids:
            results = await self.search(kb_id, query, limit=limit_per_kb)
            for r in results:
                if r.get("content"):
                    src = f"（来源: {r['source']}）" if r.get("source") else ""
                    all_chunks.append(f"{r['content']}{src}")
        if not all_chunks:
            return ""
        return "\n\n".join(all_chunks)

    async def delete_kb(self, kb_id: str) -> int:
        """删除整个知识库。返回大致删除数（best-effort）。"""
        store = await get_store()
        ns = kb_namespace(kb_id)
        try:
            items = await store.aget(ns, limit=10000)  # type: ignore[arg-type]
            count = 0
            if hasattr(items, "__iter__") and not isinstance(items, dict):
                for item in items:
                    await store.adelete(ns, item.key)
                    count += 1
            logger.info("RAG 删除 kb=%s：%d 块", kb_id, count)
            return count
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG 删除失败：%s", e)
            return 0


_rag_service: Optional[RagService] = None


def get_rag_service() -> RagService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service
