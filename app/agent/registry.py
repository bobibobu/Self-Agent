"""
Agent 工具注册表（单一真相来源）
--------------------------------
统一管理 Agent 可用的全部工具，包括：
- 内置工具（@tool 定义的 calculator / get_current_time / get_weather）
- MCP 工具（运行时从外部 MCP server 发现的 BaseTool）
- Phase 2 的 Skill 注册的工具

所有需要「工具列表」或「按名找工具」的地方都走这里，
保证 tools_node 的执行映射与 LLM 看到的工具声明一致。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.agent.tools import TOOL_MAP
from app.core.logging import get_logger

logger = get_logger(__name__)

# 已注册的工具：name → BaseTool
_registry: dict[str, BaseTool] = dict(TOOL_MAP)


def register_tool(tool: BaseTool) -> None:
    """注册一个工具。重名会覆盖并告警。"""
    if tool.name in _registry:
        logger.warning("工具 '%s' 已存在，将被覆盖", tool.name)
    _registry[tool.name] = tool


def register_tools(tools: list[BaseTool]) -> int:
    """批量注册工具，返回成功注册的数量。"""
    count = 0
    for t in tools:
        register_tool(t)
        count += 1
    return count


def get_all_tools() -> list[BaseTool]:
    """获取当前已注册的全部工具（用于 LLM 工具声明）。"""
    return list(_registry.values())


def get_tool(name: str) -> BaseTool | None:
    """按名查找工具。"""
    return _registry.get(name)


def tool_names() -> list[str]:
    return list(_registry.keys())


def refresh_from_mcp(mcp_tools: list[BaseTool]) -> int:
    """把 MCP 发现的工具合并进注册表，返回新增数量。

    供应用启动时（mcp_client_manager.connect 后）调用。
    """
    added = 0
    for t in mcp_tools:
        if t.name not in _registry:
            _registry[t.name] = t
            added += 1
        else:
            logger.warning("MCP 工具 '%s' 与内置工具重名，保留内置版本", t.name)
    if added:
        logger.info("工具注册表新增 %d 个 MCP 工具", added)
    return added
