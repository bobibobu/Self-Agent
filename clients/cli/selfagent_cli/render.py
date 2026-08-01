"""
CLI 事件渲染与审批交互
======================
把 Agent 的事件流渲染成终端界面，并在遇到 approval_required 时
停下来问用户——这是审批闸门真正发挥作用的地方。

审批的界面设计原则：**让人能在一秒内看清"它要干什么"**。
所以危险等级、工具名、关键参数（命令原文 / 文件路径）都直接摊开显示，
而不是丢一个 JSON 让人自己读。
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()

_RISK_STYLE = {
    "read": ("green", "只读"),
    "write": ("yellow", "修改文件"),
    "exec": ("red", "执行命令"),
}


def render_approval(payload: dict) -> str:
    """展示审批请求并读取用户决策。

    返回 "approve" / "deny" / "always"（本次会话内该工具后续免问）。
    """
    tool = payload.get("tool", "?")
    risk = payload.get("risk", "exec")
    args = payload.get("args") or {}
    color, risk_label = _RISK_STYLE.get(risk, ("red", risk))

    body = Text()
    body.append(f"工具：{tool}\n", style="bold")
    body.append(f"风险：{risk_label}\n", style=color)

    # 命令与文件路径单独高亮——这是用户判断"要不要同意"的主要依据
    if tool == "run_command":
        body.append("\n将执行：\n", style="dim")
        console.print(Panel(
            body, title=f"[{color}]需要你的确认[/]", border_style=color, expand=False,
        ))
        console.print(Syntax(str(args.get("command", "")), "bash", theme="ansi_dark",
                             word_wrap=True, background_color="default"))
        cwd = args.get("cwd")
        if cwd and cwd != ".":
            console.print(f"[dim]工作目录：{cwd}[/]")
    else:
        for key in ("path", "old_text", "new_text", "content"):
            if key in args:
                val = str(args[key])
                shown = val if len(val) <= 300 else val[:300] + f" …（共 {len(val)} 字符）"
                body.append(f"\n{key}:\n", style="dim")
                body.append(shown + "\n")
        console.print(Panel(
            body, title=f"[{color}]需要你的确认[/]", border_style=color, expand=False,
        ))

    return _ask()


def _ask() -> str:
    """读取决策。默认（直接回车）是**拒绝**——安全选项必须是默认值。"""
    while True:
        try:
            answer = console.input(
                "[bold]允许吗？[/] [dim](y=允许 / n=拒绝 / a=本次会话总是允许该工具)"
                " [默认 n][/] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]已拒绝[/]")
            return "deny"
        if answer in ("", "n", "no", "拒绝"):
            return "deny"
        if answer in ("y", "yes", "允许"):
            return "approve"
        if answer in ("a", "always", "总是"):
            return "always"
        console.print("[yellow]请输入 y / n / a[/]")


_PLAN_STYLE = {"completed": ("✔", "green"), "in_progress": ("▶", "cyan"), "pending": ("○", "dim")}


def render_plan(plan: list[dict]) -> None:
    """把任务计划渲染成面板。长任务里这是用户唯一能看清「它打算干什么」的地方。"""
    if not plan:
        return
    body = Text()
    for step in plan:
        icon, style = _PLAN_STYLE.get(step.get("status", "pending"), ("○", "dim"))
        body.append(f"{icon} ", style=style)
        body.append(step.get("content", "") + "\n",
                    style="dim strike" if step.get("status") == "completed" else style)
    done = sum(1 for s in plan if s.get("status") == "completed")
    console.print(Panel(
        body, title=f"任务计划 {done}/{len(plan)}", border_style="blue", expand=False,
    ))


def render_event(event: dict, state: dict) -> None:
    """渲染一个非 token 事件。token 由调用方用 Live 增量渲染。"""
    etype = event.get("type")

    if etype == "plan_updated":
        render_plan(event.get("plan") or [])
    elif etype == "tool_calls":
        names = ", ".join(c.get("name", "?") for c in event.get("calls", []))
        console.print(f"[dim]🔧 决定调用：{names}[/]")
    elif etype == "tool_start":
        console.print(f"[dim]  ⏳ {event.get('name')}…[/]")
    elif etype == "tool_result":
        content = (event.get("content") or "").strip().splitlines()
        head = content[0][:100] if content else "(无输出)"
        more = f" [dim]…共 {len(content)} 行[/]" if len(content) > 1 else ""
        console.print(f"[dim]  ✓ {event.get('name')}:[/] {head}{more}")
    elif etype == "tool_denied":
        console.print(f"[yellow]  ⛔ {event.get('name')} 已拒绝：{event.get('reason', '')}[/]")
    elif etype == "error":
        console.print(f"[red]⚠️ {event.get('message')}[/]")
    elif etype == "cancelled":
        console.print("[yellow]已中断[/]")
