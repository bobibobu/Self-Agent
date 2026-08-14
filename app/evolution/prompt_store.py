"""
提示词版本管理（Prompt Store）
------------------------------
管理系统提示词的版本历史，支持：
- 读取当前生效版本
- 写入新版本（Hermes 反思后优化）
- 列出历史版本
- 回滚到指定版本

存储：文件系统（data/prompts/ 下），简单可读、可 git 管理、易调试。
每个版本一个 JSON 文件，含版本号、内容、来源、时间戳、反思评分。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 提示词存储目录
_PROMPTS_DIR = Path("data/prompts")
_CURRENT_FILE = _PROMPTS_DIR / "current.json"


def _ensure_dir() -> None:
    _PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


# 当前提示词缓存：(st_mtime_ns, st_size) → content。
# get_current_prompt 在每次 /chat 都会被调用（构造系统提示），
# 不缓存的话每个请求都做一次同步磁盘读 + JSON 解析；
# 用 mtime+size 做校验，Hermes 写入新版本后下一次读取自动失效。
_current_prompt_cache: tuple[tuple[int, int], str] | None = None


def get_current_prompt() -> str:
    """获取当前生效的系统提示词。

    若无历史版本，返回内置默认提示词。
    """
    global _current_prompt_cache
    _ensure_dir()
    if _CURRENT_FILE.exists():
        try:
            st = _CURRENT_FILE.stat()
            stamp = (st.st_mtime_ns, st.st_size)
            if _current_prompt_cache is not None and _current_prompt_cache[0] == stamp:
                return _current_prompt_cache[1]
            data = json.loads(_CURRENT_FILE.read_text(encoding="utf-8"))
            content = data.get("content", "")
            _current_prompt_cache = (stamp, content)
            return content
        except Exception:  # noqa: BLE001
            logger.warning("当前提示词文件损坏，回退默认")
            _current_prompt_cache = None
    # 回退到内置默认
    from app.agent.prompts import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def get_current_version() -> str:
    """获取当前版本号。"""
    _ensure_dir()
    if _CURRENT_FILE.exists():
        try:
            data = json.loads(_CURRENT_FILE.read_text(encoding="utf-8"))
            return data.get("version", "unknown")
        except Exception:  # noqa: BLE001
            pass
    return "builtin"


def save_version(content: str, *, source: str = "hermes", score: float | None = None, note: str = "") -> str:
    """保存一个新版本并设为当前生效。

    Returns:
        新版本号（时间戳格式）
    """
    _ensure_dir()
    version = f"v{int(time.time())}"
    record = {
        "version": version,
        "content": content,
        "source": source,
        "score": score,
        "note": note,
        "timestamp": time.time(),
    }
    # 存版本历史
    history_file = _PROMPTS_DIR / f"{version}.json"
    history_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    # 更新当前指针
    _CURRENT_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("提示词新版本已保存：%s（来源=%s，评分=%s）", version, source, score)
    return version


def list_versions(limit: int = 20) -> list[dict[str, Any]]:
    """列出历史版本（按时间倒序）。"""
    _ensure_dir()
    versions = []
    for f in _PROMPTS_DIR.glob("v*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            versions.append({
                "version": data.get("version"),
                "source": data.get("source"),
                "score": data.get("score"),
                "note": data.get("note", ""),
                "timestamp": data.get("timestamp"),
            })
        except Exception:  # noqa: BLE001
            continue
    versions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return versions[:limit]


def rollback(version: str) -> bool:
    """回滚到指定版本。"""
    _ensure_dir()
    target = _PROMPTS_DIR / f"{version}.json"
    if not target.exists():
        logger.warning("回滚目标版本不存在：%s", version)
        return False
    data = json.loads(target.read_text(encoding="utf-8"))
    _CURRENT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("提示词已回滚到：%s", version)
    return True
