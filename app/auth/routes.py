"""
认证路由
--------
- POST /auth/register  注册
- POST /auth/login     登录（返回 JWT）
- GET  /auth/me        当前用户信息

登录返回的 token 放在 Authorization: Bearer <token> 头里访问受保护端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.jwt_service import AuthError, create_token
from app.auth.tenant import resolve_tenant
from app.auth.user_service import get_user_service
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


# 注意：凭据只走请求体，不接受 query 参数——query string 会被
# nginx / uvicorn 的访问日志原样记录，密码会明文落盘。
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    email: str | None = Field(None, max_length=128)
    # 这里**故意不提供 tenant_id**：租户由服务端 resolve_tenant 决定。


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/auth/register", response_model=AuthResponse, tags=["认证"])
async def register(req: RegisterRequest, request: Request) -> AuthResponse:
    """注册新用户，直接返回 token（免去再登录一步）。"""
    tenant_id = resolve_tenant(request)
    user = await get_user_service().register(
        username=req.username, password=req.password, tenant_id=tenant_id, email=req.email,
    )
    if user is None:
        raise AuthError("用户名已存在")
    token = create_token(
        user_id=user["id"], tenant_id=user.get("tenant_id", tenant_id), username=req.username,
    )
    return AuthResponse(access_token=token, user=user)


@router.post("/auth/login", response_model=AuthResponse, tags=["认证"])
async def login(req: LoginRequest, request: Request) -> AuthResponse:
    """登录，返回 JWT。"""
    tenant_id = resolve_tenant(request)
    user = await get_user_service().authenticate(req.username, req.password, tenant_id)
    if user is None:
        raise AuthError("用户名或密码错误")
    token = create_token(
        user_id=user["id"], tenant_id=user.get("tenant_id", tenant_id), username=req.username,
    )
    return AuthResponse(access_token=token, user=user)


@router.get("/auth/me", tags=["认证"])
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """获取当前登录用户信息。"""
    return {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "username": user.username,
        "is_authenticated": user.is_authenticated,
        "role": user.role,
    }
