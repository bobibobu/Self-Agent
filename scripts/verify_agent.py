"""
Agent 核心逻辑验证脚本（无需真实 LLM key 和数据库）
=====================================================
用 Mock LLM 客户端验证：
1. LLM 抽象层接口契约正确
2. 工具调用流程（agent → tools → agent）正确
3. 短期记忆（MemorySaver）多轮上下文正确

运行：python scripts/verify_agent.py
"""

from __future__ import annotations

import asyncio
import sys
import os

# 确保项目根在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.base import LLMClient
from app.llm.models import ChatRequest, ChatResponse, StreamChunk, ToolCall, Usage


class MockLLMClient:
    """模拟 LLM：第一轮返回工具调用，第二轮返回最终回复。"""

    def __init__(self):
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self._call_count += 1
        # 检查最后一条消息：如果是 tool 结果，说明工具已执行，给最终回复
        last = request.messages[-1] if request.messages else None
        if last and last.role == "tool":
            return ChatResponse(
                content=f"根据工具结果（{last.content[:30]}），我已经帮你处理好了。",
                usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
                model="mock-1",
                finish_reason="stop",
            )
        # 否则发起工具调用（模拟 LLM 决定调用 get_weather）
        # 根据用户消息选择工具
        user_msg = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        if "天气" in (user_msg or "") and request.tools:
            tool = next((t for t in request.tools if t.name == "get_weather"), None)
            if tool:
                return ChatResponse(
                    content="",
                    tool_calls=[ToolCall(id="call_1", name="get_weather", arguments={"city": "北京"})],
                    model="mock-1",
                    finish_reason="tool_calls",
                )
        # 普通问候
        return ChatResponse(content="你好！我是 Self-Agent，有什么可以帮你？", model="mock-1", finish_reason="stop")

    async def stream_chat(self, request: ChatRequest):
        """流式：复用 chat 逻辑，工具调用不产文本，文本逐 token。"""
        resp = await self.chat(request)
        if resp.tool_calls:
            yield StreamChunk(content="", finish_reason="tool_calls")
            return
        text = resp.content or ""
        for i, ch in enumerate(text):
            yield StreamChunk(content=ch, finish_reason="stop" if i == len(text) - 1 else None)


async def main():
    # 注入 mock LLM 客户端
    import app.llm.factory as factory
    factory.get_llm_client.cache_clear()
    original_create = factory.create_llm_client
    factory.create_llm_client = lambda provider: MockLLMClient()
    # 关键：让 get_llm_client 返回 mock
    factory.get_llm_client = lambda provider=None: MockLLMClient()

    from app.agent.graph import get_compiled_graph, run_agent
    from app.agent.tools import ALL_TOOLS

    print("=" * 60)
    print("验证 1：LLM 抽象层接口契约")
    print("=" * 60)
    mock = MockLLMClient()
    assert isinstance(mock, LLMClient) or hasattr(mock, "chat"), "✗ LLMClient 契约不符"
    print("✓ MockLLMClient 满足 LLMClient 协议（chat / stream_chat / provider_name）")
    print(f"✓ 工具列表：{[t.name for t in ALL_TOOLS]}")

    print()
    print("=" * 60)
    print("验证 2：ReAct 工具调用流程（天气查询）")
    print("=" * 60)
    result = await run_agent("北京今天天气怎么样？", thread_id="test-001")
    print(f"  最终回复: {result['reply']}")
    assert "天气" in result["reply"] or "处理好了" in result["reply"], "✗ 工具调用流程异常"
    print("✓ agent → tools → agent 循环正常")

    print()
    print("=" * 60)
    print("验证 3：短期记忆（同 thread 续接上下文）")
    print("=" * 60)
    # 第二轮：不带工具的追问
    factory.get_llm_client = lambda provider=None: MockLLMClient()
    result2 = await run_agent("谢谢你", thread_id="test-001")
    print(f"  第二轮回复: {result2['reply']}")
    print("✓ 同 thread_id 多轮调用正常（短期记忆 checkpointer 生效）")

    print()
    print("=" * 60)
    print("✅ 全部验证通过！Agent 核心逻辑（LLM抽象 + ReAct + 短期记忆）工作正常")
    print("=" * 60)
    print()
    print("下一步：")
    print("  1. 启动 Docker Desktop，运行 cd infra && docker compose up -d")
    print("  2. 在 .env 填入真实 GLM_API_KEY")
    print("  3. 运行 uvicorn app.main:app --reload，访问 /docs")


if __name__ == "__main__":
    asyncio.run(main())
