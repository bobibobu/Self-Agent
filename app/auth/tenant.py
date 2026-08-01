"""
多租户隔离工具
--------------
为各数据层提供按租户隔离的命名空间与查询过滤。

隔离策略：
- 长期记忆（store）：namespace 加 tenant 前缀 → ("tenant", tenant_id, "user", user_id)
- 用户画像（Neo4j）：User 节点加 tenant_id 属性，查询带 tenant 过滤
- 会话（conversations）：tenant_id 列过滤
- 对话日志（Mongo）：每条事件带 tenant_id

设计原则：tenant_id 从认证 token 获取（已验证），不可被客户端伪造。
"""

from __future__ import annotations

DEFAULT_TENANT = "default"


def allowed_tenants() -> set[str]:
    """配置里允许的租户集合。始终包含 default。"""
    from app.core.config import get_settings

    raw = get_settings().tenant_allowlist or ""
    tenants = {t.strip() for t in raw.split(",") if t.strip()}
    tenants.add(DEFAULT_TENANT)
    return tenants


def resolve_tenant(request) -> str:
    """从请求解析租户 ID —— **服务端说了算，不接受请求体自由指定**。

    原来 /auth/register 的 tenant_id 是从请求体读的，等于任何人都能
    自助注册进任意租户，多租户隔离形同虚设。现在改为：

    - 未启用多租户            → 恒为 default
    - 启用多租户              → 从配置的请求头读，且必须命中 allowlist，否则拒绝

    生产建议由网关按域名/证书注入该头，并禁止外部直接传入。
    """
    from app.auth.jwt_service import AuthError
    from app.core.config import get_settings

    s = get_settings()
    if not s.multi_tenant_enabled:
        return DEFAULT_TENANT

    claimed = (request.headers.get(s.tenant_header) or DEFAULT_TENANT).strip()
    if claimed not in allowed_tenants():
        raise AuthError(f"未知或不被允许的租户：{claimed}")
    return claimed


def memory_namespace(tenant_id: str, user_id: str) -> tuple[str, ...]:
    """构造租户隔离的记忆命名空间。

    不同租户的同名 user_id 记忆完全隔离。
    multi_tenant_enabled=False 时退化为不隔离（兼容旧行为）。
    """
    from app.core.config import get_settings

    if get_settings().multi_tenant_enabled:
        return ("tenant", tenant_id, "user", user_id)
    return ("user", user_id)


def scoped_user_id(tenant_id: str, user_id: str) -> str:
    """构造带租户前缀的 user_id（用于 Neo4j 等需扁平 ID 的场景）。

    multi_tenant_enabled=False 时返回原值。
    """
    from app.core.config import get_settings

    if get_settings().multi_tenant_enabled:
        return f"{tenant_id}:{user_id}"
    return user_id


def scoped_thread_id(tenant_id: str, thread_id: str) -> str:
    """构造带租户前缀的 thread_id（防跨租户 thread 冲突）。"""
    from app.core.config import get_settings

    if get_settings().multi_tenant_enabled:
        return f"{tenant_id}:{thread_id}"
    return thread_id
