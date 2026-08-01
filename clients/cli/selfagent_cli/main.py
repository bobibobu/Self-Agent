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

import argparse
import asyncio
import contextlib
import sys

import httpx
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from selfagent_cli.api import AuthRequired, get_json, login, register, stream_chat
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

        parts = []
        if tool_lines:
            parts.append(Text("\n".join(tool_lines) + "\n", style="dim yellow"))
        parts.append(full_text)
        return Text.assemble(*parts)

    try:
        with Live(render(), console=console, refresh_per_second=20, vertical_overflow="visible") as live:
            async for event in stream_chat(
                session.api_url, message, session.thread_id, session.user_id, token=session.token,
            ):
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
    except AuthRequired as e:
        console.print(f"\n[yellow]🔒 {e}[/]")
        console.print("[dim]后端开了认证（AUTH_ENABLED=true）。执行 /login <用户名> 登录，"
                      "或 /register <用户名> 注册。[/]")
        return
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
            "[bold]账号：[/]\n"
            "  /login <用户名>     登录（后端开认证时必需）\n"
            "  /register <用户名>  注册新账号并登录\n"
            "  /logout            退出登录，清除本地 token\n"
            "[bold]会话：[/]\n"
            "  /new               新对话（重置会话）\n"
            "  /sessions          列出历史会话\n"
            "  /resume <thread>   切到指定会话并显示历史\n"
            "  /history           显示当前会话的历史消息\n"
            "[bold]其他：[/]\n"
            "  /tools             列出可用工具\n"
            "  /memory <关键词>   检索长期记忆\n"
            "  /profile [用户id]  查看用户画像\n"
            "  /status            查看当前状态\n"
            "  /help /exit",
            title="帮助", border_style="cyan",
        ))
    elif cmd == "login":
        await _do_login(session, args, is_register=False)
    elif cmd == "register":
        await _do_login(session, args, is_register=True)
    elif cmd == "logout":
        session.logout()
        console.print("[green]✓ 已退出登录，本地 token 已清除[/]")
    elif cmd == "new":
        session.reset_thread()
        console.print(f"[green]✓ 新会话：{session.thread_id}[/]")
    elif cmd == "sessions":
        await _guarded(_list_sessions(session))
    elif cmd == "resume":
        if not args:
            console.print("[yellow]用法：/resume <thread_id>（先用 /sessions 查看）[/]")
        else:
            session.thread_id = args[0]
            console.print(f"[green]✓ 已切到会话 {session.thread_id}[/]")
            await _guarded(_show_history(session))
    elif cmd == "history":
        await _guarded(_show_history(session))
    elif cmd == "user":
        if args:
            session.user_id = args[0]
            console.print(f"[green]✓ 用户已设为：{session.user_id}[/]")
            if session.is_logged_in:
                console.print("[dim]注意：已登录时后端以 token 身份为准，此设置只影响本地展示[/]")
        else:
            console.print(f"当前用户：{session.user_id}")
    elif cmd == "status":
        who = f"{session.username} ({session.user_id})" if session.is_logged_in else "未登录（匿名模式）"
        console.print(f"[dim]API:  {session.api_url}[/]")
        console.print(f"[dim]身份: {who}[/]")
        console.print(f"[dim]会话: {session.thread_id}[/]")
    elif cmd == "tools":
        await _guarded(_list_tools(session))
    elif cmd == "profile":
        uid = args[0] if args else session.user_id
        await _guarded(_show_profile(session, uid))
    elif cmd == "memory":
        if not args:
            console.print("[yellow]用法：/memory <查询关键词>[/]")
        else:
            await _guarded(_search_memory(session, " ".join(args)))
    else:
        console.print(f"[red]未知命令：/{cmd}（/help 查看可用命令）[/]")
    return True


async def _guarded(coro) -> None:
    """统一处理命令里的 401 与其他异常，避免每个分支重复 try。"""
    try:
        await coro
    except AuthRequired as e:
        console.print(f"[yellow]🔒 {e}[/]")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]获取失败：{e}[/]")


async def _do_login(session: Session, args: list[str], *, is_register: bool) -> None:
    """登录 / 注册。密码走 getpass 读取，不回显、不进 shell 历史。"""
    import getpass

    action = "注册" if is_register else "登录"
    username = args[0] if args else console.input("用户名: ").strip()
    if not username:
        console.print("[yellow]已取消[/]")
        return
    try:
        password = getpass.getpass("密码: ")
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]已取消[/]")
        return
    if not password:
        console.print("[yellow]已取消[/]")
        return

    try:
        fn = register if is_register else login
        data = await fn(session.api_url, username, password)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]{action}失败：{e}[/]")
        return

    session.set_auth(data["access_token"], data.get("user") or {})
    console.print(f"[green]✓ {action}成功，欢迎 {session.username or username}[/]")
    console.print("[dim]token 已保存到 ~/.config/selfagent/credentials.json（权限 0600）[/]")


