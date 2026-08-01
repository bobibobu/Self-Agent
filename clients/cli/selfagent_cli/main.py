"""
Self-Agent CLI 主程序
---------------------
类 Claude Code 的交互式命令行对话。

特性：
- 真·token 级流式输出（NDJSON，逐字 rich 渲染）
- 工具调用过程实时展示
- 命令系统：/new /user /tools /memory /profile /help /exit
- 输入历史（上下键）、多行（Shift+Enter）

启动：
    selfagent              # 交互式
    selfagent "你好"       # 单次查询
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from selfagent_cli.api import get_json, stream_chat
from selfagent_cli.config import Session

console = Console()

BANNER = """
[bold cyan]╔══════════════════════════════════════╗[/]
[bold cyan]║          🤖 Self-Agent CLI           ║[/]
[bold cyan]╚══════════════════════════════════════╝[/]
[dim]企业级 AI Agent · 流式对话 · 工具调用 · 记忆增强[/]
[dim]输入 /help 查看命令，/exit 退出[/]
"""


async def run_stream(session: Session, message: str) -> None:
    """执行一次流式对话，实时渲染。"""
    full_text = Text("")
    tool_lines: list[str] = []

    def render():
        """构造当前渲染内容。"""
        from io import StringIO

        parts = []
        if tool_lines:
            parts.append(Text("\n".join(tool_lines) + "\n", style="dim yellow"))
        parts.append(full_text)
        return Text.assemble(*parts)

    try:
        with Live(render(), console=console, refresh_per_second=20, vertical_overflow="visible") as live:
            async for event in stream_chat(session.api_url, message, session.thread_id, session.user_id):
                etype = event.get("type")
                if etype == "token":
                    full_text.append(event.get("text", ""))
                    live.update(render())
                elif etype == "tool_calls":
                    names = [c.get("name", "?") for c in event.get("calls", [])]
                    tool_lines.append(f"🔧 决定调用: {', '.join(names)}")
                    live.update(render())
                elif etype == "tool_start":
                    tool_lines.append(f"  ⏳ 正在执行 {event.get('name')}...")
                    live.update(render())
                elif etype == "tool_result":
                    content = (event.get("content") or "")[:80]
                    tool_lines.append(f"  ✓ {event.get('name')}: {content}")
                    live.update(render())
                elif etype == "done":
                    if event.get("reply") and not str(full_text):
                        full_text.append(event["reply"])
                    live.update(render())
                elif etype == "error":
                    tool_lines.append(f"⚠️ 错误: {event.get('message')}")
                    live.update(render())
    except httpx.ConnectError as e:
        console.print(f"\n[red]⚠️ 连接失败：{e}[/]")
        console.print(f"[dim]请确认后端已启动：{session.api_url}[/]")
    except httpx.HTTPError as e:
        console.print(f"\n[red]⚠️ HTTP 错误：{e}[/]")
    except Exception as e:  # noqa: BLE001
        console.print(f"\n[red]⚠️ 出错：{e}[/]")

    # 最终用 Markdown 渲染完整回复（更美观）
    if str(full_text).strip():
        console.print()  # 空行分隔
        try:
            console.print(Markdown(str(full_text)))
        except Exception:  # noqa: BLE001
            console.print(full_text)


async def handle_command(session: Session, cmd: str, args: list[str]) -> bool:
    """处理斜杠命令。返回 False 表示退出。"""
    if cmd == "exit":
        console.print("[dim]再见！👋[/]")
        return False
    if cmd == "help":
        console.print(Panel(
            "[bold]命令：[/]\n"
            "  /new          新对话（重置会话）\n"
            "  /user <id>    设置用户 ID\n"
            "  /tools        列出可用工具\n"
            "  /memory <id>  查看用户记忆（需 query 参数）\n"
            "  /profile <id> 查看用户画像\n"
            "  /status       查看当前会话状态\n"
            "  /help         显示帮助\n"
            "  /exit         退出",
            title="帮助", border_style="cyan",
        ))
    elif cmd == "new":
        session.reset_thread()
        console.print(f"[green]✓ 新会话：{session.thread_id}[/]")
    elif cmd == "user":
        if args:
            session.user_id = args[0]
            console.print(f"[green]✓ 用户已设为：{session.user_id}[/]")
        else:
            console.print(f"当前用户：{session.user_id}")
    elif cmd == "status":
        console.print(f"[dim]API: {session.api_url}[/]")
        console.print(f"[dim]用户: {session.user_id}[/]")
        console.print(f"[dim]会话: {session.thread_id}[/]")
    elif cmd == "tools":
        try:
            data = await get_json(session.api_url, "/tools")
            for t in data.get("tools", []):
                console.print(f"  🔧 [bold]{t['name']}[/] [dim]- {t.get('description', '')[:50]}[/]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]获取失败：{e}[/]")
    elif cmd == "profile":
        uid = args[0] if args else session.user_id
        try:
            data = await get_json(session.api_url, f"/profile/{uid}")
            console.print(Panel(
                f"兴趣: {data.get('interests', [])}\n"
                f"偏好: {data.get('preferences', {})}\n"
                f"来源: {data.get('source')}",
                title=f"用户画像 · {uid}", border_style="magenta",
            ))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]获取失败：{e}[/]")
    elif cmd == "memory":
        if not args:
            console.print("[yellow]用法：/memory <查询关键词>[/]")
        else:
            query = " ".join(args)
            try:
                data = await get_json(session.api_url, f"/memory/{session.user_id}?query={query}")
                for m in data.get("memories", []):
                    console.print(f"  • {m.get('content', '')}")
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]获取失败：{e}[/]")
    else:
        console.print(f"[red]未知命令：/{cmd}（/help 查看可用命令）[/]")
    return True


def read_input() -> str:
    """读取用户输入（支持多行、历史）。"""
    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.history import InMemoryHistory

        if not hasattr(read_input, "_history"):
            read_input._history = InMemoryHistory()
        return pt_prompt(">>> ", history=read_input._history, multiline=False)
    except ImportError:
        # 无 prompt_toolkit 时回退内置 input
        return input(">>> ")


async def repl(session: Session) -> None:
    """交互式 REPL 主循环。"""
    console.print(BANNER)
    # 检查后端连接
    try:
        h = await get_json(session.api_url, "/health")
        console.print(f"[green]✓ 已连接后端（{h.get('app')} v{h.get('version')}，provider={h.get('default_provider')}）[/]\n")
    except Exception:  # noqa: BLE001
        console.print(f"[yellow]⚠ 无法连接后端 {session.api_url}，请先启动：uv run uvicorn app.main:app[/]\n")

    while True:
        try:
            user_input = read_input().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！👋[/]")
            break

        if not user_input:
            continue

        # 斜杠命令
        if user_input.startswith("/"):
            parts = user_input[1:].split()
            cmd = parts[0] if parts else ""
            args = parts[1:]
            should_continue = await handle_command(session, cmd, args)
            if not should_continue:
                break
            console.print()  # 命令后空行
            continue

        # 普通对话
        console.print()  # 输入后空行
        await run_stream(session, user_input)
        console.print()  # 回复后空行


async def async_main() -> None:
    session = Session()
    # 单次查询模式：selfagent "你好"
    if len(sys.argv) > 1 and not sys.argv[1].startswith("/"):
        message = " ".join(sys.argv[1:])
        await run_stream(session, message)
    else:
        await repl(session)


def main() -> None:
    """入口点（被 console_script 调用）。"""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
