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

from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 仅类型检查时导入，运行时按需导入避免强依赖
if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from psycopg_pool import AsyncConnectionPool
    from pymongo import AsyncMongoClient
    from pymongo.database import Database as MongoDatabase
    from redis import asyncio as aioredis


class DBManager:
    """数据库连接单例。通过 `db_manager` 模块级实例使用。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        # 各客户端懒加载
        self._postgres: AsyncConnectionPool | None = None
        self._mongo_client: AsyncMongoClient | None = None
        self._mongo_db: MongoDatabase | None = None
        self._redis: aioredis.Redis | None = None
        self._neo4j: AsyncDriver | None = None

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
        # 池的生命周期归 app.memory.pg 管；close_pg_pool 幂等，
        # main.py 里先关过一次的话这里是空操作
        if self._postgres:
            from app.memory.pg import close_pg_pool

            self._postgres = None
            await close_pg_pool()
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
        # 业务表（users / conversations）与 LangGraph checkpointer/store 共用
        # app/memory/pg.py 的 psycopg 连接池：一个驱动、一个池、一份 DSN。
        # 以前这里另开了一个 asyncpg 池，进程里同时挂两套 Postgres 驱动、两倍连接数。
        # 池子在 open(wait=True) 时已经验证过连通性，拿到非 None 就是可用的。
        from app.memory.pg import get_pg_pool

        logger.info("PostgreSQL 连接中: %s:%s", self.settings.postgres_host, self.settings.postgres_port)
        pool = await get_pg_pool()
        if pool is None:
            raise RuntimeError("共享 Postgres 连接池不可用（原因见 app.memory.pg 的告警）")
        self._postgres = pool
        logger.info("PostgreSQL 已连接（与 LangGraph 共用 psycopg 连接池）: %s:%s",
                    self.settings.postgres_host, self.settings.postgres_port)

    @property
    def postgres(self) -> AsyncConnectionPool | None:
        return self._postgres

    # ---------- MongoDB ----------
    async def _connect_mongo(self) -> None:
        from pymongo import AsyncMongoClient

        # serverSelectionTimeoutMS：找不到服务端时的超时（开发期 DB 没起时快速失败）
        client = AsyncMongoClient(
            self.settings.mongo_uri,
            serverSelectionTimeoutMS=3000,
        )
        db = client[self.settings.mongo_db]
        # 先验证连通性与鉴权，通过后才赋值——
        # 否则连接失败时 self._mongo_db 已经是个半初始化对象，
        # 而全项目都用 `db_manager.mongo is not None` 当「Mongo 可用」的判据，
        # 判断就废了：每次写日志都要抛异常再被 except 吞掉，而不是廉价地短路。
        await db.command("ping")
        self._mongo_client = client
        self._mongo_db = db
        logger.info("MongoDB 已连接: %s:%s", self.settings.mongo_host, self.settings.mongo_port)

    @property
    def mongo(self) -> MongoDatabase | None:
        return self._mongo_db

    # ---------- Redis ----------
    async def _connect_redis(self) -> None:
        from redis import asyncio as aioredis

        # 同 Mongo：验证通过后才赋值，保证 `db_manager.redis is not None` 等价于「可用」
        client = aioredis.from_url(
            self.settings.redis_url, decode_responses=True, socket_connect_timeout=3
        )
        await client.ping()
        self._redis = client
        logger.info("Redis 已连接: %s:%s", self.settings.redis_host, self.settings.redis_port)

    @property
    def redis(self) -> aioredis.Redis | None:
        return self._redis

    # ---------- Neo4j ----------
    async def _connect_neo4j(self) -> None:
        from neo4j import AsyncGraphDatabase

        # 同 Mongo/Redis：验证通过后才赋值
        driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            connection_timeout=3,    # 建连超时（秒）
        )
        await driver.verify_connectivity()
        self._neo4j = driver
        logger.info("Neo4j 已连接: %s", self.settings.neo4j_uri)

    @property
    def neo4j(self) -> AsyncDriver | None:
        return self._neo4j


# 模块级单例
db_manager = DBManager()
