"""
本地模式（内嵌 Agent）
======================
`selfagent` 在任意目录敲下去就能干活——不需要先起后端，不需要装
Postgres/Mongo/Redis/Neo4j。这是 CLI 形态与服务端形态的根本区别：

    服务端形态：CLI --HTTP--> FastAPI --> Agent --> 文件（**服务端的**磁盘）
    本地形态：  CLI --直接调用--> Agent --> 文件（**你的**磁盘）

编码 Agent 必须是后者：文件工具操作的是你 cd 进去的那个目录。

实现上很轻——run_agent / stream_agent 本来就是普通 async 函数，
直接 import 调用即可。真正要处理的是环境预设：必须在**任何 app 模块
被导入之前**把配置写进环境变量，因为 get_settings() 带 lru_cache，
读一次就定型了。
"""

from __future__ import annotations

import os
from pathlib import Path


def bootstrap(workspace: str | None = None, *, approval_mode: str | None = None) -> Path:
    """预设本地模式的环境，返回工作区路径。

    必须在 import app.* 之前调用。
    """
    root = Path(workspace or os.getcwd()).expanduser().resolve()

    defaults = {
        # 状态落单文件 SQLite，不依赖任何数据库服务
        "STORAGE_BACKEND": "sqlite",
        "WORKSPACE_ROOT": str(root),
        # 编码工具是本地模式的重点
        "CODING_TOOLS_ENABLED": "true",
        # 本地单用户，不需要认证/多租户/限流
        "AUTH_ENABLED": "false",
        "MULTI_TENANT_ENABLED": "false",
        "RATE_LIMIT_ENABLED": "false",
        # 不起 A2A / MCP server 之类的服务端组件
        "A2A_ENABLED": "false",
        "MCP_SERVER_ENABLED": "false",
        # Hermes 的被动学习会额外烧一次 LLM 调用，本地默认关掉，
        # 需要的人显式开
        "HERMES_LEARNING_ENABLED": "false",
        # 编码任务步数远多于问答：25 步只够 12 个工具回合，不够用
        "AGENT_RECURSION_LIMIT": "80",
    }
    if approval_mode:
        defaults["TOOL_APPROVAL_MODE"] = approval_mode

    # 用 setdefault：用户已经在 .env / 环境里显式配过的，不覆盖
    for k, v in defaults.items():
        os.environ.setdefault(k, v)
    # 工作区必须以命令行为准（用户可能在不同目录反复启动）
    os.environ["WORKSPACE_ROOT"] = str(root)
    return root


async def setup_agent() -> dict:
    """初始化本地 Agent，返回一份能力概览供 CLI 展示。"""
    from app.agent.plan import PLAN_TOOLS
    from app.agent.registry import ToolRisk, register_tools, risk_map
    from app.agent.tools.files import READ_TOOLS, WRITE_TOOLS
    from app.agent.tools.shell import SHELL_TOOLS
    from app.core.config import get_settings
    from app.memory.local_store import resolve_sqlite_path
    from app.sandbox import describe as sandbox_describe
    from app.workspace import get_workspace

    register_tools(READ_TOOLS, ToolRisk.READ)
    register_tools(WRITE_TOOLS, ToolRisk.WRITE)
    register_tools(SHELL_TOOLS, ToolRisk.EXEC)
    register_tools(PLAN_TOOLS, ToolRisk.READ)   # 计划只是记事板，不必审批

    # Skill 的工具也并进来
    s = get_settings()
    if s.skills_enabled:
        try:
            import app.skills.builtin  # noqa: F401  触发 @skill 注册
            from app.agent import registry as tool_reg
            from app.skills.registry import skill_registry

            skill_registry.load_all_defaults(tool_registry=tool_reg)
        except Exception:  # noqa: BLE001
            pass

    # 预热状态图（建 SQLite 表），让第一句话不必等
    from app.agent.graph import get_compiled_graph

    await get_compiled_graph()

    return {
        "workspace": str(get_workspace().root),
        "storage": str(resolve_sqlite_path()),
        "sandbox": sandbox_describe(),
        "approval_mode": s.tool_approval_mode,
        "provider": s.llm_default_provider,
        "tools": risk_map(),
    }


async def shutdown_agent() -> None:
    """释放本地资源。"""
    from app.memory.checkpointer import reset_checkpointer
    from app.memory.local_store import close_sqlite

    await reset_checkpointer()
    await close_sqlite()
