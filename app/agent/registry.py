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

from enum import StrEnum

from langchain_core.tools import BaseTool

from app.agent.tools import TOOL_MAP, TOOL_RISKS
from app.core.logging import get_logger

logger = get_logger(__name__)


class ToolRisk(StrEnum):
    """工具风险等级——决定执行前要不要问用户。

    分级依据是「出错的后果可不可逆」，不是「操作复不复杂」：
        READ  读文件、搜索、算数    —— 错了重来即可
        WRITE 写/改/删文件          —— 改变用户工作区，可逆但要人知情
        EXEC  执行命令、访问网络    —— 后果不可预测且可能不可逆
    """

    READ = "read"
    WRITE = "write"
    EXEC = "exec"


# 未显式声明风险的工具一律按 EXEC 处理。这是**故意的保守默认**：
# 新工具（尤其是 MCP 发现来的第三方工具）接进来时若没分级，
# 宁可多问用户一次，也不能默默放行一个可能删库的东西。
DEFAULT_RISK = ToolRisk.EXEC

# 已注册的工具：name → BaseTool
_registry: dict[str, BaseTool] = dict(TOOL_MAP)
# 工具风险等级：name → ToolRisk
_risks: dict[str, ToolRisk] = {}


def _risk_from_metadata(tool: BaseTool) -> ToolRisk:
    """从工具自带的 metadata 里读风险等级（@tool(metadata={"risk": ...})）。"""
    meta = getattr(tool, "metadata", None) or {}
    raw = meta.get("risk")
    if isinstance(raw, ToolRisk):
        return raw
    if isinstance(raw, str):
        try:
            return ToolRisk(raw)
        except ValueError:
            logger.warning("工具 '%s' 的 risk='%s' 无法识别，按最高风险处理", tool.name, raw)
    return DEFAULT_RISK


# 内置工具的等级要在这里补齐：_registry 是直接从 TOOL_MAP 建的，
# 没走 register_tool，不初始化的话它们会全部落到保守默认 EXEC，
# 结果连 calculator 都要弹审批。
_risks.update({name: ToolRisk(risk) for name, risk in TOOL_RISKS.items()})


def register_tool(tool: BaseTool, risk: ToolRisk | None = None) -> None:
    """注册一个工具。重名会覆盖并告警。"""
    if tool.name in _registry:
        logger.warning("工具 '%s' 已存在，将被覆盖", tool.name)
    _registry[tool.name] = tool
    _risks[tool.name] = risk or _risk_from_metadata(tool)


def register_tools(tools: list[BaseTool], risk: ToolRisk | None = None) -> int:
    """批量注册工具，返回成功注册的数量。"""
    count = 0
    for t in tools:
        register_tool(t, risk)
        count += 1
    return count


def get_risk(name: str) -> ToolRisk:
    """查工具风险等级。未知工具按最高风险处理。"""
    return _risks.get(name, DEFAULT_RISK)


def risk_map() -> dict[str, str]:
    """全部工具的风险等级（供 /tools 接口与 CLI 展示）。"""
    return {name: get_risk(name).value for name in _registry}


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
