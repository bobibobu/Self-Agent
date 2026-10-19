"""
Shell 执行工具
==============
编码 Agent 绕不开的一件事：跑测试、跑 lint、看 git 状态、装依赖。

这是全项目风险最高的工具，所以做了几件事：

1. **不经过 shell 解释器**——用 shlex 拆词 + subprocess 列表参数形式。
   `shell=True` 会让 `rm -rf / #` 这类拼接、`$(...)`、反引号、重定向全部生效，
   模型只要产出一个带 `;` 的字符串就能绕开任何命令白名单。
2. **工作目录禁闭在工作区内**，cwd 参数同样走 Workspace.resolve()。
3. **超时强制终止**，并且杀整个进程组——只 kill 父进程会留下孤儿子进程。
4. **输出截断**，避免一次 `find /` 把上下文撑爆。
5. 风险等级 EXEC，默认策略下执行前必须经用户审批（见 tools_node）。

6. **沙箱隔离**（app/sandbox.py）：可写范围收敛到工作区，隐藏 $HOME
   （连同 ~/.ssh ~/.aws 里的凭据），默认切断网络。

审批与沙箱是两层，不能互相替代：审批管「模型想干什么，用户知不知情」，
沙箱管「用户点了同意之后最多能造成多大破坏」——审批通过的 pytest
也可能因为项目里有个恶意 conftest.py 而读走 SSH key。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import signal
import subprocess

from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.sandbox import wrap_command
from app.workspace import WorkspaceError, get_workspace

logger = get_logger(__name__)

_MAX_OUTPUT_CHARS = 30_000

# 明确拒绝的命令：即便用户点了同意，这些也不放行。
# 不是完整的安全边界（真正的边界是沙箱），而是挡住模型最容易犯的几种致命错误。
_DENIED = {
    "shutdown", "reboot", "halt", "poweroff", "init",
    "mkfs", "fdisk", "dd", "sudo", "su", "chown", "chmod",
}


def _looks_destructive(argv: list[str]) -> str | None:
    """挡住几种典型的毁灭性调用。返回拒绝原因，None 表示放行。"""
    if not argv:
        return "空命令"
    exe = os.path.basename(argv[0])
    if exe in _DENIED:
        return f"命令 {exe} 在拒绝名单内"
    # rm -rf 指向工作区根或更上层
    if exe == "rm" and any(a.startswith("-") and "r" in a for a in argv[1:]):
        for a in argv[1:]:
            if a.startswith("-"):
                continue
            if a in ("/", "~", "*") or a.rstrip("/") in ("", ".", ".."):
                return f"拒绝递归删除 {a!r}"
    return None


@tool
async def run_command(command: str, cwd: str = ".") -> str:
    """在工作区内执行一条 shell 命令，返回退出码与输出。

    适合跑测试、lint、git 等。命令按 shell 词法拆分后直接执行，
    **不经过 shell 解释器**——管道 `|`、重定向 `>`、`&&`、`;` 都不会生效。
    需要组合命令时请分多次调用。

    Args:
        command: 要执行的命令，例如 "pytest tests/ -q" 或 "git status --short"
        cwd: 执行目录，相对工作区根目录，默认根目录
    """
    ws = get_workspace()
    s = get_settings()

    if not command or not command.strip():
        return "错误：命令不能为空"

    try:
        workdir = ws.resolve(cwd)
    except WorkspaceError as e:
        return f"错误：{e}"
    if not workdir.is_dir():
        return f"错误：执行目录不存在：{cwd}"

    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"错误：命令无法解析（引号不匹配？）：{e}"

    denied = _looks_destructive(argv)
    if denied:
        logger.warning("run_command 拒绝执行：%s（%s）", command, denied)
        return f"错误：拒绝执行此命令——{denied}"

    # 套沙箱：把可写范围收敛到工作区，隐藏 $HOME（~/.ssh、~/.aws 等凭据），
    # 默认切断网络。审批解决"用户知不知情"，沙箱解决"同意之后能造成多大破坏"。
    sbx = wrap_command(
        argv, workspace=ws.root, cwd=workdir, allow_network=s.sandbox_allow_network,
    )
    backend = sbx.backend
    # env 覆盖（主要是把 TMPDIR 指向沙箱私有临时目录）
    child_env = {**os.environ, **sbx.env} if sbx.env else None

    logger.info("run_command: %s（cwd=%s, sandbox=%s）", command, ws.relative(workdir), backend.value)
    try:
        proc = await asyncio.create_subprocess_exec(
            *sbx.argv,
            cwd=str(workdir),
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # 独立进程组：超时时能连子进程一起杀掉，
            # 只 kill 父进程会留下还在跑的孤儿（比如 npm 拉起的 node）
            start_new_session=True,
            preexec_fn=sbx.preexec,  # noqa: PLW1509 —— Landlock 必须在 fork 后 exec 前施加
        )
    except NotImplementedError:
        # Windows 的 SelectorEventLoop 不支持 asyncio 子进程。服务端在 Windows 上为了
        # 兼容 psycopg 必须用 Selector（见 app/core/eventloop.py），这里退到线程里同步跑。
        logger.info("run_command: 当前事件循环不支持 asyncio 子进程，改用线程执行 subprocess.run")
        return await _run_in_thread(command, argv[0], sbx, str(workdir), child_env, s.shell_timeout_seconds)
    except FileNotFoundError:
        return f"错误：找不到命令 {argv[0]!r}"
    except OSError as e:
        return f"错误：启动失败：{e}"

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=s.shell_timeout_seconds)
    except TimeoutError:
        _kill_process_group(proc)
        logger.warning("run_command 超时已终止：%s（>%.0fs）", command, s.shell_timeout_seconds)
        return f"错误：命令超时（超过 {s.shell_timeout_seconds:.0f} 秒），已终止"

    return _format_result(command, proc.returncode, stdout, backend.value)


async def _run_in_thread(command: str, program: str, sbx, cwd: str, env: dict | None, timeout: float) -> str:
    """同步 subprocess.run 放进线程执行（事件循环不支持 asyncio 子进程时的兜底）。

    超时时 subprocess.run 会 kill 子进程本身；Windows 没有进程组可杀，孤儿子进程无法一并清理。
    """
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            sbx.argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            start_new_session=True,
            preexec_fn=sbx.preexec,  # noqa: PLW1509
        )
    except subprocess.TimeoutExpired:
        logger.warning("run_command 超时已终止（线程模式）：%s（>%.0fs）", command, timeout)
        return f"错误：命令超时（超过 {timeout:.0f} 秒），已终止"
    except FileNotFoundError:
        return f"错误：找不到命令 {program!r}"
    except OSError as e:
        return f"错误：启动失败：{e}"
    return _format_result(command, r.returncode, r.stdout, sbx.backend.value)


def _format_result(command: str, returncode: int | None, stdout: bytes | None, backend: str) -> str:
    output = (stdout or b"").decode("utf-8", errors="replace")
    if len(output) > _MAX_OUTPUT_CHARS:
        omitted = len(output) - _MAX_OUTPUT_CHARS
        output = output[:_MAX_OUTPUT_CHARS] + f"\n...[输出过长，已截断 {omitted} 字符]"

    status = "成功" if returncode == 0 else f"失败（退出码 {returncode}）"
    logger.info("run_command 完成：%s → %s，输出 %d 字符", command, status, len(output))
    # 把生效的沙箱后端写进输出：用户和模型都该知道这条命令跑在哪一层保护下，
    # 「以为有沙箱其实没有」比「明确知道没有」危险得多
    tag = f" sandbox={backend}" if backend != "none" else " sandbox=none ⚠️"
    return f"$ {command}\n[{status}{tag}]\n{output or '(无输出)'}"


def _kill_process_group(proc) -> None:
    """杀掉整个进程组，先 TERM 后 KILL。"""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


SHELL_TOOLS = [run_command]
