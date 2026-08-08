"""
Prompt 缓存命中测试
===================
2026-08 改造：重构系统提示拼装，让 LLM 的 prompt caching 能命中。

核心断言：**多轮调用的 system prompt 完全一致**（前缀稳定）。
如果前缀每轮变化（如改造前时间戳填进 SYSTEM_PROMPT），prompt cache 永远 miss。

背景：GLM/OpenAI/Anthropic 的 prompt caching 都只认「精确前缀匹配」。
本测试钉住「SYSTEM_PROMPT 主体静态」这条不变量。
"""

import pytest

from app.agent.prompts import SYSTEM_PROMPT


class _EchoLLM:
    """最小 LLM 桩：不调网络，记录每次收到的消息列表。"""

    def __init__(self):
        self.seen_requests = []

    @property
    def provider_name(self) -> str:
        return "echo"

    @property
    def default_model(self) -> str:
        return "echo"

    async def chat(self, request):
        from app.llm.models import ChatResponse

        self.seen_requests.append(request)
        return ChatResponse(content="好的", model="echo", finish_reason="stop")

    async def stream_chat(self, request):
        from app.llm.models import StreamChunk, Usage

        self.seen_requests.append(request)
        yield StreamChunk(content="好的")
        yield StreamChunk(content="", finish_reason="stop", usage=Usage(), model="echo")


class TestPromptCachingPrefix:
    """系统提示的静态前缀在多轮调用间完全一致。"""

    @pytest.mark.asyncio
    async def test_system_prompt_constant_across_turns(self, monkeypatch):
        """多轮 run_agent，每次发给 LLM 的 system 消息内容必须**完全相同**。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        tid = "cache-prefix-1"
        for _ in range(3):
            await run_agent("你好", thread_id=tid)

        assert len(llm.seen_requests) >= 2, "至少要 2 轮才能比对前缀"

        # 每次请求的第一条消息都是 system，内容必须逐字相同
        first_system = llm.seen_requests[0].messages[0]
        assert first_system.role == "system", "第一条消息必须是 system"

        for req in llm.seen_requests[1:]:
            sys_msg = req.messages[0]
            assert sys_msg.role == "system"
            assert sys_msg.content == first_system.content, (
                "多轮调用的 system prompt 不一致——prompt cache 会永远 miss！\n"
                f"首轮: {first_system.content[:100]!r}\n"
                f"本轮: {sys_msg.content[:100]!r}"
            )

    @pytest.mark.asyncio
    async def test_no_timestamp_in_system_prompt(self, monkeypatch):
        """SYSTEM_PROMPT 不含当前时间——时间戳会破坏缓存前缀。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        await run_agent("你好", thread_id="cache-prefix-2")

        sys_content = llm.seen_requests[0].messages[0].content
        # system 里不应出现「当前时间：2026」这样的动态字符串
        assert "当前时间：" not in sys_content, (
            "SYSTEM_PROMPT 里不应含当前时间戳（会破坏 prompt caching 前缀）。"
            f"实际内容片段：{sys_content[-80:]!r}"
        )

    @pytest.mark.asyncio
    async def test_timestamp_passed_via_config_as_trailing_message(self, monkeypatch):
        """时间戳改走 config，作为对话末尾的 HumanMessage 出现，不进 system。"""
        import app.agent.nodes.agent_node as node
        from app.agent.graph import run_agent

        llm = _EchoLLM()
        monkeypatch.setattr(node, "get_llm_client", lambda *a, **k: llm)

        await run_agent("你好", thread_id="cache-prefix-3")

        req = llm.seen_requests[0]
        # 最后一条消息应是 user（时间戳），含「当前时间」标记
        last = req.messages[-1]
        assert last.role == "user", f"末尾应是时间戳的 user 消息，实际 role={last.role}"
        assert "当前时间" in last.content, "末尾 user 消息应含当前时间"


class TestSystemPromptStatic:
    """SYSTEM_PROMPT 模板本身是完全静态的（无占位符）。"""

    def test_system_prompt_has_no_placeholder(self):
        """模板不应含 {xxx} 占位符——占位符意味着运行时填充，破坏静态性。"""
        assert "{" not in SYSTEM_PROMPT, (
            f"SYSTEM_PROMPT 含花括号（可能是占位符），会破坏 prompt caching：\n"
            f"{SYSTEM_PROMPT}"
        )
        assert "}" not in SYSTEM_PROMPT

    def test_system_prompt_mentions_time_tool(self):
        """去掉时间戳后，应提示模型用 get_current_time 工具获取时间。"""
        assert "get_current_time" in SYSTEM_PROMPT
