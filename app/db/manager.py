"""
数据库连接管理器
----------------
统一持有 PostgreSQL / MongoDB / Redis / Neo4j 的异步客户端，
随应用生命周期启停。

为什么独立一个 manager？
- 单一职责：连接生命周期与业务逻辑分离
- 单例复用：全应用共享连接池，避免反复建连
- 优雅降级：开发期某个服务没起，不阻断整体启动
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 仅类型检查时导入，运行时按需导入避免强依赖
if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from pymongo import AsyncMongoClient
    from pymongo.database import Database as MongoDatabase
    from redis import asyncio as aioredis
    import asyncpg


class DBManager:
    """数据库连接单例。通过 `db_manager` 模块级实例使用。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        # 各客户端懒加载
        self._postgres: Optional["asyncpg.Pool"] = None
        self._mongo_client: Optional["AsyncMongoClient"] = None
        self._mongo_db: Optional["MongoDatabase"] = None
        self._redis: Optional["aioredis.Redis"] = None
        self._neo4j: Optional["AsyncDriver"] = None

    # ---------- 生命周期 ----------
    async def connect(self) -> None:
        """启动时连接所有数据库。单个失败不影响其他。"""
        await self._try("PostgreSQL", self._connect_postgres)
        await self._try("MongoDB", self._connect_mongo)
        await self._try("Redis", self._connect_redis)
        await self._try("Neo4j", self._connect_neo4j)

    async def disconnect(self) -> None:
        """关闭时释放所有连接。每个连接独立 try/except，保证全部尝试关闭。"""
        for name, action in [
            ("PostgreSQL", self._close_postgres),
            ("MongoDB", self._close_mongo),
            ("Redis", self._close_redis),
            ("Neo4j", self._close_neo4j),
        ]:
            try:
                await action()
            except Exception as e:  # noqa: BLE001
                logger.warning("%s 关闭失败（不影响其他）：%s", name, e)

    async def _close_postgres(self) -> None:
        if self._postgres:
            await self._postgres.close()
            self._postgres = None
            logger.info("PostgreSQL 连接已关闭")

    async def _close_mongo(self) -> None:
        if self._mongo_client:
            await self._mongo_client.close()
            self._mongo_client = None
            self._mongo_db = None
            logger.info("MongoDB 连接已关闭")

    async def _close_redis(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None
            logger.info("Redis 连接已关闭")

    async def _close_neo4j(self) -> None:
        if self._neo4j:
            await self._neo4j.close()
            self._neo4j = None
            logger.info("Neo4j 连接已关闭")

    async def _try(self, name: str, coro_fn) -> None:
        try:
            await coro_fn()
        except Exception as e:  # noqa: BLE001
            # 开发期常见：某个容器没起。只告警不崩。
            logger.warning("%s 连接失败（不阻断启动）：%s", name, e)

    # ---------- PostgreSQL ----------
    async def _connect_postgres(self) -> None:
        import asyncpg

        pool = await asyncpg.create_pool(
            dsn=self.settings.postgres_dsn_asyncpg,
            min_size=2,
            max_size=10,
            timeout=5,            # 建连超时（秒），开发期 DB 没起时快速失败
            command_timeout=10,
        )
        # 先验证连通性，通过后才赋值，避免留下不可用的池
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        self._postgres = pool
        logger.info("PostgreSQL 已连接: %s:%s", self.settings.postgres_host, self.settings.postgres_port)

    @property
    def postgres(self) -> "Optional[asyncpg.Pool]":
        return self._postgres

    # ---------- MongoDB ----------
    async def _connect_mongo(self) -> None:
        from pymongo import AsyncMongoClient

        # serverSelectionTimeoutMS：找不到服务端时的超时（开发期 DB 没起时快速失败）
        self._mongo_client = AsyncMongoClient(
            self.settings.mongo_uri,
            serverSelectionTimeoutMS=3000,
        )
        self._mongo_db = self._mongo_client[self.settings.mongo_db]
        # 触发实际连接 + 鉴权校验
        await self._mongo_db.command("ping")
        logger.info("MongoDB 已连接: %s:%s", self.settings.mongo_host, self.settings.mongo_port)

    @property
    def mongo(self) -> "Optional[MongoDatabase]":
        return self._mongo_db

    # ---------- Redis ----------
    async def _connect_redis(self) -> None:
        from redis import asyncio as aioredis

        self._redis = aioredis.from_url(
            self.settings.redis_url, decode_responses=True, socket_connect_timeout=3
        )
        await self._redis.ping()
        logger.info("Redis 已连接: %s:%s", self.settings.redis_host, self.settings.redis_port)

    @property
    def redis(self) -> "Optional[aioredis.Redis]":
        return self._redis

    # ---------- Neo4j ----------
    async def _connect_neo4j(self) -> None:
        from neo4j import AsyncGraphDatabase

        self._neo4j = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            connection_timeout=3,    # 建连超时（秒）
        )
        await self._neo4j.verify_connectivity()
        logger.info("Neo4j 已连接: %s", self.settings.neo4j_uri)

    @property
    def neo4j(self) -> "Optional[AsyncDriver]":
        return self._neo4j


# 模块级单例
db_manager = DBManager()
