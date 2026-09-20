"""MCP 2.x 协议栈端到端（fastmcp 4.x + langchain.mcp MCPAdapter）
================================================================
2026-09 迁移验证：

- 依赖：langchain[mcp] 1.4.2（fastmcp 4.0.5）+ mcp 2.2.0（2026-07-28 规范）
- 旧 langchain-mcp-adapters 的 MultiServerMCPClient → 新 langchain.mcp.MCPAdapter
- server 侧 mcp.server.fastmcp.FastMCP（2.0 已移除）→ fastmcp.FastMCP
- 钉住 stdio 的铁律：日志必须走 stderr——stdout 被协议独占，
  一行日志混进去 client 就会把响应解析炸掉（Connection closed）

端到端分两层：进程内 FastMCP server（官方推荐的测试形态，无子进程）
验证协议闭环；真实 stdio 子进程验证 client↔server 跨进程全链路。
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient


# ==================== 配置翻译（mcp_servers.json → 标准 MCPConfig）====================


class TestMcpConfigTranslation:
    def test_stdio_http_sse_mapping(self):
        from app.mcp.client import MCPClientManager

        servers = {
            "local": {"transport": "stdio", "command": "python", "args": ["-m", "x"]},
            "remote": {"transport": "http", "url": "http://localhost:9000/mcp"},
            "legacy_sse": {"transport": "sse", "url": "http://localhost:9100/sse"},
        }
        cfg = MCPClientManager._to_mcp_config(servers)
        assert set(cfg["mcpServers"]) == {"local", "remote", "legacy_sse"}
        assert cfg["mcpServers"]["local"]["command"] == "python"
        assert cfg["mcpServers"]["local"]["args"] == ["-m", "x"]
        assert cfg["mcpServers"]["remote"]["url"] == "http://localhost:9000/mcp"
        assert cfg["mcpServers"]["legacy_sse"]["transport"] == "sse"

    def test_unrecognized_entry_skipped(self):
        from app.mcp.client import MCPClientManager

        cfg = MCPClientManager._to_mcp_config({"bad": {"foo": 1}})
        assert cfg["mcpServers"] == {}


# ==================== 端到端：server 暴露 → client 发现 → 调用 ====================


class TestMcpV2EndToEnd:
    @pytest.mark.asyncio
    async def test_in_process_discovery_and_invocation(self):
        """进程内闭环：build_mcp_server() → MCPAdapter.list_tools() → 调用 calculator。"""
        from langchain.mcp import MCPAdapter

        from app.mcp.server import build_mcp_server

        server = build_mcp_server()
        async with MCPAdapter(server) as adapter:
            tools = await adapter.list_tools()
            names = [t.name for t in tools]
            # 内置工具全部暴露（含 2026-09 新增的 Agentic RAG 工具）
            assert {"calculator", "get_current_time", "search_knowledge_base"} <= set(names)

            calc = next(t for t in tools if t.name == "calculator")
            # schema 钉住：参数必须从 args_schema 正确生成（旧 **kwargs 隐患的回归测试）。
            # 适配后的 args_schema 可能是 pydantic 模型，也可能是 MCP 传来的 dict 形态
            schema = (
                calc.args_schema.model_json_schema()
                if hasattr(calc.args_schema, "model_json_schema")
                else calc.args_schema
            )
            assert "expression" in schema.get("properties", {})
            assert "expression" in schema.get("required", [])

            result = await calc.ainvoke({"expression": "3 + 4 * 2"})
            assert "11" in str(result)

    @pytest.mark.asyncio
    async def test_tool_description_round_trips(self):
        """LangChain 工具的 description 必须随 MCP 往返，供调用方 LLM 阅读。"""
        from langchain.mcp import MCPAdapter

        from app.mcp.server import build_mcp_server

        async with MCPAdapter(build_mcp_server()) as adapter:
            tools = await adapter.list_tools()
            calc = next(t for t in tools if t.name == "calculator")
            assert calc.description and "表达式" in calc.description

    def test_mcp_adapter_importable_and_stack_versions(self):
        """钉住依赖形态：langchain.mcp 存在、mcp 是 2.x、adapters 已移除。"""
        import importlib.util
        from importlib.metadata import version

        from langchain.mcp import MCPAdapter  # noqa: F401

        assert importlib.util.find_spec("langchain_mcp_adapters") is None
        mcp_version = version("mcp")
        assert mcp_version.startswith("2."), f"mcp 应为 2.x，实际 {mcp_version}"


    @pytest.mark.asyncio
    async def test_cross_process_stdio_roundtrip(self, tmp_path, monkeypatch):
        """真实跨进程：client(manager) ↔ stdio 子进程(server)，发现并调用工具。

        同时钉住「日志走 stderr」的回归——stdout 被协议占用，
        日志混进去就是 Connection closed。
        """
        import json

        from app.core.config import get_settings
        from app.mcp.client import mcp_client_manager

        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(json.dumps({
            "servers": {
                "self_tools": {
                    "enabled": True,
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "app.mcp.server"],
                },
            },
        }), encoding="utf-8")

        s = get_settings()
        saved = (s.mcp_servers_config, s.mcp_client_enabled)
        s.mcp_servers_config = str(config_path)
        s.mcp_client_enabled = True
        try:
            await mcp_client_manager.connect()
            assert mcp_client_manager.is_connected
            assert "calculator" in mcp_client_manager.tool_names()

            calc = next(t for t in mcp_client_manager.tools if t.name == "calculator")
            result = await calc.ainvoke({"expression": "21 * 2"})
            assert "42" in str(result)
        finally:
            await mcp_client_manager.disconnect()
            s.mcp_servers_config, s.mcp_client_enabled = saved


# ==================== 应用层兼容：/health 冒烟不受迁移影响 ====================


def test_app_boots_with_mcp_v2_stack():
    """MCP 栈整体替换后应用照常启动（lifespan 里 connect/disconnect 都要走新代码）。"""
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
