"""
文件工具集
==========
编码 Agent 的基本功：看得见、找得到、改得动项目里的文件。

所有路径都经过 Workspace.resolve() 禁闭在工作区内——模型会产出
`../../etc/passwd` 这类路径，这道校验是唯一的防线，不能省。

风险分级（决定要不要弹审批，见 app/agent/registry.ToolRisk）：
    read_file / list_dir / glob_files / grep_files   → READ  只读
    write_file / edit_file / delete_file             → WRITE 改工作区
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.workspace import WorkspaceError, get_workspace

logger = get_logger(__name__)

# 遍历类工具的结果条数上限，防止在大仓库里刷屏并撑爆上下文
_MAX_ENTRIES = 200
_MAX_GREP_HITS = 100


def _err(msg: str) -> str:
    """工具错误统一返回字符串而不是抛异常——交回模型让它自己纠正。"""
    return f"错误：{msg}"


def _read_text(path: Path, limit: int) -> str:
    data = path.read_bytes()
    truncated = len(data) > limit
    if truncated:
        data = data[:limit]
    text = data.decode("utf-8", errors="replace")
    if truncated:
        text += f"\n\n...[文件超过 {limit} 字节，已截断]"
    return text


# ==================== 只读 ====================


@tool
async def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """读取工作区内某个文本文件的内容，带行号。

    Args:
        path: 相对工作区根目录的文件路径，例如 "app/main.py"
        start_line: 起始行号（从 1 开始），默认 1
        end_line: 结束行号（含）。0 表示读到文件末尾
    """
    ws = get_workspace()
    try:
        target = ws.resolve(path)
    except WorkspaceError as e:
        return _err(str(e))

    if ws.is_sensitive(target):
        return _err(f"拒绝读取敏感文件：{ws.relative(target)}（密钥类文件不允许进入上下文）")
    if not target.exists():
        return _err(f"文件不存在：{path}")
    if target.is_dir():
        return _err(f"这是目录不是文件：{path}（用 list_dir）")

    limit = get_settings().file_read_max_bytes
    try:
        text = await asyncio.to_thread(_read_text, target, limit)
    except OSError as e:
        return _err(f"读取失败：{e}")

    lines = text.splitlines()
    start = max(1, start_line)
    end = len(lines) if end_line <= 0 else min(end_line, len(lines))
    if start > len(lines):
        return _err(f"起始行 {start} 超出文件总行数 {len(lines)}")

    width = len(str(end))
    body = "\n".join(f"{i:>{width}}| {lines[i - 1]}" for i in range(start, end + 1))
    header = f"{ws.relative(target)}（第 {start}-{end} 行，共 {len(lines)} 行）"
    return f"{header}\n{body}"


@tool
async def list_dir(path: str = ".") -> str:
    """列出工作区内某个目录的内容（已自动跳过 .git/node_modules 等）。

    Args:
        path: 相对工作区根目录的目录路径，默认为根目录
    """
    ws = get_workspace()
    try:
        target = ws.resolve(path)
    except WorkspaceError as e:
        return _err(str(e))
    if not target.is_dir():
        return _err(f"不是目录：{path}")

    def _scan() -> list[str]:
        out = []
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if ws.is_ignored(entry):
                continue
            if entry.is_dir():
                out.append(f"{ws.relative(entry)}/")
            else:
                out.append(f"{ws.relative(entry)}  ({entry.stat().st_size} B)")
        return out

    try:
        entries = await asyncio.to_thread(_scan)
    except OSError as e:
        return _err(f"列目录失败：{e}")

    if not entries:
        return f"{ws.relative(target)}/ 是空目录（或内容全部被忽略）"
    shown = entries[:_MAX_ENTRIES]
    tail = "" if len(entries) <= _MAX_ENTRIES else f"\n...[共 {len(entries)} 项，只显示前 {_MAX_ENTRIES} 项]"
    return "\n".join(shown) + tail


@tool
async def glob_files(pattern: str) -> str:
    """按通配符查找文件路径，例如 "**/*.py"、"app/**/test_*.py"。

    Args:
        pattern: glob 模式，相对工作区根目录
    """
    ws = get_workspace()

    def _scan() -> list[str]:
        out = []
        for p in ws.root.glob(pattern):
            if p.is_file() and not ws.is_ignored(p):
                out.append(ws.relative(p))
        return sorted(out)

    try:
        hits = await asyncio.to_thread(_scan)
    except (OSError, ValueError) as e:
        return _err(f"模式无效或查找失败：{e}")

    if not hits:
        return f"没有匹配 {pattern} 的文件"
    shown = hits[:_MAX_ENTRIES]
    tail = "" if len(hits) <= _MAX_ENTRIES else f"\n...[共 {len(hits)} 个，只显示前 {_MAX_ENTRIES} 个]"
    return "\n".join(shown) + tail


@tool
async def grep_files(query: str, file_pattern: str = "**/*", ignore_case: bool = True) -> str:
    """在工作区文件里按字面量搜索内容，返回 文件:行号: 内容。

    Args:
        query: 要搜索的字面量文本（不是正则）
        file_pattern: 限定搜索范围的 glob，默认全部文件
        ignore_case: 是否忽略大小写，默认是
    """
    if not query:
        return _err("搜索内容不能为空")
    ws = get_workspace()
    needle = query.lower() if ignore_case else query

    def _scan() -> list[str]:
        hits: list[str] = []
        for p in ws.root.glob(file_pattern):
            if len(hits) >= _MAX_GREP_HITS:
                break
            if not p.is_file() or ws.is_ignored(p) or ws.is_sensitive(p):
                continue
            try:
                # 二进制文件直接跳过：errors="ignore" 后内容没有意义
                raw = p.read_bytes()
                if b"\x00" in raw[:8000]:
                    continue
                text = raw.decode("utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                haystack = line.lower() if ignore_case else line
                if needle in haystack:
                    hits.append(f"{ws.relative(p)}:{i}: {line.strip()[:200]}")
                    if len(hits) >= _MAX_GREP_HITS:
                        break
        return hits

    hits = await asyncio.to_thread(_scan)
    if not hits:
        return f"没有找到包含 {query!r} 的内容（范围 {file_pattern}）"
    tail = f"\n...[已达上限 {_MAX_GREP_HITS} 条]" if len(hits) >= _MAX_GREP_HITS else ""
    return "\n".join(hits) + tail


# ==================== 写操作 ====================


@tool
async def write_file(path: str, content: str) -> str:
    """写入文件（覆盖已有内容，不存在则创建，父目录自动创建）。

    Args:
        path: 相对工作区根目录的文件路径
        content: 要写入的完整文本内容
    """
    ws = get_workspace()
    try:
        target = ws.resolve(path)
    except WorkspaceError as e:
        return _err(str(e))
    if target.is_dir():
        return _err(f"目标是目录：{path}")

    existed = target.exists()

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    try:
        await asyncio.to_thread(_write)
    except OSError as e:
        return _err(f"写入失败：{e}")

    action = "已覆盖" if existed else "已创建"
    logger.info("write_file %s %s（%d 字符）", action, ws.relative(target), len(content))
    return f"{action} {ws.relative(target)}（{len(content)} 字符，{content.count(chr(10)) + 1} 行）"


@tool
async def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """把文件里的一段文本替换成另一段（精确匹配）。

    比 write_file 更适合改动已有文件：不需要重写整个文件，
    也不会因为模型记错其余内容而误删。

    Args:
        path: 相对工作区根目录的文件路径
        old_text: 要被替换的原文（必须与文件内容精确一致，含缩进）
        new_text: 替换成的新文本
        replace_all: 为 true 时替换全部出现，否则要求 old_text 唯一
    """
    ws = get_workspace()
    try:
        target = ws.resolve(path)
    except WorkspaceError as e:
        return _err(str(e))
    if not target.is_file():
        return _err(f"文件不存在：{path}")
    if old_text == new_text:
        return _err("old_text 与 new_text 相同，无需替换")

    try:
        original = await asyncio.to_thread(target.read_text, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return _err(f"读取失败：{e}")

    count = original.count(old_text)
    if count == 0:
        return _err(f"在 {path} 中找不到要替换的文本（注意缩进与空白必须完全一致）")
    if count > 1 and not replace_all:
        # 不猜测该改哪一处——让模型自己补足上下文使其唯一，或显式要求全替
        return _err(
            f"要替换的文本在 {path} 中出现了 {count} 次。"
            f"请补充上下文让它唯一，或传 replace_all=true 全部替换"
        )

    updated = original.replace(old_text, new_text) if replace_all else original.replace(old_text, new_text, 1)
    try:
        await asyncio.to_thread(target.write_text, updated, encoding="utf-8")
    except OSError as e:
        return _err(f"写入失败：{e}")

    replaced = count if replace_all else 1
    logger.info("edit_file %s（替换 %d 处）", ws.relative(target), replaced)
    return f"已修改 {ws.relative(target)}（替换 {replaced} 处）"


@tool
async def delete_file(path: str) -> str:
    """删除工作区内的一个文件（不能删目录）。

    Args:
        path: 相对工作区根目录的文件路径
    """
    ws = get_workspace()
    try:
        target = ws.resolve(path)
    except WorkspaceError as e:
        return _err(str(e))
    if target == ws.root:
        return _err("拒绝删除工作区根目录")
    if not target.exists():
        return _err(f"文件不存在：{path}")
    if target.is_dir():
        # 递归删目录风险太高，且模型很容易把 "." 当成要清理的目标
        return _err(f"拒绝删除目录：{path}（本工具只删单个文件）")

    try:
        await asyncio.to_thread(os.remove, target)
    except OSError as e:
        return _err(f"删除失败：{e}")
    logger.info("delete_file %s", ws.relative(target))
    return f"已删除 {ws.relative(target)}"


# 按风险分组导出：注册时显式传 risk，比把等级藏在 metadata 里更直白，
# 也不依赖 @tool 装饰器的参数（不同 langchain-core 版本不一致）。
READ_TOOLS = [read_file, list_dir, glob_files, grep_files]
WRITE_TOOLS = [write_file, edit_file, delete_file]
FILE_TOOLS = READ_TOOLS + WRITE_TOOLS
