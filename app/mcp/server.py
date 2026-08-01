"""
MCP Server（对外暴露工具）
--------------------------
用官方 FastMCP 把本 Agent 的内置工具暴露为标准 MCP server，
这样其他 Agent（无论用什么框架）都能通过 MCP 协议调用我们的工具。

这是 MCP 的「被调用」方向：本 Agent 既是工具的使用者(client)，
也是工具的提供者(server)。

启动：
    python -m app.mcp.server            # stdio 传输（默认，本地）
    python -m app.mcp.server --http     # streamable-http 传输（远程可访问）

也可在 app.main 启动时通过 MCP_SERVER_ENABLED=true 一并拉起 HTTP 模式。
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server.fastmcp import FastMCP

from app.agent.tools import ALL_TOOLS
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


def build_mcp_server() -> FastMCP:
    """构造 FastMCP server，把内置工具逐一注册为 MCP 工具。

    每个 @mcp.tool() 内部调用对应的 LangChain 工具，
    这样工具逻辑只维护一份（DRY），MCP 只是暴露层。
    """
    mcp = FastMCP("self-agent-tools")

    for tool in ALL_TOOLS:
        # 用闭包捕获当前 tool，避免循环变量陷阱
        def _make(t):
            # 从 langchain 工具的 args_schema 生成参数签名的运行时包装
            schema = t.args_schema.model_json_schema() if t.args_schema else {}

            async def _wrapped(**kwargs):
                """动态注册的 MCP 工具，转发到 LangChain 工具。"""
                result = await asyncio.to_thread(t.invoke, kwargs)
                return result

            _wrapped.__doc__ = t.description
            _wrapped.__name__ = t.name
            return t.name, t.description, _wrapped, schema

        name, desc, fn, schema = _make(tool)
        # FastMCP 用函数签名推断 schema；这里用 docstring + 直接装饰
        mcp.tool(name=name, description=desc)(fn)
        logger.debug("已注册 MCP 工具: %s", name)

    return mcp


def run_stdio() -> None:
    """以 stdio 传输运行（本地进程间通信）。"""
    setup_logging()
    logger.info("启动 MCP server（stdio 传输），暴露工具: %s", [t.name for t in ALL_TOOLS])
    mcp = build_mcp_server()
    mcp.run(transport="stdio")


def run_http(port: int) -> None:
    """以 streamable-http 传输运行（远程可访问）。"""
    setup_logging()
    logger.info("启动 MCP server（streamable-http），端口 %d", port)
    mcp = build_mcp_server()
    # FastMCP 的 run 支持 streamable-http 传输
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-Agent MCP Server")
    parser.add_argument(
        "--http", action="store_true",
        help="使用 streamable-http 传输（默认 stdio）",
    )
    parser.add_argument("--port", type=int, default=9000, help="HTTP 端口")
    args = parser.parse_args()

    if args.http:
        run_http(args.port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
