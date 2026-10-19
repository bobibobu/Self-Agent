"""
用户存储服务
-----------
操作 users 表：注册、查询、密码校验。
含多租户支持（tenant_id 字段）。

需先执行 infra/postgres/init.sql 扩展（加 tenant_id + password_hash 列）。
"""

from __future__ import annotations

from typing import Any

from app.auth.jwt_service import hash_password, verify_password
from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)

# 防 timing attack 的填充哈希：用户不存在时也跑一次 bcrypt，使两条路径耗时一致
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


class UserService:
    """用户管理。

    走 db_manager.postgres（psycopg 共享连接池，autocommit + dict_row）：
    占位符是 %s，行是 dict。
    """

    async def register(
        self, *, username: str, password: str, tenant_id: str = "default", email: str | None = None,
    ) -> dict[str, Any] | None:
        """注册用户。返回用户信息（不含密码哈希），用户名冲突返回 None。"""
        from psycopg.errors import UniqueViolation

        # 明文密码与哈希都不进日志
        logger.info("[users] register 入参 username=%s tenant=%s email=%s", username, tenant_id, email)
        pool = db_manager.postgres
        if pool is None:
            raise RuntimeError("PostgreSQL 不可用，无法注册用户")
        pwd_hash = hash_password(password)
        try:
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO users (username, email, password_hash, tenant_id) "
                    "VALUES (%s, %s, %s, %s) RETURNING id, username, email, tenant_id, created_at",
                    (username, email, pwd_hash, tenant_id),
                )
                row = await cur.fetchone()
            result = self._row_to_dict(row)
            logger.info("用户注册成功 username=%s tenant=%s 返回=%s", username, tenant_id, result)
            return result
        except UniqueViolation:
            # 唯一约束冲突（用户名已存在）——用类型化异常而非字符串匹配
            logger.info("注册失败：用户名已存在 %s", username)
            return None

    async def authenticate(self, username: str, password: str, tenant_id: str = "default") -> dict[str, Any] | None:
        """校验用户名密码。成功返回用户信息，失败返回 None。

        防 timing attack：用户不存在时也执行一次 bcrypt（dummy hash），
        使"用户不存在"和"密码错误"两条路径耗时一致，防止用户名枚举。
        """
        logger.info("[users] authenticate 入参 username=%s tenant=%s", username, tenant_id)
        pool = db_manager.postgres
        if pool is None:
            logger.warning("[users] authenticate 跳过：PostgreSQL 不可用")
            return None
        try:
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, username, email, tenant_id, password_hash FROM users "
                    "WHERE username = %s AND tenant_id = %s",
                    (username, tenant_id),
                )
                row = await cur.fetchone()
            if row is None:
                # 用户不存在：跑一次 dummy bcrypt 平衡耗时，防 timing attack
                verify_password(password, _DUMMY_HASH)
                logger.info("[users] authenticate 返回 None：用户不存在 username=%s tenant=%s", username, tenant_id)
                return None
            if not verify_password(password, row["password_hash"]):
                logger.info("[users] authenticate 返回 None：密码错误 username=%s tenant=%s", username, tenant_id)
                return None
            result = self._row_to_dict(row)
            logger.info("[users] authenticate 成功 返回=%s", result)
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("认证查询失败：%s", e)
            return None

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """按 ID 查用户。"""
        logger.info("[users] get_by_id 入参 user_id=%s", user_id)
        pool = db_manager.postgres
        if pool is None:
            logger.warning("[users] get_by_id 跳过：PostgreSQL 不可用")
            return None
        try:
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, username, email, tenant_id FROM users WHERE id = %s",
                    (user_id,),
                )
                row = await cur.fetchone()
            result = self._row_to_dict(row) if row else None
            logger.info("[users] get_by_id 返回=%s", result)
            return result
        except Exception as e:  # noqa: BLE001
            # 非法 UUID 字符串也会落到这里（InvalidTextRepresentation）
            logger.warning("[users] get_by_id 查询失败 user_id=%s：%s", user_id, e)
            return None

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        d = dict(row)
        d.pop("password_hash", None)  # 绝不返回密码哈希
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        return d


_user_service: UserService | None = None


def get_user_service() -> UserService:
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
