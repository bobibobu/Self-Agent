"""
客户端协议契约测试
==================
后端接口「能返回正确数据」不等于「客户端能用」——这两个 bug 就是活例子：

1. Web 端流式一片空白：后端 SSE 事件块用 CRLF 分隔（sse-starlette 的
   DEFAULT_SEPARATOR = "\\r\\n"，2.x 和 3.x 都是），前端却按 '\\n\\n' 切分。
   '\\r\\n\\r\\n' 里根本不存在 '\\n\\n' 子串 → 切分永不匹配 → 整个流被当成
   一块 → 所有 data 拼在一起 JSON.parse 失败 → 前端只收到一个空的 done。
   后端测试全绿，页面上是个空气泡。

2. CLI 全线 401：AUTH_ENABLED 默认改成 true 后，CLI 没有任何 token 支持。

所以这里测的是**线上字节格式**与**客户端解析逻辑**的对接，
其中 SSE 解析器是 clients/web/src/api.js 的等价实现——
两边要一起改，改一边就会在这里挂。

运行：pytest tests/test_client_contract.py -v
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# clients/web/src/api.js 中 parseSSEBlock + streamChat 的 Python 等价实现
# ---------------------------------------------------------------------------


def parse_sse_stream(raw: str) -> list[dict]:
    """按 WHATWG SSE 规范解析。与前端实现保持一致。"""
    events: list[dict] = []
    # 规范：行结束符可以是 CRLF / CR / LF，先归一
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    for block in normalized.split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue  # 空行与注释（sse-starlette 的 ping）
            idx = line.find(":")
            field = line if idx == -1 else line[:idx]
            value = "" if idx == -1 else line[idx + 1:]
            if value.startswith(" "):
                value = value[1:]  # 只去一个空格，不能 trim
            if field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        try:
            events.append({"type": event_type, **json.loads(payload)})
        except json.JSONDecodeError:
            events.append({"type": event_type, "raw": payload})
    return events


def buggy_parse_sse_stream(raw: str) -> list[dict]:
    """修复前的实现，仅用于证明 bug 确实存在（不要照抄）。"""
    events, buffer = [], ""
    for ch in raw:
        buffer += ch
        blocks = buffer.split("\n\n")
        buffer = blocks.pop()
        for block in blocks:
            ev = _buggy_parse_block(block)
            if ev:
                events.append(ev)
    if buffer.strip():
        ev = _buggy_parse_block(buffer)
        if ev:
            events.append(ev)
    return events


def _buggy_parse_block(block: str):
    event_type, data_str = "message", ""
    for line in block.split("\n"):
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_str += line[5:].strip()
    if not data_str:
        return None
    try:
        return {"type": event_type, **json.loads(data_str)}
    except json.JSONDecodeError:
        return {"type": event_type, "raw": data_str}


def render(events: list[dict]) -> str:
    """模拟前端把事件流渲染成气泡文本。"""
    content = ""
    for e in events:
        if e.get("type") == "token":
            content += e.get("text", "")
        elif e.get("type") == "done" and not content:
            content = e.get("reply") or ""
    return content


# ---------------------------------------------------------------------------


class _MockLLM:
    provider_name = "mock"
    default_model = "mock-model"

    REPLY = "你好，我是 Self-Agent。"

    async def chat(self, request):
        from app.llm.models import ChatResponse

        return ChatResponse(content=self.REPLY, model="mock-model", finish_reason="stop")

    async def stream_chat(self, request):
        from app.llm.models import StreamChunk, Usage

        for ch in self.REPLY:
            yield StreamChunk(content=ch)
        yield StreamChunk(
            content="", finish_reason="stop",
            usage=Usage(prompt_tokens=5, completion_tokens=9), model="mock-model",
        )


@pytest.fixture
def client(monkeypatch):
    import app.agent.nodes.agent_node as node
    import app.api.routes as routes
    import app.llm.factory as factory

    mock = _MockLLM()
    for mod in (factory, routes, node):
        monkeypatch.setattr(mod, "get_llm_client", lambda *a, **k: mock)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestWebSSEContract:
    """Web 端：/chat/stream 的 SSE 字节必须能被前端解析器还原成逐 token 文本。"""

    def test_sse_uses_crlf_separators(self, client):
        """先把「后端到底吐什么」钉死——前端解析器是照着它写的。"""
        with client.stream("POST", "/chat/stream", json={"message": "hi", "thread_id": "c-1"}) as r:
            raw = b"".join(r.iter_bytes()).decode()
        assert "\r\n\r\n" in raw, (
            "sse-starlette 默认用 CRLF 分隔事件块；若哪天变成 LF，"
            "前端归一化逻辑仍然兼容，但这条断言会提醒你契约变了"
        )

    def test_frontend_parser_recovers_every_token(self, client):
        with client.stream("POST", "/chat/stream", json={"message": "hi", "thread_id": "c-2"}) as r:
            raw = b"".join(r.iter_bytes()).decode()

        events = parse_sse_stream(raw)
        tokens = [e for e in events if e["type"] == "token"]
        assert len(tokens) == len(_MockLLM.REPLY), f"应有 {len(_MockLLM.REPLY)} 个 token 事件"
        assert render(events) == _MockLLM.REPLY

    def test_done_event_reply_matches_tokens(self, client):
        with client.stream("POST", "/chat/stream", json={"message": "hi", "thread_id": "c-3"}) as r:
            raw = b"".join(r.iter_bytes()).decode()
        events = parse_sse_stream(raw)
        done = next(e for e in events if e["type"] == "done")
        joined = "".join(e.get("text", "") for e in events if e["type"] == "token")
        assert done["reply"] == joined

    def test_old_parser_would_render_nothing(self, client):
        """回归证据：旧实现在同样字节上只解析出 1 个事件、渲染为空。"""
        with client.stream("POST", "/chat/stream", json={"message": "hi", "thread_id": "c-4"}) as r:
            raw = b"".join(r.iter_bytes()).decode()

        buggy = buggy_parse_sse_stream(raw)
        assert render(buggy) == "", "旧解析器应当渲染为空——这正是页面空气泡的成因"
        assert render(parse_sse_stream(raw)) == _MockLLM.REPLY

    def test_parser_skips_ping_comments(self):
        """sse-starlette 会周期性发 `: ping` 注释，不能被当成事件。"""
        raw = (
            "event: token\r\ndata: {\"type\": \"token\", \"text\": \"A\"}\r\n\r\n"
            ": ping - 2026-08-01T00:00:00\r\n\r\n"
            "event: done\r\ndata: {\"type\": \"done\", \"reply\": \"A\"}\r\n\r\n"
        )
        events = parse_sse_stream(raw)
        assert [e["type"] for e in events] == ["token", "done"]
        assert render(events) == "A"

    def test_parser_handles_lf_and_cr_separators(self):
        """规范允许三种行结束符，解析器都要吃得下。"""
        payload = '{"type": "token", "text": "X"}'
        for sep in ("\r\n", "\n", "\r"):
            raw = f"event: token{sep}data: {payload}{sep}{sep}"
            assert render(parse_sse_stream(raw)) == "X", f"分隔符 {sep!r} 解析失败"


class TestCliNDJSONContract:
    """CLI：/chat/http-stream 每行一个 JSON，逐行解析必须还原完整回复。"""

    def test_ndjson_lines_are_individually_parseable(self, client):
        with client.stream("POST", "/chat/http-stream", json={"message": "hi", "thread_id": "c-5"}) as r:
            raw = b"".join(r.iter_bytes()).decode()

        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        assert render(events) == _MockLLM.REPLY
        assert events[-1]["type"] == "done"


class TestCliAuthSupport:
    """CLI 必须支持 token——AUTH_ENABLED=true 时没有它就是全线 401。"""

    def test_stream_chat_accepts_token(self):
        import inspect

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "clients", "cli"))
        from selfagent_cli.api import get_json, stream_chat

        assert "token" in inspect.signature(stream_chat).parameters
        assert "token" in inspect.signature(get_json).parameters

    def test_auth_headers_shape(self):
        from selfagent_cli.api import auth_headers

        assert auth_headers("abc")["Authorization"] == "Bearer abc"
        assert "Authorization" not in auth_headers(None)

    @pytest.mark.asyncio
    async def test_query_params_are_url_encoded(self, monkeypatch):
        """/memory 的查询串曾用 f"?query={query}" 手工拼接，含空格/中文/& 会拼坏。

        用假 transport 截下真实请求 URL 来验证，而不是去 grep 源码
        （源码里的注释也会命中字符串，那种断言测的是注释不是行为）。
        """
        import httpx

        from selfagent_cli.api import get_json

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["query"] = dict(request.url.params)
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"memories": []})

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def fake_client(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", fake_client)

        tricky = "Python 开发 & 机器学习"
        await get_json("http://x", "/memory/u1", token="tok", params={"query": tricky})

        # 原样解码得回来，说明编码正确；& 没有把参数截断
        assert captured["query"]["query"] == tricky, f"查询串被拼坏了：{captured['url']}"
        assert " " not in captured["url"], "URL 里不该出现裸空格"
        assert captured["auth"] == "Bearer tok"

    def test_credentials_saved_with_owner_only_permission(self, tmp_path, monkeypatch):
        """token 等同于密码，落盘必须是 0600。"""
        import stat

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from selfagent_cli.config import _credentials_path, load_credentials, save_credentials

        save_credentials("tok-123", {"id": "u1", "username": "alice"})
        path = _credentials_path()
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"凭据文件权限应为 0600，实际 {oct(mode)}"
        assert load_credentials()["access_token"] == "tok-123"
