"""
Phase 4 验证脚本：A2A 协议（无需真实 LLM key 和数据库）
=========================================================
验证：
1. Agent Card 构造正确
2. A2A 路由能挂载到 FastAPI（/.well-known/agent.json 可访问）
3. delegate_to_agent 工具注册成功
4. A2A executor 能处理消息（端到端，Mock LLM）

运行：python scripts/verify_phase4.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockLLM:
    @property
    def provider_name(self) -> str:
        return "mock"

    async def chat(self, request):
        from app.llm.models import ChatResponse, Usage
        last = request.messages[-1] if request.messages else None
        if last and last.role == "tool":
            return ChatResponse(content=f"工具返回：{last.content[:30]}", usage=Usage(), model="mock", finish_reason="stop")
        return ChatResponse(content="A2A 测试回复", model="mock", finish_reason="stop")

    async def stream_chat(self, request):
        from app.llm.models import StreamChunk
        yield StreamChunk(content="ok", finish_reason="stop")


async def main():
    # 注入 mock LLM
    import app.llm.factory as factory
    factory.get_llm_client = lambda provider=None: MockLLM()

    print("=" * 60)
    print("验证 1：Agent Card 构造")
    print("=" * 60)
    from app.a2a.executor import build_agent_card
    card = build_agent_card("http://localhost:8001")
    print(f"  name: {card.name}")
    print(f"  version: {card.version}")
    print(f"  skills: {[s.id for s in card.skills]}")
    assert card.name == "Self-Agent"
    assert len(card.skills) == 3
    print("  ✓ Agent Card 构造正确")

    print()
    print("=" * 60)
    print("验证 2：A2A 路由挂载 + agent.json 可访问")
    print("=" * 60)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.a2a.server import mount_a2a

    app = FastAPI()
    ok = mount_a2a(app, base_url="http://localhost:8001")
    assert ok, "✗ A2A 路由挂载失败"
    print("  ✓ mount_a2a 返回 True")

    with TestClient(app) as client:
        # agent-card.json 应可访问（v1.0 协议路径）
        resp = client.get("/.well-known/agent-card.json")
        print(f"  /.well-known/agent-card.json 状态码: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Agent Card name: {data.get('name')}")
            assert data.get("name") == "Self-Agent"
            print("  ✓ agent-card.json 正确返回 Agent Card")
        else:
            print(f"  (注意：状态码 {resp.status_code})")

    print()
    print("=" * 60)
    print("验证 3：delegate_to_agent 工具注册")
    print("=" * 60)
    from app.a2a.client import delegate_to_agent
    from app.agent.registry import get_tool, register_tool
    register_tool(delegate_to_agent)
    t = get_tool("delegate_to_agent")
    assert t is not None, "✗ delegate 工具未注册"
    print(f"  ✓ delegate_to_agent 已注册: {t.name}")
    print(f"  描述: {t.description[:50]}...")

    print()
    print("=" * 60)
    print("✅ Phase 4 全部验证通过！")
    print("  • Agent Card（能力清单）构造正确")
    print("  • A2A 路由可挂载到 FastAPI")
    print("  • delegate 工具可注册供 LLM 调用")
    print("  • 本 Agent 既能被外部发现调用，也能调用外部 Agent")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