async def _list_sessions(session: Session) -> None:
    data = await get_json(session.api_url, "/sessions", token=session.token)
    sessions = data.get("sessions", [])
    if not sessions:
        console.print("[dim]暂无历史会话[/]")
        return
    for s in sessions:
        mark = "→" if s["thread_id"] == session.thread_id else " "
        console.print(f" {mark} [bold]{s['thread_id']}[/]  {s.get('title', '')}  "
                      f"[dim]{(s.get('updated_at') or '')[:19]}[/]")
    console.print("[dim]用 /resume <thread_id> 切换[/]")


async def _show_history(session: Session) -> None:
    """显示当前会话的历史消息（来自 MongoDB 对话日志）。"""
    data = await get_json(
        session.api_url, f"/history/{session.thread_id}", token=session.token, params={"limit": 50},
    )
    events = data.get("events", [])
    if not events:
        console.print("[dim]这个会话还没有历史消息"
                      "（历史来自 MongoDB 对话日志，若未启动 Mongo 则始终为空）[/]")
        return
    for ev in events:
        if ev.get("user_message"):
            console.print(f"[bold cyan]>>> {ev['user_message']}[/]")
        if ev.get("agent_reply"):
            console.print(ev["agent_reply"])
        console.print()


async def _list_tools(session: Session) -> None:
    data = await get_json(session.api_url, "/tools", token=session.token)
    for t in data.get("tools", []):
        console.print(f"  🔧 [bold]{t['name']}[/] [dim]- {t.get('description', '')[:50]}[/]")


async def _show_profile(session: Session, uid: str) -> None:
    data = await get_json(session.api_url, f"/profile/{uid}", token=session.token)
    console.print(Panel(
        f"兴趣: {data.get('interests', [])}\n"
        f"偏好: {data.get('preferences', {})}\n"
        f"来源: {data.get('source')}",
        title=f"用户画像 · {uid}", border_style="magenta",
    ))


async def _search_memory(session: Session, query: str) -> None:
    # 查询串走 params 交给 httpx 编码：手工拼 f"?query={query}" 遇到空格/中文/& 会拼坏
    data = await get_json(
        session.api_url, f"/memory/{session.user_id}",
        token=session.token, params={"query": query},
    )
    memories = data.get("memories", [])
    if not memories:
        console.print("[dim]没有检索到相关记忆[/]")
    for m in memories:
        console.print(f"  • {m.get('content', '')}")


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
        console.print(f"[green]✓ 已连接后端（{h.get('app')} v{h.get('version')}，provider={h.get('default_provider')}）[/]")
    except Exception:  # noqa: BLE001
        console.print(f"[yellow]⚠ 无法连接后端 {session.api_url}，请先启动：uv run uvicorn app.main:app[/]\n")
        return

    # 探测后端是否要求认证：直接问一个受保护端点，比让用户在第一句话上撞 401 好
    try:
        await get_json(session.api_url, "/sessions", token=session.token)
        if session.is_logged_in:
            console.print(f"[green]✓ 已登录：{session.username or session.user_id}[/]\n")
        else:
            console.print("[dim]后端未开启认证，以匿名模式运行[/]\n")
    except AuthRequired:
        console.print("[yellow]🔒 后端已开启认证，请先登录：[/]")
        console.print("[dim]  /login <用户名>     已有账号[/]")
        console.print("[dim]  /register <用户名>  新建账号[/]\n")
    except Exception:  # noqa: BLE001
        console.print()

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


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="selfagent",
        description="Self-Agent CLI —— 在当前目录里干活的编码 Agent",
    )
    parser.add_argument("prompt", nargs="*", help="单次查询；留空进入交互模式")
    parser.add_argument("--cwd", metavar="DIR", help="工作区目录（默认当前目录）")
    parser.add_argument(
        "--remote", metavar="URL", nargs="?", const="", default=None,
        help="改用远程后端（默认本地内嵌运行，不需要起服务）",
    )
    parser.add_argument(
        "--approval", choices=["auto", "gated", "strict", "readonly"],
        help="工具审批策略，默认 gated（写文件与执行命令前询问）",
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="等价于 --approval auto，跳过所有确认（仅限沙箱/CI）")
    return parser.parse_known_args(argv)


async def async_main() -> None:
    args, _unknown = _parse_args(sys.argv[1:])

    # 远程模式：老的 HTTP 瘦客户端形态
    if args.remote is not None:
        session = Session()
        if args.remote:
            session.api_url = args.remote.rstrip("/")
        if args.prompt:
            await run_stream(session, " ".join(args.prompt))
        else:
            await repl(session)
        return

    # 本地模式（默认）：Agent 跑在本进程里，操作的是**你的**磁盘
    from selfagent_cli.local import bootstrap, setup_agent, shutdown_agent

    approval = "auto" if args.yes else args.approval
    # bootstrap 必须在任何 app.* 导入之前调用（get_settings 带 lru_cache）
    bootstrap(args.cwd, approval_mode=approval)

    try:
        info = await setup_agent()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]初始化失败：{e}[/]")
        return

    try:
        from selfagent_cli.localrepl import run_local_once, run_local_repl

        if args.prompt:
            await run_local_once(" ".join(args.prompt), info)
        else:
            await run_local_repl(info)
    finally:
        await shutdown_agent()


def main() -> None:
    """入口点（被 console_script 调用）。"""
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(async_main())


if __name__ == "__main__":
    main()
