"""
工作区（Workspace）
===================
编码 Agent 的上下文单位是「一个项目目录」，不是 thread_id。
这一层负责回答三个问题：

    根目录在哪？          → Workspace.root
    这个路径能不能碰？    → resolve()，越界直接拒绝
    这个文件该不该看？    → is_ignored()，尊重 .gitignore

**路径禁闭是本模块最重要的职责。** LLM 会产出 `../../etc/passwd`、
`/etc/shadow`、以及指向工作区外的符号链接。工具层不做这道校验，
就等于把整台机器的读写权交给了模型输出。

实现要点：先 resolve() 再判断归属——resolve() 会展开 `..` 与符号链接，
所以「解析后仍在 root 之下」这一条同时挡住路径穿越和符号链接逃逸。
只做字符串前缀匹配是挡不住 symlink 的。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

# 永远不进入的目录：体积大、噪音多、或含敏感内容
_ALWAYS_IGNORE = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".tox",
    "dist", "build", ".next", ".nuxt", "target",
    ".idea", ".vscode", ".DS_Store",
}

# 永远不读的文件名/后缀：密钥类
_SENSITIVE_NAMES = {".env", ".env.local", "credentials.json", "id_rsa", "id_ed25519"}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


class WorkspaceError(AppError):
    """工作区相关错误（越界访问、目标不存在等）。"""

    def __init__(self, message: str):
        super().__init__(message, code="WORKSPACE_ERROR", status_code=400)


class Workspace:
    """一个受约束的项目目录。"""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkspaceError(f"工作区目录不存在：{self.root}")
        self._spec = self._load_gitignore()

    # ---------- 路径 ----------

    def resolve(self, path: str) -> Path:
        """把用户/模型给的路径解析成工作区内的绝对路径。越界抛错。

        接受相对路径（相对 root）与绝对路径（必须落在 root 内）。
        """
        if not path or not path.strip():
            raise WorkspaceError("路径不能为空")

        candidate = Path(path).expanduser()
        full = candidate if candidate.is_absolute() else self.root / candidate

        # resolve(strict=False)：允许目标尚不存在（写新文件的场景），
        # 但仍会展开 .. 与已存在部分的符号链接
        resolved = full.resolve()

        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise WorkspaceError(
                f"拒绝访问工作区外的路径：{path}（工作区根目录是 {self.root}）"
            )
        return resolved

    def relative(self, path: Path) -> str:
        """转成相对工作区的展示路径（不要把服务器绝对路径暴露给模型/用户）。"""
        try:
            return str(path.relative_to(self.root)) or "."
        except ValueError:
            return str(path)

    # ---------- 过滤 ----------

    def is_ignored(self, path: Path) -> bool:
        """是否应当忽略（.gitignore + 内置黑名单）。"""
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return True

        if any(part in _ALWAYS_IGNORE for part in rel.parts):
            return True
        return self._spec is not None and self._spec.match_file(str(rel))

    @staticmethod
    def is_sensitive(path: Path) -> bool:
        """是否是密钥类文件。

        单独于 gitignore 之外再挡一道：.env 通常已被 gitignore，
        但「被忽略」和「禁止读取」是两件事——前者影响遍历，
        后者要在 read_file 这种精确指名的场景也生效。
        """
        return path.name in _SENSITIVE_NAMES or path.suffix in _SENSITIVE_SUFFIXES

    def _load_gitignore(self):
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            return None
        try:
            import pathspec

            lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
            # pathspec 1.x 起 "gitwildmatch" 已弃用，改用 "gitignore"；
            # 老版本没有该 factory，回退到旧名字保持兼容
            try:
                return pathspec.PathSpec.from_lines("gitignore", lines)
            except (KeyError, ValueError):
                return pathspec.PathSpec.from_lines("gitwildmatch", lines)
        except Exception as e:  # noqa: BLE001
            logger.warning("解析 .gitignore 失败，仅使用内置忽略列表：%s", e)
            return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Workspace root={self.root}>"


# ---------------------------------------------------------------------------
# 当前工作区（进程级）
# ---------------------------------------------------------------------------


@lru_cache
def get_workspace() -> Workspace:
    """当前工作区单例。

    根目录取自 WORKSPACE_ROOT 配置，留空则用进程的当前目录——
    这正是 CLI 在项目里直接跑起来时期望的行为。
    """
    from app.core.config import get_settings

    root = get_settings().workspace_root or os.getcwd()
    ws = Workspace(root)
    logger.info("工作区：%s", ws.root)
    return ws


def set_workspace(root: str | os.PathLike) -> Workspace:
    """切换工作区（CLI 的 --cwd、或测试用）。"""
    get_workspace.cache_clear()
    from app.core.config import get_settings

    get_settings().workspace_root = str(Path(root).expanduser().resolve())
    return get_workspace()
