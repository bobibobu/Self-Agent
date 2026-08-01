"""CLI 配置：后端地址、用户/会话 ID、登录凭据的本地持久化。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path


def get_api_url() -> str:
    """获取后端 API 地址（环境变量 AGENT_API_URL 或默认本地）。"""
    return os.environ.get("AGENT_API_URL", "http://localhost:8000").rstrip("/")


def _credentials_path() -> Path:
    """凭据文件路径（遵循 XDG）。"""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "selfagent" / "credentials.json"


def load_credentials() -> dict:
    """读取本地保存的 token。读不到返回空 dict。"""
    path = _credentials_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_credentials(token: str, user: dict) -> Path:
    """保存 token 到本地，权限设为 0600（仅本人可读）。"""
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"access_token": token, "user": user, "api_url": get_api_url()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # token 等同于密码，不能让同机其他用户读到
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def clear_credentials() -> None:
    """删除本地 token。"""
    path = _credentials_path()
    if path.exists():
        path.unlink()


class Session:
    """当前 CLI 会话状态。"""

    def __init__(self) -> None:
        self.api_url: str = get_api_url()
        self.thread_id: str = "cli-" + str(os.getpid())

        # 启动时尝试恢复上次登录（后端 AUTH_ENABLED=true 时必需）
        creds = load_credentials()
        self.token: str | None = creds.get("access_token")
        user = creds.get("user") or {}
        # 认证模式下身份以 token 为准；未登录时留一个占位 id 供匿名模式使用
        self.user_id: str = user.get("id") or "cli-user"
        self.username: str = user.get("username", "")

    @property
    def is_logged_in(self) -> bool:
        return bool(self.token)

    def set_auth(self, token: str, user: dict) -> None:
        self.token = token
        self.user_id = user.get("id") or self.user_id
        self.username = user.get("username", "")
        save_credentials(token, user)

    def logout(self) -> None:
        self.token = None
        self.username = ""
        self.user_id = "cli-user"
        clear_credentials()

    def reset_thread(self) -> None:
        """重置会话 ID（开始新对话）。"""
        import time

        self.thread_id = "cli-" + str(int(time.time()))
