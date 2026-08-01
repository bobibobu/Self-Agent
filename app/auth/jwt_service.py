"""
密码哈希与 JWT 服务
-------------------
- 密码：bcrypt 哈希（直接用 bcrypt 库，不依赖已停维的 passlib）
- Token：JWT 签发/校验（PyJWT）
- 用户/租户身份封装在 token 的 claims 里
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

# bcrypt 限制：密码最长 72 字节
_BCRYPT_MAX_BYTES = 72


class AuthError(AppError):
    """认证相关错误。"""

    def __init__(self, message: str):
        super().__init__(message, code="AUTH_ERROR", status_code=401)


# ---------- 密码 ----------


def hash_password(password: str) -> str:
    """密码哈希（bcrypt）。超 72 字节自动截断（bcrypt 限制）。"""
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。"""
    try:
        pwd_bytes = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------


def is_admin_username(username: str) -> bool:
    """用户名是否在 ADMIN_USERNAMES 名单里。"""
    raw = get_settings().admin_usernames or ""
    return username in {u.strip() for u in raw.split(",") if u.strip()}


def create_token(*, user_id: str, tenant_id: str = "default", username: str = "") -> str:
    """签发 JWT。claims 含 user_id / tenant_id / username / role / 过期时间。"""
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,          # subject = user_id
        "tenant": tenant_id,     # 租户
        "username": username,
        "role": "admin" if is_admin_username(username) else "user",
        "exp": now + timedelta(hours=s.jwt_expire_hours),
        "iat": now,
        # jti：给后续做 token 吊销名单留的锚点（当前未实现吊销，见 README 已知限制）
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    logger.info("签发 token user=%s tenant=%s role=%s", user_id, tenant_id, payload["role"])
    return token


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT。无效则抛 AuthError。"""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token 已过期") from e
    except jwt.InvalidTokenError as e:
        raise AuthError("无效的 Token") from e

    if "sub" not in payload:
        raise AuthError("Token 缺少用户信息")
    return payload


def extract_token_from_header(authorization: str | None) -> str:
    """从 Authorization: Bearer <token> 头提取 token。"""
    if not authorization:
        raise AuthError("缺少认证信息")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("认证格式错误，应为 Bearer <token>")
    return parts[1]
