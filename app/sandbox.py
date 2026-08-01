"""
命令沙箱
========
审批闸门解决的是「模型想干什么，用户知不知情」；沙箱解决的是
「用户点了同意之后，这条命令最多能造成多大破坏」。两者不能互相替代：

    审批通过的 `pytest` 也可能因为项目里有个恶意 conftest.py
    而读走 ~/.ssh/id_rsa 并 POST 出去 —— 用户点同意时想的是"跑个测试"。

所以真正的边界必须在执行层。这一层把命令限制在：
    可写：工作区、/tmp
    只读：系统目录（/usr /etc 等，工具链需要）
    不可见：$HOME（连同 ~/.ssh ~/.aws ~/.config/gh 里的所有凭据）
    网络：默认切断

后端分层，按可用性自动降级：

    bwrap     bubblewrap，namespace 隔离，文件系统 + 网络 + PID 全覆盖。首选。
    landlock  内核原生 LSM（5.13+），只管文件系统，但不依赖外部二进制，
              且在禁用了非特权 user namespace 的机器上仍然可用。
    none      无隔离。**必须显式配置**，且启动时打 WARNING。

设计原则：**能力不足要说出来，不能假装有保护。** detect() 返回实际生效的
后端，run_command 的输出里会带上它，用户始终知道自己处在哪一层。
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from app.core.logging import get_logger

logger = get_logger(__name__)


class SandboxBackend(StrEnum):
    BWRAP = "bwrap"
    LANDLOCK = "landlock"
    NONE = "none"


# ---------------------------------------------------------------------------
# Landlock（内核 LSM）
# ---------------------------------------------------------------------------

# x86_64 / aarch64 的系统调用号一致
_NR_CREATE_RULESET = 444
_NR_ADD_RULE = 445
_NR_RESTRICT_SELF = 446

# 文件系统访问位（landlock_fs 权限，ABI v1 起）
_FS_EXECUTE = 1 << 0
_FS_WRITE_FILE = 1 << 1
_FS_READ_FILE = 1 << 2
_FS_READ_DIR = 1 << 3
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13
_FS_TRUNCATE = 1 << 14

_READ_ACCESS = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR
_WRITE_ACCESS = (
    _FS_WRITE_FILE | _FS_REMOVE_DIR | _FS_REMOVE_FILE | _FS_MAKE_CHAR
    | _FS_MAKE_DIR | _FS_MAKE_REG | _FS_MAKE_SOCK | _FS_MAKE_FIFO
    | _FS_MAKE_BLOCK | _FS_MAKE_SYM | _FS_TRUNCATE
)

# 只对目录有意义的权限位。给**非目录**（普通文件、字符设备如 /dev/null）
# 附带这些位，landlock_add_rule 会直接返回 EINVAL——
# 而 preexec_fn 里的异常会被 subprocess 吞成一句笼统的
# "Exception occurred in preexec_fn"，极难定位，所以必须在这里就掩掉。
_DIR_ONLY_ACCESS = (
    _FS_READ_DIR | _FS_REMOVE_DIR | _FS_REMOVE_FILE | _FS_MAKE_CHAR
    | _FS_MAKE_DIR | _FS_MAKE_REG | _FS_MAKE_SOCK | _FS_MAKE_FIFO
    | _FS_MAKE_BLOCK | _FS_MAKE_SYM | _FS_REFER
)

_LANDLOCK_RULE_PATH_BENEATH = 1


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def landlock_abi() -> int:
    """内核支持的 Landlock ABI 版本。<=0 表示不支持。"""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        return libc.syscall(_NR_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    except OSError:
        return -1


def _apply_landlock(read_paths: list[str], write_paths: list[str]) -> None:
    """在**当前进程**上施加 Landlock 限制。

    只能在 fork 之后、exec 之前调用（subprocess 的 preexec_fn），
    因为 Landlock 是不可撤销的：一旦施加，本进程及其所有后代永久受限。
    """
    abi = landlock_abi()
    if abi <= 0:
        raise OSError("内核不支持 Landlock")

    libc = ctypes.CDLL("libc.so.6", use_errno=True)

    # 高版本 ABI 引入的权限位，在低版本内核上必须去掉，否则 create_ruleset 报 EINVAL
    handled = _READ_ACCESS | _WRITE_ACCESS
    if abi < 2:
        handled &= ~_FS_REFER
    if abi < 3:
        handled &= ~_FS_TRUNCATE

    attr = _RulesetAttr(handled_access_fs=handled, handled_access_net=0)
    ruleset_fd = libc.syscall(
        _NR_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint32(0)
    )
    if ruleset_fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset 失败")

    try:
        for paths, access in ((read_paths, _READ_ACCESS), (write_paths, _READ_ACCESS | _WRITE_ACCESS)):
            for p in paths:
                if not os.path.exists(p):
                    continue
                fd = os.open(p, os.O_PATH | os.O_CLOEXEC)
                try:
                    allowed = access & handled
                    # 非目录要掩掉目录专属权限位，否则 EINVAL
                    if not os.path.isdir(p):
                        allowed &= ~_DIR_ONLY_ACCESS
                    if not allowed:
                        continue
                    rule = _PathBeneathAttr(allowed_access=allowed, parent_fd=fd)
                    rc = libc.syscall(
                        _NR_ADD_RULE, ctypes.c_int(ruleset_fd),
                        ctypes.c_uint32(_LANDLOCK_RULE_PATH_BENEATH),
                        ctypes.byref(rule), ctypes.c_uint32(0),
                    )
                    if rc < 0:
                        raise OSError(ctypes.get_errno(), f"landlock_add_rule 失败：{p}")
                finally:
                    os.close(fd)

        # 必须先 no_new_privs，否则 restrict_self 会被拒绝
        PR_SET_NO_NEW_PRIVS = 38
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(NO_NEW_PRIVS) 失败")

        if libc.syscall(_NR_RESTRICT_SELF, ctypes.c_int(ruleset_fd), ctypes.c_uint32(0)) < 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self 失败")
    finally:
        os.close(ruleset_fd)


# ---------------------------------------------------------------------------
# 后端选择
# ---------------------------------------------------------------------------

# 工具链需要读的系统目录
_SYSTEM_READ_PATHS = ["/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt", "/var/lib"]


@lru_cache
def _bwrap_available() -> bool:
    """bwrap 是否真的可用。

    有二进制不等于能用——容器里、或禁用了非特权 user namespace 的机器上
    会直接失败。所以实跑一次最小命令来确认，结果缓存（进程内不会变）。
    """
    if shutil.which("bwrap") is None:
        return False
    try:
        r = subprocess.run(
            ["bwrap", "--ro-bind", "/usr", "/usr", "--dev", "/dev", "true"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache
def _landlock_available() -> bool:
    """Landlock 是否真的能用。

    只看 ABI 版本号不够——具体的 ruleset 可能因为权限位组合、路径类型
    等原因被内核拒绝，而这个错误发生在 preexec_fn 里，
    会被 subprocess 吞成一句笼统的 "Exception occurred in preexec_fn"。
    所以在子进程里真跑一次，失败就干脆降级，别让每条命令都炸。

    必须 fork：Landlock 不可撤销，在当前进程试等于把整个应用锁死。
    """
    if landlock_abi() <= 0:
        return False
    try:
        pid = os.fork()
    except OSError:
        return False
    if pid == 0:  # 子进程
        try:
            _apply_landlock(
                [p for p in _SYSTEM_READ_PATHS if os.path.exists(p)],
                [_private_tmp(), "/dev/null"],
            )
            os._exit(0)
        except Exception:  # noqa: BLE001
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    ok = os.waitstatus_to_exitcode(status) == 0
    if not ok:
        logger.warning("Landlock 自检失败，将降级（内核 ABI 报告为 v%d）", landlock_abi())
    return ok


def detect_backend(preferred: str = "auto") -> SandboxBackend:
    """决定实际生效的沙箱后端。

    显式指定但不可用时**降级并告警**，而不是静默失败或直接崩溃——
    但绝不会在用户以为有沙箱时假装有。
    """
    if preferred == "none":
        return SandboxBackend.NONE

    if preferred in ("auto", "bwrap") and _bwrap_available():
        return SandboxBackend.BWRAP
    if preferred == "bwrap":
        logger.warning("指定了 bwrap 沙箱但不可用（缺二进制或非特权 user namespace 被禁），尝试降级")

    if preferred in ("auto", "bwrap", "landlock") and _landlock_available():
        return SandboxBackend.LANDLOCK
    if preferred == "landlock":
        logger.warning("指定了 landlock 沙箱但不可用，降级为无隔离")

    return SandboxBackend.NONE


def describe() -> str:
    """当前沙箱能力的可读描述（供启动日志与 /health 展示）。"""
    from app.core.config import get_settings

    s = get_settings()
    if not s.sandbox_enabled:
        return "已禁用（SANDBOX_ENABLED=false）"
    backend = detect_backend(s.sandbox_backend)
    if backend is SandboxBackend.BWRAP:
        net = "允许联网" if s.sandbox_allow_network else "切断网络"
        return f"bubblewrap（文件系统隔离 + {net}）"
    if backend is SandboxBackend.LANDLOCK:
        return f"Landlock ABI v{landlock_abi()}（仅文件系统隔离，**不限制网络**）"
    return "无隔离（未检测到可用后端）"


# ---------------------------------------------------------------------------
# 构造受限执行
# ---------------------------------------------------------------------------


@lru_cache
def _private_tmp() -> str:
    """本进程专属的临时目录。

    不能把整个 /tmp 授予写权限：那样沙箱里的命令就能读到别人（甚至用户自己）
    放在 /tmp 下的东西，而 /tmp 恰恰是各类凭据缓存的常见落点。
    给一个私有目录并把 TMPDIR 指过去，工具链照常工作，暴露面小得多。
    """
    import tempfile

    path = Path(tempfile.gettempdir()) / f"selfagent-sbx-{os.getpid()}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return str(path)


class SandboxedCommand(NamedTuple):
    argv: list[str]
    preexec: object | None
    env: dict[str, str]
    backend: SandboxBackend


def wrap_command(
    argv: list[str], *, workspace: Path, cwd: Path, allow_network: bool,
) -> SandboxedCommand:
    """把 argv 包装成受沙箱限制的形式。"""
    from app.core.config import get_settings

    s = get_settings()
    if not s.sandbox_enabled:
        return SandboxedCommand(argv, None, {}, SandboxBackend.NONE)

    backend = detect_backend(s.sandbox_backend)
    tmp = _private_tmp()
    tmp_env = {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp}

    if backend is SandboxBackend.BWRAP:
        # bwrap 用私有 tmpfs 挂 /tmp，天然隔离，不必改 TMPDIR
        return SandboxedCommand(
            _bwrap_argv(argv, workspace, cwd, allow_network), None, {}, backend,
        )

    if backend is SandboxBackend.LANDLOCK:
        read_paths = [p for p in _SYSTEM_READ_PATHS if os.path.exists(p)]
        # 可写范围：工作区 + 私有临时目录 + 几个必需的字符设备
        write_paths = [str(workspace), tmp, "/dev/null", "/dev/zero", "/dev/urandom"]

        def _preexec() -> None:  # 在子进程 fork 后、exec 前执行
            _apply_landlock(read_paths, write_paths)

        return SandboxedCommand(argv, _preexec, tmp_env, backend)

    return SandboxedCommand(argv, None, {}, SandboxBackend.NONE)


def _bwrap_argv(argv: list[str], workspace: Path, cwd: Path, allow_network: bool) -> list[str]:
    """构造 bubblewrap 命令行。

    关键点：**不挂载 $HOME**。~/.ssh、~/.aws、~/.config/gh 里的凭据
    因此在沙箱里根本不存在——这正是"审批通过的 pytest 偷走 SSH key"
    这条攻击路径要堵的地方。git 等工具需要 HOME，给个 tmpfs 空目录。
    """
    cmd = [
        "bwrap",
        "--die-with-parent",   # 父进程没了子进程跟着死，不留孤儿
        "--new-session",       # 独立 session，防 TIOCSTI 注入宿主终端
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]

    if not allow_network:
        cmd.append("--unshare-net")

    # 系统目录只读。/bin /lib 在现代发行版上多是指向 usr/ 的符号链接，
    # 对符号链接做 bind 会失败，要按实际类型分别处理。
    for path in _SYSTEM_READ_PATHS:
        p = Path(path)
        if not p.exists():
            continue
        if p.is_symlink():
            cmd += ["--symlink", os.readlink(path), path]
        else:
            cmd += ["--ro-bind", path, path]

    # 工作区可写——这是沙箱**故意**留的口子：Agent 就是来改这个目录的。
    # 破坏半径因此被收敛到工作区内，而不是整台机器。
    cmd += ["--bind", str(workspace), str(workspace)]
    # 空的 HOME：满足 git/npm 等对 $HOME 的依赖，但不暴露真实家目录
    cmd += ["--tmpfs", "/root", "--setenv", "HOME", "/tmp"]
    cmd += ["--chdir", str(cwd)]
    cmd += ["--"]
    return cmd + argv
