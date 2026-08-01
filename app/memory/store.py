"""
长期记忆（Long-Term Memory / Store）
------------------------------------
跨会话的用户记忆：记住用户的偏好、事实、历史交互要点。
与短期记忆（checkpointer，单次对话内）互补。

实现：LangGraph 的 BaseStore。
- 开发期：InMemoryStore（内存，带语义检索 index）
- 生产期：PostgresStore（持久化，API 一致，平滑切换）

语义检索：store.search(namespace, query="...") 会按语义相似度排序，
需要 embedding。开发期用确定性哈希 embedding（零依赖），
生产应替换为真实 embedding 模型（如 OpenAIEmbeddings 或本地 sentence-transformers）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 开发期伪 embedding 维度
_DEV_EMBED_DIMS = 256

# 初始化锁（防并发首次调用竞态）
_init_lock = asyncio.Lock()


def _hash_embed(texts: list[str]) -> list[list[float]]:
    """确定性哈希 embedding（仅开发/测试用）。

    LangGraph 的 embed 接口期望：输入 list[str]，输出 list[list[float]]（每条文本一个向量）。
    把每条文本哈希到固定维度向量，相同文本得相同向量，
    让 InMemoryStore 的余弦相似度能跑通。
    生产环境务必替换为真实语义 embedding（如 OpenAIEmbeddings）。
    """

    def _one(text: str) -> list[float]:
        vec = [0.0] * _DEV_EMBED_DIMS
        for i, ch in enumerate(text):
            vec[i % _DEV_EMBED_DIMS] = (vec[i % _DEV_EMBED_DIMS] + ord(ch)) / 1000.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    return [_one(t) for t in texts]


_store: Optional[BaseStore] = None


async def get_store() -> BaseStore:
    """获取长期记忆 store 单例（带锁防并发首次调用竞态）。

    持久化策略（改进）：默认优先 Postgres（dev/prod 一致，重启不丢）；
    仅当 Postgres 不可用时回退 InMemoryStore（内存 + 哈希 embedding）。
    """
    global _store
    if _store is not None:
        return _store

    async with _init_lock:
        if _store is not None:
            return _store

        s = get_settings()
        # 统一优先 Postgres（dev/prod 一致）
        try:
            from langgraph.store.postgres import PostgresStore

            store = PostgresStore.from_conn_string(
                s.postgres_dsn_sync,
                index={"dims": _DEV_EMBED_DIMS, "fields": ["content"], "embed": _hash_embed},
            )
            await store.setup()  # type: ignore[attr-defined]
            _store = store
            logger.info("长期记忆：PostgresStore（持久化，重启不丢）")
        except Exception as e:  # noqa: BLE001
            # Postgres 不可用 → 回退内存
            _store = InMemoryStore(index={"embed": _hash_embed, "dims": _DEV_EMBED_DIMS, "fields": ["content"]})
            logger.warning("长期记忆：Postgres 不可用，回退 InMemoryStore（重启将丢失）：%s", e)

    return _store


def user_namespace(user_id: str, tenant_id: str = "default") -> tuple[str, ...]:
    """构造用户记忆的命名空间（支持多租户隔离）。

    namespace 是 BaseStore 的记忆隔离单元。
    多租户启用时：("tenant", tenant_id, "user", user_id)
    否则：("user", user_id)
    """
    from app.auth.tenant import memory_namespace

    return memory_namespace(tenant_id, user_id)


# ---------- 高层封装：记忆增删查 ----------


class MemoryService:
    """长期记忆的便捷操作封装。"""

    def __init__(self, store: BaseStore):
        self.store = store

    async def add_memory(self, user_id: str, content: str, *, key: str | None = None, tenant_id: str = "default") -> str:
        """为用户添加一条长期记忆。返回记忆 key。"""
        import uuid

        ns = user_namespace(user_id, tenant_id)
        mem_key = key or f"mem_{uuid.uuid4().hex[:8]}"
        await self.store.aput(ns, mem_key, {"content": content})
        logger.info("长期记忆已添加 user=%s tenant=%s key=%s: %s", user_id, tenant_id, mem_key, content[:50])
        return mem_key

    async def search_memory(self, user_id: str, query: str, *, limit: int = 5, tenant_id: str = "default") -> list[dict[str, Any]]:
        """语义检索用户的相关记忆。"""
        ns = user_namespace(user_id, tenant_id)
        items = await self.store.asearch(ns, query=query, limit=limit)
        return [
            {"key": item.key, "content": item.value.get("content", ""), "score": getattr(item, "score", None)}
            for item in items
        ]

    async def get_all_memories(self, user_id: str, *, limit: int = 50, tenant_id: str = "default") -> list[dict[str, Any]]:
        """列出用户全部记忆（不按语义排序，按时间倒序）。"""
        ns = user_namespace(user_id, tenant_id)
        try:
            all_items = await self.store.aget(ns, limit=limit)  # type: ignore[arg-type]
            if hasattr(all_items, "__iter__") and not isinstance(all_items, dict):
                return [{"key": i.key, "content": i.value.get("content", "")} for i in all_items]
        except Exception as e:  # noqa: BLE001
            logger.warning("获取全部记忆失败：%s", e)
        return []

    async def delete_memory(self, user_id: str, key: str, *, tenant_id: str = "default") -> None:
        """删除用户的一条记忆。"""
        await self.store.adelete(user_namespace(user_id, tenant_id), key)
        logger.info("长期记忆已删除 user=%s key=%s", user_id, key)


_memory_service: Optional[MemoryService] = None


async def get_memory_service() -> MemoryService:
    """获取 MemoryService 单例。"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService(await get_store())
    return _memory_service
