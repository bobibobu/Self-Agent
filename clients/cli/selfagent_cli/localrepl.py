"""
本地模式的交互循环
==================
与远程模式的区别只在「事件从哪来」：这里直接 async for 内嵌的
stream_agent，而不是走 HTTP。审批环节因此可以真正闭环——
拿到 approval_required 就地问用户，再用 resume_agent 把决策送回图里。
"""

from __future__ import annotations

import time
import uuid

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from selfagent_cli.render import render_approval, render_event

console = Console()


class LocalSession:
    """本地会话状态。"""

    def __init__(self, info: dict) -> None:
        self.info = info
        self.thread_id = f"local-{uuid.uuid4().hex[:12]}"
        # 用户选了"总是允许"的工具，本次进程内不再询问
        self.always_allow: set[str] = set()

    def reset(self) -> None:
        self.thread_id = f"local-{uuid.uuid4().hex[:12]}"


def _banner(info: dict) -> None:
    tools = info["tools"]
    by_risk = {}
    for name, risk in tools.items():
        by_risk.setdefault(risk, []).append(name)

    console.print(Panel(
        f"[bold]工作区[/]   {info['workspace']}\n"
        f"[bold]模型[/]     {info['provider']}\n"
        f"[bold]沙箱[/]     {info['sandbox']}\n"
        f"[bold]审批[/]     {info['approval_mode']}"
        f"{'  [dim](写与执行前会询问)[/]' if info['approval_mode'] == 'gated' else ''}\n"
        f"[bold]工具[/]     "
        f"[green]{len(by_risk.get('read', []))} 只读[/] · "
        f"[yellow]{len(by_risk.get('write', []))} 写[/] · "
        f"[red]{len(by_risk.get('exec', []))} 执行[/]\n"
        f"[bold]状态[/]     {info['storage']}",
        title="🤖 Self-Agent（本地模式）", border_style="cyan", expand=False,
    ))
    console.print("[dim]/help 查看命令 · /exit 退出[/]\n")


async def _drive(session: LocalSession, message: str) -> None:
    """跑一轮对话，处理其中可能出现的多次审批中断。"""
    from app.agent.graph import resume_agent, stream_agent

    text = Text("")
    started = time.time()
    pending = None   # 待处理的审批请求

    async def consume(stream) -> dict | None:
        """消费事件流，返回其中的审批请求（若有）。

        **必须把流消费完，不能拿到 approval_required 就 break。**
        LangGraph 要等 astream 自然结束才会把中断状态写进 checkpointer；
        提前中止会让后续的 resume 找不到可恢复的中断——
        表现为"点了同意但什么也没发生"（实测过，见 git 历史）。
        """
        nonlocal text
        approval = None
        with Live(text, console=console, refresh_per_second=20,
                  vertical_overflow="visible") as live:
            async for event in stream:
                etype = event.get("type")
                if etype == "token":
                    text.append(event.get("text", ""))
                    live.update(text)
                elif etype == "approval_required":
                    approval = event   # 记下来，但继续把流走完
                elif etype == "done":
                    if event.get("reply") and not str(text):
                        text.append(event["reply"])
                        live.update(text)
                else:
                    live.stop()
                    render_event(event, {})
                    live.start()
        return approval

    pending = await consume(stream_agent(message, session.thread_id))

    # 可能连续多次中断（一轮里调多个需审批的工具）
    while pending is not None:
        tool = pending.get("tool", "?")
        if tool in session.always_allow:
            decision = {"approved": True, "reason": "本次会话已授权"}
            console.print(f"[dim]  ✓ {tool}（本次会话已授权）[/]")
        else:
            choice = render_approval(pending)
            if choice == "always":
                session.always_allow.add(tool)
                decision = {"approved": True, "reason": "用户授权本次会话内总是允许"}
            elif choice == "approve":
                decision = {"approved": True, "reason": ""}
            else:
                decision = {"approved": False, "reason": "用户拒绝"}

        pending = await consume(resume_agent(session.thread_id, decision))

    body = str(text).strip()
    if body:
        console.print()
        try:
            console.print(Markdown(body))
        except Exception:  # noqa: BLE001
            console.print(body)
    console.print(f"[dim]({time.time() - started:.1f}s)[/]")


async def run_local_once(message: str, info: dict) -> None:
    session = LocalSession(info)
    await _drive(session, message)


async def run_local_repl(info: dict) -> None:
    session = LocalSession(info)
    _banner(info)

    while True:
        try:
            from selfagent_cli.main import read_input

            user_input = read_input().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！👋[/]")
            return

        if not user_input:
            continue

        if user_input.startswith("/"):
            if not await _handle_local_command(session, user_input[1:]):
                return
            continue

        console.print()
        try:
            await _drive(session, user_input)
        except KeyboardInterrupt:
            console.print("\n[yellow]已中断[/]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]⚠️ 出错：{e}[/]")
        console.print()


async def _handle_local_command(session: LocalSession, raw: str) -> bool:
    """返回 False 表示退出。"""
    parts = raw.split()
    cmd = parts[0] if parts else ""

    if cmd in ("exit", "quit", "q"):
        console.print("[dim]再见！👋[/]")
        return False
    if cmd == "help":
        console.print(Panel(
            "  /new       开始新对话（清空上下文）\n"
            "  /tools     列出可用工具与风险等级\n"
            "  /info      显示工作区 / 沙箱 / 审批状态\n"
            "  /trust     查看本次会话已授权免问的工具\n"
            "  /help /exit",
            title="命令", border_style="cyan", expand=False,
        ))
    elif cmd == "new":
        session.reset()
        console.print(f"[green]✓ 新对话：{session.thread_id}[/]")
    elif cmd == "tools":
        for name, risk in sorted(session.info["tools"].items(), key=lambda kv: (kv[1], kv[0])):
            color = {"read": "green", "write": "yellow", "exec": "red"}.get(risk, "white")
            console.print(f"  [{color}]{risk:<6}[/] {name}")
    elif cmd == "info":
        _banner(session.info)
    elif cmd == "trust":
        if session.always_allow:
            console.print("本次会话免问的工具：" + "、".join(sorted(session.always_allow)))
        else:
            console.print("[dim]暂无（每次写/执行都会询问）[/]")
    else:
        console.print(f"[red]未知命令：/{cmd}[/]")
    return True
