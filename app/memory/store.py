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
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.core.logging import get_logger
from app.memory.embeddings import embedding_config, get_embed_fn, log_embedding_status
from app.memory.pg import get_pg_pool

logger = get_logger(__name__)

# 初始化锁（防并发首次调用竞态）
_init_lock = asyncio.Lock()

_store: BaseStore | None = None


def _index_config() -> dict[str, Any]:
    """语义检索的索引配置（维度随实际 embedding 模型走）。"""
    _, _, dims = embedding_config()
    return {"dims": dims, "fields": ["content"], "embed": get_embed_fn()}


async def get_store() -> BaseStore:
    """获取长期记忆 store 单例（带锁防并发首次调用竞态）。

    持久化策略：优先 Postgres（dev/prod 一致，重启不丢、多进程共享）；
    Postgres 不可用时才回退 InMemoryStore。

    注意：语义索引需要 pgvector 扩展。若库里没装 vector 扩展，
    退而求其次建**无索引**的 PostgresStore——数据仍然持久化，
    只是 search(query=...) 退化为按 key 排序，不做语义排序。
    """
    global _store
    if _store is not None:
        return _store

    async with _init_lock:
        if _store is not None:
            return _store

        log_embedding_status()
        pool = await get_pg_pool()
        if pool is not None:
            from langgraph.store.postgres import AsyncPostgresStore

            # 注意：必须用构造函数传连接池；from_conn_string 是 @contextmanager，
            # 且 PostgresStore（同步类）不支持 aput/asearch，必须用 AsyncPostgresStore
            try:
                store = AsyncPostgresStore(pool, index=_index_config())
                await store.setup()
                _store = store
                logger.info("长期记忆：AsyncPostgresStore + 语义索引（持久化，重启不丢）")
            except Exception as e:  # noqa: BLE001
                logger.warning("语义索引建立失败（通常是缺 pgvector 扩展），尝试无索引模式：%s", e)
                try:
                    store = AsyncPostgresStore(pool)
                    await store.setup()
                    _store = store
                    logger.warning(
                        "长期记忆：AsyncPostgresStore（持久化，但**无语义索引**）。"
                        "要开启语义检索，请给 Postgres 装 pgvector 并执行 CREATE EXTENSION vector;"
                    )
                except Exception as e2:  # noqa: BLE001
                    logger.warning("AsyncPostgresStore 初始化失败：%s", e2)

        if _store is None:
            # Postgres 不可用 → 回退内存
            _store = InMemoryStore(index=_index_config())
            logger.warning("长期记忆：回退 InMemoryStore（重启将丢失，多进程不共享）")

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
        """列出用户全部记忆。

        注意：列举要用 asearch（不带 query）——aget 是「按 key 取单条」，
        签名是 aget(namespace, key)，没有 limit 参数。
        """
        ns = user_namespace(user_id, tenant_id)
        try:
            items = await self.store.asearch(ns, limit=limit)
            return [{"key": i.key, "content": (i.value or {}).get("content", "")} for i in items]
        except Exception as e:  # noqa: BLE001
            logger.warning("获取全部记忆失败：%s", e)
            return []

    async def delete_memory(self, user_id: str, key: str, *, tenant_id: str = "default") -> None:
        """删除用户的一条记忆。"""
        await self.store.adelete(user_namespace(user_id, tenant_id), key)
        logger.info("长期记忆已删除 user=%s key=%s", user_id, key)


_memory_service: MemoryService | None = None


async def get_memory_service() -> MemoryService:
    """获取 MemoryService 单例。"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService(await get_store())
    return _memory_service
