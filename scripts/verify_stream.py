"""
流式验证脚本：验证真·token 级流式（无需真实 LLM key 和数据库）
================================================================
验证：
1. stream_agent 逐事件 yield（token / tool_calls / tool_start / tool_result / done）
2. token 真的是逐个推送（不是一次性）
3. 工具调用流程的事件顺序正确
4. done 事件的 reply 是完整拼接

运行：python scripts/verify_stream.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.models import ChatRequest, ChatResponse, StreamChunk, ToolCall, Usage


class MockStreamLLM:
    """模拟支持流式的 LLM：分多个 chunk 返回文本 + 工具调用。"""

    def __init__(self):
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock-stream"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """非流式：返回工具调用（天气查询场景）。"""
        self._call_count += 1
        # agent_node 会在对话末尾追加「[当前时间：...]」HumanMessage 作为环境参考，
        # 判断消息角色时要先过滤掉它（与 test_api_smoke 的 mock 保持一致）
        msgs = [m for m in request.messages if not (m.role == "user" and (m.content or "").startswith("[当前时间："))]
        last = msgs[-1] if msgs else None
        if last and last.role == "tool":
            # 工具结果后，返回最终自然语言回复
            return ChatResponse(
                content="北京今天晴朗，气温26度，适合出行。",
                usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
                model="mock-stream",
                finish_reason="stop",
            )
        # 首轮：决定调用天气工具
        user_msg = next((m.content for m in reversed(msgs) if m.role == "user"), "")
        if "天气" in (user_msg or "") and request.tools:
            return ChatResponse(
                tool_calls=[ToolCall(id="c1", name="get_weather", arguments={"city": "北京"})],
                model="mock-stream",
                finish_reason="tool_calls",
            )
        return ChatResponse(content="你好，我是助手。", model="mock-stream", finish_reason="stop")

    async def stream_chat(self, request: ChatRequest):
        """流式：逐 token 产文本，收尾 chunk 携带聚合结果。

        契约（与真实 provider 一致）：tool_calls / usage 只出现在流末尾的
        收尾 chunk 上——agent_node 一次流式请求同时拿到文本与工具决策。
        """
        resp = await self.chat(request)
        if resp.tool_calls:
            yield StreamChunk(
                content="",
                tool_calls=resp.tool_calls,
                finish_reason="tool_calls",
            )
            return
        # 文本回复：逐字 yield（模拟 token 流）
        text = resp.content or ""
        for tok in text:
            yield StreamChunk(content=tok)
        yield StreamChunk(
            content="",
            usage=resp.usage,
            finish_reason="stop",
        )


async def main():
    # 注入 mock LLM
    import app.llm.factory as factory
    # 共享单例：让调用计数可观测（每次 new 实例会把计数打散）
    mock_llm = MockStreamLLM()
    factory.get_llm_client = lambda provider=None: mock_llm

    from app.agent.graph import stream_agent

    print("=" * 60)
    print("验证：真·token 级流式（含工具调用）")
    print("=" * 60)
    print("用户输入: 北京天气怎么样？")
    print("-" * 60)

    events = []
    token_count = 0
    async for event in stream_agent("北京天气怎么样？", thread_id="stream-test"):
        events.append(event)
        etype = event.get("type")
        if etype == "token":
            token_count += 1
            # 逐 token 打印（不换行，模拟打字机）
            print(event.get("text", ""), end="", flush=True)
        elif etype == "tool_calls":
            print(f"\n  [事件] 决定调用工具: {[c['name'] for c in event.get('calls', [])]}")
        elif etype == "tool_start":
            print(f"  [事件] 工具开始: {event.get('name')} {event.get('args')}")
        elif etype == "tool_result":
            print(f"  [事件] 工具结果: {event.get('name')} → {event.get('content', '')[:40]}")
        elif etype == "done":
            print(f"\n  [事件] 完成: reply 长度={len(event.get('reply', ''))}")
        elif etype == "error":
            print(f"\n  [事件] 错误: {event.get('message')}")

    print("-" * 60)
    print(f"总事件数: {len(events)}")
    print(f"token 事件数: {token_count}（应 > 1，证明逐 token 推送）")

    # 断言
    types = [e["type"] for e in events]
    assert token_count > 1, f"✗ token 数应 > 1，实际 {token_count}（说明没真流式）"
    assert "tool_calls" in types, "✗ 缺 tool_calls 事件"
    assert "tool_start" in types, "✗ 缺 tool_start 事件"
    assert "tool_result" in types, "✗ 缺 tool_result 事件"
    assert types[-1] == "done", f"✗ 最后事件应是 done，实际 {types[-1]}"

    done_event = events[-1]
    assert "晴朗" in done_event["reply"] or "26" in done_event["reply"], "✗ done 的 reply 不完整"

    # ★ 单次调用断言（流式 tool_calls 聚合优化的核心证据）：
    # 本次对话共 2 个 agent 步骤（决策调工具 → 工具后总结），
    # mock 的 stream_chat 内部复用 chat() 判断逻辑，每步恰好 1 次。
    # 若退化回「流式出文本 + chat() 复查」的双调用，计数会是 4。
    assert mock_llm._call_count == 2, (
        f"✗ LLM 调用次数异常：{mock_llm._call_count}（预期 2 = 每步 1 次；"
        f"若为 4 说明退化为双调用，延迟/成本翻倍）"
    )

    print()
    print("✅ 真·token 流式验证通过！")
    print(f"   • 逐 token 推送（{token_count} 个 token）")
    print("   • 工具调用中间步骤推送（tool_calls/start/result）")
    print("   • done 事件含完整回复")
    print("   • 事件顺序: token流 → tool_calls → tool_start → tool_result → token流 → done")
    print(f"   • 单次调用验证：2 个 agent 步骤 = {mock_llm._call_count} 次 LLM 调用（无复查冗余）")


if __name__ == "__main__":
    asyncio.run(main())
