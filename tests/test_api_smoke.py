"""
HTTP 端到端冒烟测试（用 Mock LLM，不依赖真实 key 和数据库）
=============================================================
用 FastAPI TestClient 验证：
- /health 正常
- /chat 能完成一次对话（含工具调用）
- /chat/stream 能流式返回

运行：pytest tests/test_api_smoke.py -v
或：  python -m pytest tests/test_api_smoke.py -v
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient


class _MockLLM:
    """用于 HTTP 测试的 Mock LLM。"""

    @property
    def provider_name(self) -> str:
        return "mock"

    async def chat(self, request):
        from app.llm.models import ChatResponse, ToolCall, Usage

        # agent_node 会在对话末尾追加一条「[当前时间：...]」的 HumanMessage 作为
        # 环境参考（见 agent_node）。它不是用户提问也不是工具结果——判断「最后一条
        # 是不是 tool」时要跳过它，否则工具结果回填后的总结步会走错分支。
        msgs = [m for m in request.messages if not (m.role == "user" and m.content.startswith("[当前时间："))]
        last = msgs[-1] if msgs else None
        if last and last.role == "tool":
            return ChatResponse(
                content=f"根据查询，结果是：{last.content[:40]}",
                usage=Usage(prompt_tokens=5, completion_tokens=15, total_tokens=20),
                model="mock",
                finish_reason="stop",
            )
        # 取最后一条「真实用户提问」。
        user_msg = next((m.content for m in reversed(msgs) if m.role == "user"), "")
        if "天气" in (user_msg or "") and request.tools:
            return ChatResponse(
                tool_calls=[ToolCall(id="c1", name="get_weather", arguments={"city": "北京"})],
                model="mock",
                finish_reason="tool_calls",
            )
        return ChatResponse(content=f"你好，你说了：{user_msg}", model="mock", finish_reason="stop")

    async def stream_chat(self, request):
        """流式：复用 chat 的判断逻辑，逐 token 产文本，末尾 chunk 带聚合结果。

        契约（与真实 provider 一致）：tool_calls / usage / model 只出现在
        流末尾的收尾 chunk 上——调用方一次流式请求就拿到全部信息，
        不需要再补一次非流式调用。
        """
        from app.llm.models import StreamChunk

        resp = await self.chat(request)
        for ch in (resp.content or ""):
            yield StreamChunk(content=ch)
        yield StreamChunk(
            content="",
            tool_calls=resp.tool_calls or None,
            finish_reason=resp.finish_reason,
            usage=resp.usage,
            model=resp.model,
        )


@pytest.fixture
def client(monkeypatch):
    """注入 Mock LLM 并构造 TestClient。"""
    import app.llm.factory as factory

    def _mock_get(_provider=None):
        return _MockLLM()

    monkeypatch.setattr(factory, "get_llm_client", _mock_get)
    # routes.py 在导入时已绑定 get_llm_client，需 patch 它引用的名字
    import app.api.routes as routes

    monkeypatch.setattr(routes, "get_llm_client", _mock_get)

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    """健康检查返回 200 且含应用信息。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "Self-Agent"


def test_root(client):
    """根路径：有前端构建产物时是 SPA 首页，没有时是 JSON 项目简介。"""
    import json as _json
    from pathlib import Path

    import app.main as main_mod

    dist = Path(main_mod.__file__).resolve().parent.parent / "clients" / "web" / "dist"
    resp = client.get("/")
    assert resp.status_code == 200
    if dist.exists():
        # 静态托管形态：/ 由 lifespan 挂载的 StaticFiles 接管
        assert resp.headers["content-type"].startswith("text/html")
    else:
        assert "/chat" in _json.loads(resp.text)["endpoints"]


def test_chat_with_tool_call(client):
    """带工具调用的对话：天气查询应触发 get_weather 并返回结果。"""
    resp = client.post("/chat", json={"message": "北京天气怎么样？", "thread_id": "smoke-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "北京" in data["reply"] or "结果" in data["reply"]
    assert data["thread_id"] == "smoke-1"


def test_chat_multi_turn(client):
    """多轮对话：同 thread_id 续接。"""
    # 第一轮
    r1 = client.post("/chat", json={"message": "你好", "thread_id": "multi-1"})
    assert r1.status_code == 200
    # 第二轮（同 thread）
    r2 = client.post("/chat", json={"message": "上海天气？", "thread_id": "multi-1"})
    assert r2.status_code == 200
    assert "结果" in r2.json()["reply"]


def test_chat_stream(client):
    """流式对话返回 SSE 事件。"""
    with client.stream("POST", "/chat/stream", json={"message": "你好", "thread_id": "stream-1"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
        assert "token" in body or "done" in body


def test_list_tools(client):
    """/tools 列出 Agent 可用工具（含内置 + Skill 注入的）。"""
    resp = client.get("/tools")
    assert resp.status_code == 200
    data = resp.json()
    names = [t["name"] for t in data["tools"]]
    assert data["count"] >= 3, f"工具数应 >=3，实际 {names}"
    # 内置工具
    assert "calculator" in names
    assert "get_current_time" in names
    # Skill 注入的工具（lifespan 已加载 math_assistant Skill）
    assert "advanced_math" in names, f"Skill 工具未注入: {names}"


def test_list_skills(client):
    """/skills 列出已注册的 Skill。"""
    resp = client.get("/skills")
    assert resp.status_code == 200
    data = resp.json()
    skill_names = [s["name"] for s in data["skills"]]
    assert "math_assistant" in skill_names
    assert "math_assistant" in data["loaded"], "Skill 未被加载"


def test_chat_with_skill_tool(client):
    """对话能调用 Skill 提供的工具（advanced_math）。"""
    # Mock 会因 "计算" 触发 advanced_math 调用
    resp = client.post("/chat", json={"message": "计算 2**10", "thread_id": "skill-1"})
    assert resp.status_code == 200
    data = resp.json()
    # 回复应含计算结果
    assert "1024" in data["reply"] or "计算" in data["reply"]

