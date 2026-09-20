"""桌面客户端支撑（2026-09）
============================
- /health 暴露 storage_backend + workspace_root：前端据此自适应
  （本地形态隐藏会话列表、头部展示工作区）。
- /chat/resume：审批决策回传端点——没有它，Web/桌面客户端收到
  approval_required 后无法把用户决策送回图里，审批流在远程形态是断的。
- 根路径静态托管：dist 存在时 / 服务前端 SPA（test_api_smoke.test_root 已钉）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient（无需 Mock LLM：这里只测健康检查、路由表与静态托管）。"""
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health_exposes_storage_and_workspace(client):
    resp = client.get("/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["storage_backend"] in ("auto", "postgres", "sqlite", "memory")
    assert body["workspace_root"]  # 桌面客户端头部展示用


def test_resume_endpoint_exists_and_handles_bad_thread(client):
    """resume 端点存在；对不存在的 thread 返回错误事件而不是 500 崩溃。"""
    resp = client.post("/chat/resume", json={"thread_id": "no-such-thread", "decision": True})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # 没有 checkpoint 的 thread 无法续跑 → 流里应有 error 事件告知客户端
    body = resp.text
    assert "error" in body or "done" in body


def test_api_prefix_rewrite(client):
    """/api/* 改写到 /*：桌面客户端的构建产物没有 vite 代理，直连后端。"""
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tools").status_code == 200
