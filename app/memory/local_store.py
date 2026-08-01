"""
本地状态存储（SQLite）
======================
CLI 形态不能要求用户先装 Postgres + Mongo + Redis + Neo4j 才能跑起来——
那是服务端的形态，不是命令行工具的形态。这里提供一个单文件 SQLite 后端，
零外部依赖，`selfagent` 在任意目录敲下去就能用。

会话按**工作区**分库存放：

    ~/.local/share/selfagent/projects/<工作区路径哈希>/state.db

同一个项目里的历史对话能续上，换个项目就是干净的新开始——
这与「工作区是编码 Agent 的上下文单位」这条一致。
目录里同时写一个 workspace.txt 记录原始路径，便于排查时知道哪个库对应哪个项目。
"""

from __future__ import annotations

import hashlib
import os
from contextlib import AsyncExitStack
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

_stack: AsyncExitStack | None = None


def data_home() -> Path:
    """XDG 数据目录下的应用根目录。"""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "selfagent"


def sqlite_path_for(workspace: Path) -> Path:
    """给定工作区对应的 SQLite 文件路径（不存在则建目录）。

    用路径哈希而不是路径本身做目录名：工作区路径可能很长、含空格或非 ASCII，
    直接当目录名在跨平台上会出问题。
    """
    digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    project_dir = data_home() / "projects" / digest
    project_dir.mkdir(parents=True, exist_ok=True)
    # 留一份可读记录，否则一堆哈希目录没法排查
    marker = project_dir / "workspace.txt"
    if not marker.exists():
        marker.write_text(str(workspace.resolve()) + "\n", encoding="utf-8")
    return project_dir / "state.db"


def resolve_sqlite_path() -> Path:
    """按配置决定 SQLite 文件位置。"""
    from app.core.config import get_settings
    from app.workspace import get_workspace

    configured = get_settings().sqlite_path
    if configured:
        p = Path(configured).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return sqlite_path_for(get_workspace().root)


async def create_sqlite_checkpointer():
    """建 SQLite checkpointer。失败返回 None 由调用方降级。

    注意 from_conn_string 是 @asynccontextmanager（与 Postgres 版同一个坑），
    必须用 AsyncExitStack 把生命周期托管到应用级，不能拿返回值直接当 saver 用。
    """
    global _stack
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError as e:
        logger.warning("langgraph-checkpoint-sqlite 未安装：%s", e)
        return None

    path = resolve_sqlite_path()
    try:
        _stack = AsyncExitStack()
        saver = await _stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(path)))
        await saver.setup()
        logger.info("短期记忆：SQLite（%s）", path)
        return saver
    except Exception as e:  # noqa: BLE001
        logger.warning("SQLite checkpointer 初始化失败：%s", e)
        if _stack is not None:
            await _stack.aclose()
            _stack = None
        return None


async def close_sqlite() -> None:
    """关闭 SQLite 连接。"""
    global _stack
    if _stack is not None:
        try:
            await _stack.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭 SQLite 失败：%s", e)
        _stack = None
