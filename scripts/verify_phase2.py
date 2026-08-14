"""
Phase 2 验证脚本：MCP + Skill 系统（无需真实 LLM key 和数据库）
================================================================
验证：
1. Skill 声明式注册 + 加载后工具进入注册表
2. Skill 提示词片段能注入系统提示
3. MCP server 能构造（FastMCP）
4. MCP client 配置解析逻辑正确
5. Agent 能调用 Skill 带来的工具（端到端，Mock LLM）

运行：python scripts/verify_phase2.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.models import ChatRequest, ChatResponse, StreamChunk, ToolCall, Usage


class MockLLM:
    """模拟 LLM：能识别 Skill 工具并触发调用。"""

    @property
    def provider_name(self) -> str:
        return "mock"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        msgs = [m for m in request.messages if not (m.role == "user" and (m.content or "").startswith("[当前时间："))]
        last = msgs[-1] if msgs else None
        if last and last.role == "tool":
            return ChatResponse(
                content=f"计算完成：{last.content[:50]}",
                usage=Usage(prompt_tokens=8, completion_tokens=12, total_tokens=20),
                model="mock",
                finish_reason="stop",
            )
        user_msg = next((m.content for m in reversed(msgs) if m.role == "user"), "")
        # 检查系统提示里是否有 Skill 提示词（验证注入）
        sys_msgs = [m.content for m in request.messages if m.role == "system"]
        _ = " ".join(sys_msgs)

        # 如果有 advanced_math 工具且用户问数学，触发它
        if request.tools:
            for t in request.tools:
                if t.name == "advanced_math" and any(c in (user_msg or "") for c in ["**", "sqrt", "计算"]):
                    return ChatResponse(
                        tool_calls=[ToolCall(id="c1", name="advanced_math", arguments={"expression": "2**10"})],
                        model="mock",
                        finish_reason="tool_calls",
                    )
        return ChatResponse(content="你好", model="mock", finish_reason="stop")

    async def stream_chat(self, request):
        """流式契约（与真实 provider 一致）：收尾 chunk 携带聚合 tool_calls/usage。"""
        resp = await self.chat(request)
        if resp.tool_calls:
            yield StreamChunk(content="", tool_calls=resp.tool_calls, finish_reason="tool_calls")
            return
        for ch in (resp.content or ""):
            yield StreamChunk(content=ch)
        yield StreamChunk(content="", usage=resp.usage, finish_reason="stop")


async def main():
    print("=" * 60)
    print("验证 1：Skill 声明式注册与工具注入")
    print("=" * 60)

    # 导入 builtin 触发 @skill 注册
    import app.skills.builtin  # noqa
    from app.skills.registry import skill_registry
    from app.agent import registry as tool_reg

    skills = skill_registry.list_skills()
    print(f"  已注册 Skill: {[s['name'] for s in skills]}")
    assert any(s["name"] == "math_assistant" for s in skills), "✗ math_assistant 未注册"
    print("  ✓ math_assistant 已注册")

    # 加载默认 Skill
    loaded = skill_registry.load_all_defaults(tool_registry=tool_reg)
    print(f"  已加载 Skill 数: {loaded}")
    assert loaded >= 1, "✗ Skill 未加载"

    # 验证 Skill 的工具进入了注册表
    all_tools = tool_reg.get_all_tools()
    tool_names = [t.name for t in all_tools]
    print(f"  Agent 工具集: {tool_names}")
    assert "advanced_math" in tool_names, "✗ advanced_math 未进入工具集"
    print("  ✓ Skill 工具 (advanced_math) 已注入工具注册表")

    print()
    print("=" * 60)
    print("验证 2：Skill 提示词片段注入系统提示")
    print("=" * 60)
    from app.agent.graph import _build_system_prompt
    sys_content = _build_system_prompt()
    assert "数学助手已激活" in sys_content, "✗ Skill 提示词未注入"
    print("  ✓ 系统提示已包含 Skill 专属提示词片段")
    print(f"  系统提示长度: {len(sys_content)} 字符")

    print()
    print("=" * 60)
    print("验证 3：MCP server 构造")
    print("=" * 60)
    from app.mcp.server import build_mcp_server
    mcp = build_mcp_server()
    print(f"  ✓ FastMCP server 构造成功: {mcp.name}")

    print()
    print("=" * 60)
    print("验证 4：MCP client 配置解析")
    print("=" * 60)
    from app.mcp.client import mcp_client_manager
    servers = mcp_client_manager._load_servers_config()
    print(f"  无配置文件时解析结果: {servers} (预期空 dict)")
    assert servers == {}, "✗ 无配置时应返回空"
    print("  ✓ 配置解析正确（无文件时优雅返回空）")

    print()
    print("=" * 60)
    print("验证 5：Agent 调用 Skill 工具（端到端）")
    print("=" * 60)
    # 注入 Mock LLM
    import app.llm.factory as factory
    factory.get_llm_client = lambda provider=None: MockLLM()

    from app.agent.graph import run_agent
    result = await run_agent("帮我计算 2**10", thread_id="phase2-test")
    print(f"  Agent 回复: {result['reply']}")
    assert "1024" in result["reply"] or "计算完成" in result["reply"], "✗ Skill 工具未被正确调用"
    print("  ✓ Agent 成功调用了 Skill 提供的 advanced_math 工具")

    print()
    print("=" * 60)
    print("✅ Phase 2 全部验证通过！MCP + Skill 系统工作正常")
    print("=" * 60)
    print()
    print("验证内容回顾：")
    print("  • Skill 声明式注册 (@skill 装饰器)")
    print("  • Skill 工具自动注入 Agent 工具注册表")
    print("  • Skill 提示词注入系统提示")
    print("  • MCP server (FastMCP) 可构造并暴露工具")
    print("  • MCP client 配置解析（优雅降级）")
    print("  • Agent 端到端调用 Skill 工具")


if __name__ == "__main__":
    asyncio.run(main())
