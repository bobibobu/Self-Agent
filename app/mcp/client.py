"""
MCP Client 管理器
-----------------
负责：
1. 读取 mcp_servers.json 配置
2. 用 MultiServerMCPClient 连接各外部 MCP server
3. 把发现到的工具统一转成 LangChain BaseTool（无缝接入 tools_node）
4. 生命周期随应用启停

设计要点：
- 单个 server 连不上不阻断其他（与 db_manager 一致的优雅降级）
- 工具按 "server名_工具名" 前缀防命名冲突
- 懒加载：首次 get_tools() 才真正连接
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MCPClientManager:
    """MCP 客户端单例：管理外部 MCP server 连接与工具发现。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] = []
        self._connected = False

    def _load_servers_config(self) -> dict[str, dict[str, Any]]:
        """读取 mcp_servers.json，过滤掉 enabled=false 的。"""
        config_path = Path(self.settings.mcp_servers_config)
        if not config_path.exists():
            logger.info("MCP 配置文件 %s 不存在，跳过外部 MCP server", config_path)
            return {}

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("MCP 配置文件解析失败：%s", e)
            return {}

        servers = data.get("servers", {})
        # 过滤：只保留 enabled 的，并剔除注释字段（_ 开头）
        enabled: dict[str, dict[str, Any]] = {}
        for name, cfg in servers.items():
            if not cfg.get("enabled", False):
                logger.debug("MCP server '%s' 已禁用，跳过", name)
                continue
            clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
            enabled[name] = clean
        return enabled

    async def connect(self) -> None:
        """连接所有已启用的外部 MCP server，发现工具。

        失败不抛异常（优雅降级），仅记录告警。
        """
        if not self.settings.mcp_client_enabled:
            logger.info("MCP client 已在配置中禁用")
            return

        servers = self._load_servers_config()
        if not servers:
            logger.info("无已启用的外部 MCP server")
            return

        try:
            self._client = MultiServerMCPClient(servers)
            # get_tools() 内部建立连接并发现各 server 的工具
            self._tools = await self._client.get_tools()
            self._connected = True
            tool_names = [t.name for t in self._tools]
            logger.info(
                "MCP client 已连接 %d 个 server，发现 %d 个工具：%s",
                len(servers), len(self._tools), tool_names,
            )
        except Exception as e:  # noqa: BLE001
            # 优雅降级：外部 server 不可用不阻断 Agent
            logger.warning("MCP client 连接失败（不阻断启动）：%s", e)
            self._tools = []

    @property
    def tools(self) -> list[BaseTool]:
        """已发现的 MCP 工具列表（LangChain BaseTool）。"""
        return self._tools

    @property
    def is_connected(self) -> bool:
        return self._connected

    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    async def disconnect(self) -> None:
        """释放连接。MultiServerMCPClient 内部管理 session，此处清理引用。"""
        self._client = None
        self._tools = []
        self._connected = False
        if self.settings.mcp_client_enabled:
            logger.info("MCP client 已断开")


# 模块级单例
mcp_client_manager = MCPClientManager()
