"""
认证 FastAPI 依赖
-----------------
- get_current_user：从请求头解析 JWT，返回当前用户身份
- 可选认证：auth_enabled=False 时放行（dev 调试用）

用法（保护端点）：
    from app.auth.dependencies import get_current_user, CurrentUser

    @router.post("/chat")
    async def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user)):
        # user.user_id / user.tenant_id 已验证
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from app.auth.jwt_service import AuthError, decode_token, extract_token_from_header
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError


@dataclass
class CurrentUser:
    """当前请求的用户身份（已通过认证）。"""

    user_id: str
    tenant_id: str = "default"
    username: str = ""
    is_authenticated: bool = True
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# dev 模式的默认用户（auth_enabled=False 时使用）
_DEFAULT_USER = CurrentUser(user_id="anonymous", tenant_id="default", username="anonymous", is_authenticated=False)


def _user_from_payload(payload: dict) -> CurrentUser:
    return CurrentUser(
        user_id=payload["sub"],
        tenant_id=payload.get("tenant", "default"),
        username=payload.get("username", ""),
        is_authenticated=True,
        role=payload.get("role", "user"),
    )


async def get_current_user(request: Request) -> CurrentUser:
    """FastAPI 依赖：解析并校验当前用户身份。

    auth_enabled=False（dev）时放行，返回默认用户；
    auth_enabled=True（生产）时必须有有效 Bearer token。
    """
    s = get_settings()
    if not s.auth_enabled:
        return _DEFAULT_USER

    auth_header = request.headers.get("Authorization")
    token = extract_token_from_header(auth_header)
    payload = decode_token(token)
    return _user_from_payload(payload)


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI 依赖：要求管理员身份。

    用于 /evolution、/stats、/metrics 这类管理面接口——它们能改写全局系统
    提示词、查看他人用量、暴露基础设施状态，不该对普通用户开放。

    auth_enabled=False 时放行：此时整个服务本来就是无鉴权的调试形态，
    再在这里拦一道只会造成「dev 下管理接口不可用」的困惑。
    生产环境启动时已强制 AUTH_ENABLED=true（见 app/main.py），不存在绕过。
    """
    if not get_settings().auth_enabled:
        return user
    if not user.is_admin:
        raise ForbiddenError("需要管理员权限")
    return user


async def get_optional_user(request: Request) -> CurrentUser:
    """可选认证：有 token 则解析，无则返回默认用户（用于 /health 等）。"""
    s = get_settings()
    if not s.auth_enabled:
        return _DEFAULT_USER
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return _DEFAULT_USER
    try:
        token = extract_token_from_header(auth_header)
        payload = decode_token(token)
        return CurrentUser(
            user_id=payload["sub"],
            tenant_id=payload.get("tenant", "default"),
            username=payload.get("username", ""),
            is_authenticated=True,
        )
    except AuthError:
        return _DEFAULT_USER


def _enforce_owner_or_anon(user: CurrentUser, resource_user_id: str) -> None:
    """校验资源归属：认证开启时，path 里的 user_id 必须等于 token 的 user_id。

    防 IDOR：认证用户只能访问自己的资源。
    匿名模式（auth 关闭）放行，便于 dev/CLI 调试。
    """
    if not user.is_authenticated:
        return  # 匿名放行
    if user.user_id != resource_user_id:
        raise AuthError("无权访问该用户的数据")


def _enforce_tenant_thread(user: CurrentUser, thread_id: str) -> None:
    """校验会话归属（认证模式下）。具体 thread 归属由 DB 查询的 tenant 过滤保证，
    此处仅做存在性提示。保留扩展点。"""
    # 会话归属由 session_service 的 tenant_id 过滤保证，这里不需重复校验
    pass
