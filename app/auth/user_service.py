"""
用户存储服务
-----------
操作 users 表：注册、查询、密码校验。
含多租户支持（tenant_id 字段）。

需先执行 infra/postgres/init.sql 扩展（加 tenant_id + password_hash 列）。
"""

from __future__ import annotations

from typing import Any, Optional

from app.auth.jwt_service import hash_password, verify_password
from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)

# 防 timing attack 的填充哈希：用户不存在时也跑一次 bcrypt，使两条路径耗时一致
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


class UserService:
    """用户管理。"""

    async def register(
        self, *, username: str, password: str, tenant_id: str = "default", email: str | None = None,
    ) -> dict[str, Any] | None:
        """注册用户。返回用户信息（不含密码哈希），用户名冲突返回 None。"""
        from asyncpg.exceptions import UniqueViolationError

        pool = db_manager.postgres
        if pool is None:
            raise RuntimeError("PostgreSQL 不可用，无法注册用户")
        pwd_hash = hash_password(password)
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO users (username, email, password_hash, tenant_id) "
                    "VALUES ($1, $2, $3, $4) RETURNING id, username, email, tenant_id, created_at",
                    username, email, pwd_hash, tenant_id,
                )
            logger.info("用户注册成功 username=%s tenant=%s", username, tenant_id)
            return self._row_to_dict(row)
        except UniqueViolationError:
            # 唯一约束冲突（用户名已存在）——用类型化异常而非字符串匹配
            logger.info("注册失败：用户名已存在 %s", username)
            return None

    async def authenticate(self, username: str, password: str, tenant_id: str = "default") -> dict[str, Any] | None:
        """校验用户名密码。成功返回用户信息，失败返回 None。

        防 timing attack：用户不存在时也执行一次 bcrypt（dummy hash），
        使"用户不存在"和"密码错误"两条路径耗时一致，防止用户名枚举。
        """
        pool = db_manager.postgres
        if pool is None:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, email, tenant_id, password_hash FROM users "
                    "WHERE username = $1 AND tenant_id = $2",
                    username, tenant_id,
                )
            if row is None:
                # 用户不存在：跑一次 dummy bcrypt 平衡耗时，防 timing attack
                verify_password(password, _DUMMY_HASH)
                return None
            if not verify_password(password, row["password_hash"]):
                return None
            return self._row_to_dict(row)
        except Exception as e:  # noqa: BLE001
            logger.warning("认证查询失败：%s", e)
            return None

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """按 ID 查用户。"""
        pool = db_manager.postgres
        if pool is None:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, email, tenant_id FROM users WHERE id = $1",
                    user_id,
                )
            return self._row_to_dict(row) if row else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        d = dict(row)
        d.pop("password_hash", None)  # 绝不返回密码哈希
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        return d


_user_service: Optional[UserService] = None


def get_user_service() -> UserService:
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
