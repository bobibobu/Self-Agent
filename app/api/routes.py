"""
API 路由
--------
- GET  /health       健康检查
- POST /chat         一次性对话（阻塞返回完整回复）
- POST /chat/stream  流式对话（SSE 逐 token 返回）

所有对话通过 LangGraph 编排，短期记忆（checkpointer）按 thread_id 持久化。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app import __version__
from app.agent.graph import run_agent, stream_agent
from app.api.schemas import (
    AddInterestRequest,
    AddMemoryRequest,
    AddPreferenceRequest,
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from app.auth.dependencies import CurrentUser, get_current_user, require_admin
from app.core.config import get_settings
from app.core.exceptions import AgentError, NotFoundError
from app.core.logging import get_logger, new_trace_id
from app.llm.factory import get_llm_client

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["系统"])
async def health() -> HealthResponse:
    """健康检查。"""
    s = get_settings()
    return HealthResponse(
        app=s.app_name,
        version=__version__,
        default_provider=s.llm_default_provider,
    )


@router.get("/tools", tags=["能力"])
async def list_tools():
    """列出 Agent 当前可用的全部工具（内置 + MCP + Skill）。"""
    from app.agent.registry import get_all_tools

    tools = []
    for t in get_all_tools():
        tools.append({
            "name": t.name,
            "description": (t.description or "")[:200],
        })
    return {"count": len(tools), "tools": tools}


@router.get("/skills", tags=["能力"])
async def list_skills():
    """列出所有已注册的 Skill。"""
    from app.skills.registry import skill_registry

    skills = skill_registry.list_skills()
    return {"count": len(skills), "loaded": skill_registry.loaded_names, "skills": skills}


@router.post("/chat", response_model=ChatResponse, tags=["对话"])
async def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user)) -> ChatResponse:
    """一次性对话：阻塞直到 Agent 给出完整回复（可能经过多轮工具调用）。

    身份从认证 token 获取（认证关闭时回退请求体 user_id）。
    自动注入该用户的长期记忆、画像（按租户隔离）到上下文。
    """
    new_trace_id()
    # 认证开启时用 token 身份；关闭时回退请求体（兼容匿名/CLI）
    uid = user.user_id if user.is_authenticated else req.user_id
    tenant = user.tenant_id
    logger.info("chat 请求 thread=%s user=%s tenant=%s", req.thread_id, uid, tenant)

    try:
        result = await run_agent(req.message, req.thread_id, user_id=uid, kb_ids=req.kb_ids, tenant_id=tenant)
    except Exception as e:
        logger.exception("Agent 执行失败")
        from app.core.config import get_settings
        msg = f"Agent 执行失败: {e}" if get_settings().is_dev else "Agent 处理失败，请稍后重试"
        raise AgentError(msg) from e

    return ChatResponse(
        reply=result["reply"],
        thread_id=result["thread_id"],
        provider=get_llm_client().provider_name,
    )


@router.post("/chat/stream", tags=["对话"])
async def chat_stream(req: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    """流式对话（SSE 传输）：真·token 级流式 + 工具调用中间步骤。

    身份从认证 token 获取。适合 Web 前端（浏览器 EventSource 原生支持）。
    """
    new_trace_id()
    uid = user.user_id if user.is_authenticated else req.user_id
    tenant = user.tenant_id
    logger.info("chat/stream (SSE) 请求 thread=%s user=%s", req.thread_id, uid)

    async def event_generator():
        async for event in stream_agent(req.message, req.thread_id, user_id=uid, kb_ids=req.kb_ids, tenant_id=tenant):
            etype = event.get("type", "message")
            yield {
                "event": etype,
                "data": json.dumps(event, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.post("/chat/http-stream", tags=["对话"])
async def chat_http_stream(req: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    """流式对话（Streamable HTTP / NDJSON 传输）：真·token 级流式。

    身份从认证 token 获取。适合 CLI / 非浏览器客户端。
    """
    new_trace_id()
    uid = user.user_id if user.is_authenticated else req.user_id
    tenant = user.tenant_id
    logger.info("chat/http-stream (NDJSON) 请求 thread=%s user=%s", req.thread_id, uid)

    async def ndjson_generator():
        async for event in stream_agent(req.message, req.thread_id, user_id=uid, kb_ids=req.kb_ids, tenant_id=tenant):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        ndjson_generator(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ==================== 长期记忆 ====================


@router.post("/memory", tags=["记忆"])
async def add_memory(req: AddMemoryRequest, user: CurrentUser = Depends(get_current_user)):
    """为当前用户添加一条长期记忆（身份从 token，按租户隔离）。"""
    from app.memory.store import get_memory_service

    uid = user.user_id if user.is_authenticated else req.user_id
    mem_service = await get_memory_service()
    key = await mem_service.add_memory(uid, req.content, key=req.key, tenant_id=user.tenant_id)
    return {"status": "ok", "key": key}


@router.get("/memory/{user_id}", tags=["记忆"])
async def search_memory(user_id: str, query: str, limit: int = 5, user: CurrentUser = Depends(get_current_user)):
    """语义检索用户的长期记忆（认证开启时校验 user_id 归属）。"""
    from app.auth.dependencies import _enforce_owner_or_anon
    from app.memory.store import get_memory_service

    _enforce_owner_or_anon(user, user_id)
    mem_service = await get_memory_service()
    results = await mem_service.search_memory(user_id, query, limit=limit, tenant_id=user.tenant_id)
    return {"count": len(results), "memories": results}


@router.get("/memory/{user_id}/all", tags=["记忆"])
async def list_memories(user_id: str, limit: int = 50, user: CurrentUser = Depends(get_current_user)):
    """列出用户全部长期记忆（认证开启时校验归属）。"""
    from app.auth.dependencies import _enforce_owner_or_anon
    from app.memory.store import get_memory_service

    _enforce_owner_or_anon(user, user_id)
    mem_service = await get_memory_service()
    results = await mem_service.get_all_memories(user_id, limit=limit, tenant_id=user.tenant_id)
    return {"count": len(results), "memories": results}


@router.delete("/memory/{user_id}/{key}", tags=["记忆"])
async def delete_memory(user_id: str, key: str, user: CurrentUser = Depends(get_current_user)):
    """删除用户的一条长期记忆（认证开启时校验归属）。"""
    from app.auth.dependencies import _enforce_owner_or_anon
    from app.memory.store import get_memory_service

    _enforce_owner_or_anon(user, user_id)
    mem_service = await get_memory_service()
    await mem_service.delete_memory(user_id, key, tenant_id=user.tenant_id)
    return {"status": "ok"}


# ==================== 用户画像 ====================


@router.post("/profile/interest", tags=["用户画像"])
async def add_interest(req: AddInterestRequest, user: CurrentUser = Depends(get_current_user)):
    """记录用户兴趣（按租户作用域）。"""
    from app.auth.tenant import scoped_user_id
    from app.profile.service import get_profile_service

    uid = scoped_user_id(user.tenant_id, req.user_id if not user.is_authenticated else user.user_id)
    await get_profile_service().add_interest(uid, req.interest)
    return {"status": "ok"}


@router.post("/profile/preference", tags=["用户画像"])
async def add_preference(req: AddPreferenceRequest, user: CurrentUser = Depends(get_current_user)):
    """记录用户偏好（按租户作用域）。"""
    from app.auth.tenant import scoped_user_id
    from app.profile.service import get_profile_service

    uid = scoped_user_id(user.tenant_id, req.user_id if not user.is_authenticated else user.user_id)
    await get_profile_service().add_preference(uid, req.key, req.value)
    return {"status": "ok"}


@router.get("/profile/{user_id}", tags=["用户画像"])
async def get_profile(user_id: str, user: CurrentUser = Depends(get_current_user)):
    """获取用户完整画像（按租户作用域）。"""
    from app.auth.dependencies import _enforce_owner_or_anon
    from app.auth.tenant import scoped_user_id
    from app.profile.service import get_profile_service

    _enforce_owner_or_anon(user, user_id)
    uid = scoped_user_id(user.tenant_id, user_id)
    profile = await get_profile_service().get_profile(uid)
    return profile


# ==================== 对话历史 ====================


@router.get("/history/{thread_id}", tags=["对话"])
async def get_history(thread_id: str, limit: int = 20, user: CurrentUser = Depends(get_current_user)):
    """查询某会话的对话历史（从 MongoDB，按租户隔离）。"""
    from app.auth.tenant import scoped_thread_id
    from app.logging_service import get_conversation_logger

    scoped_tid = scoped_thread_id(user.tenant_id, thread_id)
    events = await get_conversation_logger().get_history(scoped_tid, limit=limit)
    return {"count": len(events), "events": events}


@router.post("/chat/cancel/{thread_id}", tags=["对话"])
async def cancel_chat(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    """取消正在进行的流式生成（需认证，且只能取消自己的会话）。"""
    from app.agent.cancel_registry import request_cancel
    from app.services.session_service import get_session_service

    # 归属校验：否则任何人猜到 thread_id 就能打断别人的生成
    if user.is_authenticated:
        owned = await get_session_service().get_session(
            thread_id, tenant_id=user.tenant_id, user_id=user.user_id,
        )
        if owned is None:
            raise NotFoundError("会话不存在")

    found = await request_cancel(thread_id)
    return {"status": "cancelled" if found else "not_found", "thread_id": thread_id}


# ==================== 会话管理 ====================


# 会话归属：认证开启时锁定到 token 里的 user_id（防同租户下互删会话的 IDOR）；
# 匿名模式下 owner 为 None，退化为「按租户共享」的调试形态。
def _session_owner(user: CurrentUser) -> str | None:
    return user.user_id if user.is_authenticated else None


@router.get("/sessions", tags=["会话"])
async def list_sessions(
    user_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
):
    """列出会话（按租户隔离；认证后只列自己的）。"""
    from app.services.session_service import get_session_service

    uid = user.user_id if user.is_authenticated else user_id
    sessions = await get_session_service().list_sessions(uid, limit=limit, tenant_id=user.tenant_id)
    return {"count": len(sessions), "sessions": sessions}


@router.post("/sessions", tags=["会话"])
async def create_session(
    user_id: str | None = None,
    title: str = Query("新对话", max_length=256),
    user: CurrentUser = Depends(get_current_user),
):
    """新建会话，返回 thread_id（按租户）。"""
    from app.services.session_service import get_session_service

    uid = user.user_id if user.is_authenticated else user_id
    session = await get_session_service().create_session(user_id=uid, title=title, tenant_id=user.tenant_id)
    return session


@router.get("/sessions/{thread_id}", tags=["会话"])
async def get_session(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    """获取单个会话信息（按租户 + 归属人校验）。"""
    from app.services.session_service import get_session_service

    session = await get_session_service().get_session(
        thread_id, tenant_id=user.tenant_id, user_id=_session_owner(user),
    )
    if session is None:
        raise NotFoundError("会话不存在")
    return session


@router.patch("/sessions/{thread_id}", tags=["会话"])
async def rename_session(
    thread_id: str,
    title: str = Query(..., max_length=256),
    user: CurrentUser = Depends(get_current_user),
):
    """重命名会话（按租户 + 归属人校验）。"""
    from app.services.session_service import get_session_service

    ok = await get_session_service().rename_session(
        thread_id, title, tenant_id=user.tenant_id, user_id=_session_owner(user),
    )
    if not ok:
        raise NotFoundError("会话不存在")
    return {"status": "ok"}


@router.delete("/sessions/{thread_id}", tags=["会话"])
async def delete_session(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    """删除会话（按租户 + 归属人校验，含清理状态）。"""
    from app.services.session_service import get_session_service

    ok = await get_session_service().delete_session(
        thread_id, tenant_id=user.tenant_id, user_id=_session_owner(user),
    )
    if not ok:
        raise NotFoundError("会话不存在")
    return {"status": "ok"}


# ==================== Hermes 自我进化 ====================


# 以下 /evolution/* 全部是管理面接口：它们能改写**全局**系统提示词
# （影响所有用户的所有会话），必须限管理员。


@router.post("/evolution/reflect", tags=["Hermes 进化"])
async def evolution_reflect(
    sample_limit: int = Query(5, ge=1, le=50),
    auto_apply_threshold: float = Query(6.0, ge=0.0, le=10.0),
    _: CurrentUser = Depends(require_admin),
):
    """手动触发 Hermes 反思循环：回顾近期对话 → 自评 → 优化提示词。

    能力 B（主动进化）。评估达标（>= auto_apply_threshold）则自动采纳为新版本。
    """
    from app.core.config import get_settings

    if not get_settings().hermes_reflection_enabled:
        return {"status": "disabled", "message": "Hermes 反思已在配置中禁用"}

    from app.evolution.reflector import reflect
    result = await reflect(sample_limit=sample_limit, auto_apply_threshold=auto_apply_threshold)
    return result


@router.get("/evolution/prompt", tags=["Hermes 进化"])
async def evolution_get_prompt(_: CurrentUser = Depends(require_admin)):
    """查看当前生效的系统提示词及其版本。"""
    from app.evolution.prompt_store import get_current_prompt, get_current_version

    return {
        "version": get_current_version(),
        "content": get_current_prompt(),
    }


@router.get("/evolution/versions", tags=["Hermes 进化"])
async def evolution_list_versions(
    limit: int = Query(20, ge=1, le=200), _: CurrentUser = Depends(require_admin),
):
    """列出提示词的历史版本。"""
    from app.evolution.prompt_store import list_versions

    versions = list_versions(limit=limit)
    return {"count": len(versions), "versions": versions}


@router.post("/evolution/rollback/{version}", tags=["Hermes 进化"])
async def evolution_rollback(version: str, _: CurrentUser = Depends(require_admin)):
    """回滚到指定提示词版本。"""
    from app.evolution.prompt_store import rollback

    ok = rollback(version)
    return {"status": "ok" if ok else "not_found", "version": version}


# ==================== 用量统计 & 可观测 ====================


@router.get("/stats/usage", tags=["统计"])
async def usage_stats(
    user_id: str | None = None,
    days: int = Query(7, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
):
    """获取 token 用量与成本统计。

    普通用户只能看自己的；管理员可以指定 user_id 或看全租户汇总。
    """
    from app.services.stats_service import get_stats_service

    if not user.is_admin and user.is_authenticated:
        # 非管理员：强制锁定到自己，忽略请求里传的 user_id
        user_id = user.user_id
    return await get_stats_service().get_usage_stats(
        user_id=user_id, days=days, tenant_id=user.tenant_id,
    )


@router.get("/metrics", tags=["系统"])
async def metrics(_: CurrentUser = Depends(require_admin)):
    """运行时指标（请求数、延迟、基础设施状态）。仅管理员。"""
    from app.services.observability import get_metrics

    return get_metrics()
