"""
MCP Client 管理器
-----------------
负责：
1. 读取 mcp_servers.json 配置
2. 用 langchain.mcp 的 MCPAdapter（fastmcp 4.x / MCP 2.x 协议栈）连接各外部 MCP server
3. 把发现到的工具统一转成 LangChain BaseTool（无缝接入 tools_node）
4. 生命周期随应用启停

2026-09 迁移说明：
    langchain-mcp-adapters 仓库已归档（2026-09-17），官方桥接迁入
    langchain 主包的 langchain.mcp 命名空间（`langchain[mcp]` extra，
    底层是 fastmcp 4.x + mcp 2.x 协议 SDK——2026-07-28 规范大版本）。
    旧 MultiServerMCPClient 的调用方式换成 MCPAdapter + 标准 MCPConfig
    （{"mcpServers": {...}}）；adapter 在 connect 时进入异步上下文并保持
    连接，disconnect 时退出——工具的 session 在两次请求之间保持可用。

设计要点：
- 单个 server 连不上不阻断其他（与 db_manager 一致的优雅降级）
- 懒加载：connect() 才真正连接；工具按 server 名去重防冲突（fastmcp 内部处理）
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MCPClientManager:
    """MCP 客户端单例：管理外部 MCP server 连接与工具发现。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._adapter: MCPAdapter | None = None
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

    @staticmethod
    def _to_mcp_config(servers: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """把 mcp_servers.json 的条目翻译成 fastmcp 的标准 MCPConfig 格式。

        标准 mcpServers 条目不需要显式 transport：
        - stdio → {"command": ..., "args": [...]}（有 command 即推断为 stdio）
        - streamable-http → {"url": "http..."}（http(s) URL 即推断）
        - 旧版 sse → {"transport": "sse", "url": ...}
        """
        mcp_servers: dict[str, dict[str, Any]] = {}
        for name, cfg in servers.items():
            transport = cfg.get("transport")
            if transport == "stdio" or "command" in cfg:
                entry: dict[str, Any] = {"command": cfg["command"]}
                if cfg.get("args"):
                    entry["args"] = cfg["args"]
                if cfg.get("env"):
                    entry["env"] = cfg["env"]
            elif transport == "sse" or cfg.get("transport") == "sse":
                entry = {"transport": "sse", "url": cfg["url"]}
            elif "url" in cfg:
                entry = {"url": cfg["url"]}
            else:
                logger.warning("MCP server '%s' 配置无法识别（缺 command/url），跳过", name)
                continue
            mcp_servers[name] = entry
        return {"mcpServers": mcp_servers}

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

        mcp_config = self._to_mcp_config(servers)
        try:
            self._adapter = MCPAdapter(mcp_config)
            # 进入异步上下文并保持连接：adapter 存活期间，发现的工具才能
            # 跨请求执行（session 由底层 fastmcp client 管理）
            await self._adapter.__aenter__()
            self._tools = await self._adapter.list_tools()
            self._connected = True
            logger.info(
                "MCP client 已连接 %d 个 server，发现 %d 个工具：%s",
                len(servers), len(self._tools), [t.name for t in self._tools],
            )
        except Exception as e:  # noqa: BLE001
            # 优雅降级：外部 server 不可用不阻断 Agent
            logger.warning("MCP client 连接失败（不阻断启动）：%s", e)
            if self._adapter is not None:
                with contextlib.suppress(Exception):
                    await self._adapter.__aexit__(None, None, None)
            self._adapter = None
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
        """退出 adapter 上下文，释放各 server 连接。"""
        if self._adapter is not None:
            try:
                await self._adapter.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.debug("MCP adapter 关闭异常（忽略）：%s", e)
        self._adapter = None
        self._tools = []
        self._connected = False
        if self.settings.mcp_client_enabled:
            logger.info("MCP client 已断开")


# 模块级单例
mcp_client_manager = MCPClientManager()
