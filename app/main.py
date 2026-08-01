"""
Self-Agent 应用入口
====================
FastAPI 应用，整合：
- 数据库连接（启动连，关闭断）
- API 路由（/health, /chat, /chat/stream）
- 全局异常处理
- 结构化日志

启动：
    uv run uvicorn app.main:app --reload
    或：python -m uvicorn app.main:app --reload

访问交互式文档：http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.upload_routes import router as upload_router
from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db.manager import db_manager
from app.mcp.client import mcp_client_manager
from app.rag.routes import router as rag_router

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时连接数据库与 MCP，关闭时断开。"""
    logger.info("🚀 %s 启动中 (env=%s, provider=%s)", settings.app_name, settings.app_env, settings.llm_default_provider)
    # 生产环境安全检查：必须开认证、必须改默认 JWT 密钥
    if settings.app_env == "prod":
        if not settings.auth_enabled:
            logger.error("⚠️ 生产环境 AUTH_ENABLED 必须为 true！拒绝以不安全模式启动")
            raise RuntimeError("生产环境必须启用认证 (AUTH_ENABLED=true)")
        if settings.jwt_secret == "self-agent-dev-secret-change-in-production":
            logger.error("⚠️ 生产环境必须修改默认 JWT_SECRET！")
            raise RuntimeError("生产环境必须设置自定义 JWT_SECRET")
    await db_manager.connect()
    # 连接外部 MCP server 并发现工具（失败不阻断）
    await mcp_client_manager.connect()
    # 把 MCP 工具合并进 Agent 工具注册表
    if mcp_client_manager.tools:
        from app.agent.registry import refresh_from_mcp
        n = refresh_from_mcp(mcp_client_manager.tools)
        logger.info("✅ Agent 工具注册表已刷新（新增 %d 个 MCP 工具）", n)
    # 加载 Skill（把 Skill 的工具注入注册表，提示词注入系统提示）
    if settings.skills_enabled:
        # 导入 builtin 触发 @skill 注册
        import app.skills.builtin  # noqa: F401

        # Skill 工具走工具注册表注入
        from app.agent import registry as tool_reg
        from app.skills.registry import skill_registry
        loaded = skill_registry.load_all_defaults(tool_registry=tool_reg)
        logger.info("✅ Skill 系统已加载（%d 个）", loaded)
    # 初始化长期记忆 store（预热单例）
    try:
        from app.memory.store import get_store
        await get_store()
        logger.info("✅ 长期记忆 store 已就绪")
    except Exception as e:  # noqa: BLE001
        logger.warning("长期记忆 store 初始化失败（不阻断）：%s", e)
    # 挂载 A2A 路由（让本 Agent 可被外部 Agent 发现与调用）
    if settings.a2a_enabled:
        from app.a2a.server import mount_a2a
        mount_a2a(app, base_url=settings.a2a_base_url)
    # 注册 A2A delegate 工具（让本 Agent 能调用外部 Agent）
    try:
        from app.a2a.client import delegate_to_agent
        from app.agent.registry import register_tool
        register_tool(delegate_to_agent)
        logger.info("✅ A2A delegate 工具已注册")
    except Exception as e:  # noqa: BLE001
        logger.warning("A2A delegate 工具注册失败（不阻断）：%s", e)
    logger.info("✅ 基础设施就绪")
    yield
    logger.info("👋 %s 关闭中，释放连接", settings.app_name)
    # 按初始化的逆序释放（依赖后者先关）
    await mcp_client_manager.disconnect()
    # 先丢掉 store/checkpointer 单例，再关它们共享的连接池
    try:
        from app.memory import store as store_mod
        from app.memory.checkpointer import reset_checkpointer

        store_mod._store = None
        store_mod._memory_service = None
        await reset_checkpointer()
    except Exception as e:  # noqa: BLE001
        logger.warning("释放记忆层单例失败：%s", e)
    try:
        from app.memory.pg import close_pg_pool
        await close_pg_pool()
    except Exception as e:  # noqa: BLE001
        logger.warning("关闭 LangGraph 连接池失败：%s", e)
    await db_manager.disconnect()
    logger.info("✅ 已关闭")


app = FastAPI(
    title=settings.app_name,
    description="企业级 AI Agent —— LangGraph + 多协议 LLM(GLM/OpenAI/Anthropic) + MCP + A2A",
    version="0.1.0",
    lifespan=lifespan,
    # 生产环境关闭交互式文档，避免暴露 API 面
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)

# CORS（开发期允许所有来源；生产需显式配置可信来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_dev else [],
    allow_credentials=settings.is_dev,  # "*" + credentials 不安全，开发态放宽
    allow_methods=["*"],
    allow_headers=["*"],
)
# 限流中间件（Redis 滑动窗口，按用户/IP）
from app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RateLimitMiddleware)
# 指标采集中间件（记录请求延迟/计数，/metrics 暴露）
from app.services.observability import MetricsMiddleware  # noqa: E402

app.add_middleware(MetricsMiddleware)

# 异常处理 & 路由
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(rag_router)
app.include_router(api_router)
app.include_router(upload_router)

# 托管上传文件目录（图片等可访问）
from pathlib import Path  # noqa: E402

_upload_dir = Path(settings.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")


@app.get("/", tags=["系统"])
async def root():
    """根路径：项目简介。"""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": ["/health", "/chat", "/chat/stream"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_dev,
    )
