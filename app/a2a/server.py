"""
A2A Server 集成
----------------
把 A2A 路由挂载到 FastAPI app，让本 Agent 可被其他 A2A 客户端发现和调用。

挂载内容：
- /.well-known/agent-card.json  —— Agent Card（能力清单，供发现）
- /                        —— JSON-RPC 端点（message/send 等）
- REST 路由                 —— （a2a-sdk 提供）

集成方式：在 app 启动时调用 mount_a2a(app)。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.a2a.executor import SelfAgentExecutor, build_agent_card
from app.core.logging import get_logger

logger = get_logger(__name__)


def mount_a2a(app: FastAPI, base_url: str = "http://localhost:8000") -> bool:
    """把 A2A 路由挂载到 FastAPI app。

    成功返回 True，失败（如 a2a-sdk 版本不兼容）返回 False 不阻断。
    """
    try:
        from a2a.server.request_handlers import DefaultRequestHandler
        from a2a.server.routes import (
            create_agent_card_routes,
            create_jsonrpc_routes,
            create_rest_routes,
        )
        from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
        from a2a.server.tasks import InMemoryTaskStore
    except ImportError as e:
        logger.warning("A2A 模块不可用，跳过挂载：%s", e)
        return False

    try:
        agent_card = build_agent_card(base_url)
        executor = SelfAgentExecutor()
        handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
            agent_card=agent_card,
        )

        add_a2a_routes_to_fastapi(
            app,
            agent_card_routes=create_agent_card_routes(agent_card),
            jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
            rest_routes=create_rest_routes(handler),
        )
        logger.info("✅ A2A 路由已挂载（本 Agent 可被外部 Agent 发现与调用）")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("A2A 路由挂载失败（不阻断）：%s", e)
        return False
