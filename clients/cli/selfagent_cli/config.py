"""CLI 配置：后端地址、用户/会话 ID。"""

from __future__ import annotations

import os


def get_api_url() -> str:
    """获取后端 API 地址（环境变量 AGENT_API_URL 或默认本地）。"""
    return os.environ.get("AGENT_API_URL", "http://localhost:8000").rstrip("/")


class Session:
    """当前 CLI 会话状态。"""

    def __init__(self) -> None:
        self.user_id: str = "cli-user"
        self.thread_id: str = "cli-" + str(os.getpid())
        self.api_url: str = get_api_url()

    def reset_thread(self) -> None:
        """重置会话 ID（开始新对话）。"""
        import time

        self.thread_id = "cli-" + str(int(time.time()))
