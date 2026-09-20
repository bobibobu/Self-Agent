"""
MCP Server（对外暴露工具）
--------------------------
用 FastMCP 4.x（fastmcp 独立包，官方 mcp SDK 2.x 生态的继承者）把本 Agent
的内置工具暴露为标准 MCP server（协议版本 2026-07-28 规范），
其他 Agent（无论用什么框架）都能通过 MCP 协议调用我们的工具。

这是 MCP 的「被调用」方向：本 Agent 既是工具的使用者(client)，
也是工具的提供者(server)。

⚠️ 迁移说明（2026-09）：官方 mcp SDK 2.0 移除了内置 FastMCP
（mcp.server.fastmcp 导入会指向迁移指南），本模块改用独立维护的
fastmcp 包（`from fastmcp import FastMCP`，装饰器 API 兼容）。
同时修掉了旧实现的一个隐患：原来用 `async def _wrapped(**kwargs)`
注册工具——`**kwargs` 签名推不出参数 schema，注册出去的是无参工具；
现在从 LangChain 工具的 args_schema 动态生成带真实类型签名的包装函数。

启动：
    python -m app.mcp.server            # stdio 传输（默认，本地）
    python -m app.mcp.server --http     # streamable-http 传输（远程可访问）

也可在 app.main 启动时通过 MCP_SERVER_ENABLED=true 一并拉起 HTTP 模式。
"""

from __future__ import annotations

import argparse
from typing import Any

from fastmcp import FastMCP

from app.agent.tools import ALL_TOOLS
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


def _build_typed_wrapper(t) -> Any:
    """从 LangChain 工具的 args_schema 动态生成带真实签名的 async 包装函数。

    fastmcp 用 inspect.signature + get_type_hints 推导工具的输入 schema，
    所以包装函数必须同时携带参数名、默认值和真实类型注解——
    `**kwargs` 签名会退化成无参工具（旧实现的隐患）。

    参数类型对象放进 exec 命名空间，注解在 def 时立即求值（无
    from __future__ import annotations 的延迟求值），get_type_hints 可解析。
    """
    from pydantic import BaseModel

    model = t.args_schema if isinstance(t.args_schema, type) and issubclass(t.args_schema, BaseModel) else None
    ns: dict[str, Any] = {"_tool": t, "Any": Any}
    param_srcs: list[str] = []
    invoke_keys: list[str] = []

    if model is not None:
        for i, (fname, field) in enumerate(model.model_fields.items()):
            ann_key = f"_ann_{i}"
            ns[ann_key] = field.annotation
            invoke_keys.append(fname)
            if field.is_required():
                param_srcs.append(f"{fname}: {ann_key}")
            else:
                ns[f"_dflt_{i}"] = field.get_default(call_default_factory=False)
                param_srcs.append(f"{fname}: {ann_key} = _dflt_{i}")

    body_keys = ", ".join(f"'{k}': {k}" for k in invoke_keys)
    src = (
        f"async def _dynamic_tool({', '.join(param_srcs)}) -> Any:\n"
        f"    return await _tool.ainvoke({{{body_keys}}})\n"
    )
    exec(src, ns)  # noqa: S102 - 受控动态生成：参数名/类型来自本仓库工具的 pydantic schema

    fn = ns["_dynamic_tool"]
    fn.__name__ = t.name
    fn.__doc__ = t.description
    # fastmcp 兼容 sync/async；ainvoke 内部自动调度，无需 to_thread
    return fn


def build_mcp_server() -> FastMCP:
    """构造 FastMCP server，把内置工具逐一注册为 MCP 工具。

    每个工具内部调用对应的 LangChain 工具，
    工具逻辑只维护一份（DRY），MCP 只是暴露层。
    """
    mcp = FastMCP("self-agent-tools")

    for tool in ALL_TOOLS:
        wrapper = _build_typed_wrapper(tool)
        mcp.tool(name=tool.name, description=tool.description)(wrapper)
        logger.debug("已注册 MCP 工具: %s", tool.name)

    return mcp


def run_stdio() -> None:
    """以 stdio 传输运行（本地进程间通信）。"""
    setup_logging()
    logger.info("启动 MCP server（stdio 传输），暴露工具: %s", [t.name for t in ALL_TOOLS])
    mcp = build_mcp_server()
    # show_banner=False：stdio 下 stdout 被协议独占，横幅/日志都必须离 stdout 远点
    mcp.run(transport="stdio", show_banner=False)


def run_http(port: int) -> None:
    """以 streamable-http 传输运行（远程可访问）。"""
    setup_logging()
    logger.info("启动 MCP server（streamable-http），端口 %d", port)
    mcp = build_mcp_server()
    # fastmcp 4.x 的 http 传输即 MCP 的 streamable-http；
    # 空闲会话 30 分钟过期、单实例会话上限等由 fastmcp 默认值兜底
    mcp.run(transport="http", host="0.0.0.0", port=port)


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
