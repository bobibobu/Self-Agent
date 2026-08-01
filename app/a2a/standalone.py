"""
A2A 独立 Server 启动入口
------------------------
把本 Agent 作为独立的 A2A server 运行（独立进程/端口）。

用法：
    python -m app.a2a.standalone --port 8001

这样其他 Agent（或本 Agent 自己的 delegate_to_agent 工具）
就能通过 A2A 协议与它交互。
"""

from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI

from app.a2a.server import mount_a2a
from app.core.logging import setup_logging


def create_a2a_app(base_url: str) -> FastAPI:
    """创建只含 A2A 路由的精简 FastAPI app。"""
    setup_logging()
    app = FastAPI(title="Self-Agent A2A Server", version="0.1.0")
    mount_a2a(app, base_url=base_url)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "self-agent-a2a"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-Agent A2A Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    base_url = f"http://localhost:{args.port}"
    app = create_a2a_app(base_url)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
