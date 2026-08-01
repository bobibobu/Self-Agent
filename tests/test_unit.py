"""
单元测试：纯逻辑层（不依赖 DB / LLM / 网络）
=============================================
快速执行的单元测试，覆盖：
- LLM 消息格式转换（OpenAI / Anthropic）
- 工具安全求值（calculator）
- 工具注册表（registry）
- 长期记忆（InMemoryStore）
- 用户画像（内存兜底）
- 配置解析

运行：pytest tests/test_unit.py -v
"""

from __future__ import annotations

import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==================== 1. calculator 安全求值 ====================


class TestCalculator:
    """计算器工具的安全求值逻辑。"""

    def test_basic_arithmetic(self):
        from app.agent.tools import calculator
        result = calculator.invoke({"expression": "3 + 4 * 2"})
        assert "11" in result

    def test_power(self):
        from app.agent.tools import calculator
        assert "1024" in calculator.invoke({"expression": "2 ** 10"})

    def test_functions(self):
        from app.agent.tools import calculator
        assert "3.14" in calculator.invoke({"expression": "round(3.14159, 2)"})
        assert "5" in calculator.invoke({"expression": "abs(-5)"})
        assert "3" in calculator.invoke({"expression": "max(1, 2, 3)"})

    def test_negative_numbers(self):
        from app.agent.tools import calculator
        assert "-3" in calculator.invoke({"expression": "-3"})
        assert "-10" in calculator.invoke({"expression": "5 - 15"})

    def test_invalid_expression_rejected(self):
        """不安全的表达式应被拒绝。"""
        from app.agent.tools import calculator
        # 不允许属性访问、import 等
        result = calculator.invoke({"expression": "__import__('os')"})
        assert "无法计算" in result or "不支持" in result

    def test_division_by_zero(self):
        from app.agent.tools import calculator
        result = calculator.invoke({"expression": "1 / 0"})
        # 应优雅报错而非崩溃
        assert "无法计算" in result or "错误" in result or "infinity" in result.lower() or "=" in result


# ==================== 2. 时间工具 ====================


class TestTimeTool:
    def test_default_timezone(self):
        from app.agent.tools import get_current_time
        result = get_current_time.invoke({"timezone": "Asia/Shanghai"})
        assert "上海" in result or "Shanghai" in result
        assert "当前时间" in result

    def test_utc(self):
        from app.agent.tools import get_current_time
        result = get_current_time.invoke({"timezone": "UTC"})
        assert "UTC" in result

    def test_invalid_timezone(self):
        from app.agent.tools import get_current_time
        result = get_current_time.invoke({"timezone": "Mars/Olympus"})
        assert "未知时区" in result


# ==================== 3. 工具注册表 ====================


class TestRegistry:
    def test_initial_tools(self):
        from app.agent.registry import get_all_tools, tool_names
        names = tool_names()
        assert "calculator" in names
        assert "get_current_time" in names
        assert "get_weather" in names

    def test_register_and_get(self):
        from langchain_core.tools import tool as lc_tool
        from app.agent.registry import register_tool, get_tool

        @lc_tool
        def temp_tool(x: int) -> int:
            """临时测试工具。"""
            return x * 2

        register_tool(temp_tool)
        assert get_tool("temp_tool") is not None
        assert get_tool("nonexistent") is None


# ==================== 4. LLM 消息转换 ====================


class TestLLMConversion:
    """测试 LangChain 消息 → 统一 ChatMessage 的转换。"""

    def test_lc_to_chat_messages(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from app.agent.nodes.bridge import lc_to_chat_messages

        msgs = [
            SystemMessage(content="你是助手"),
            HumanMessage(content="你好"),
            AIMessage(content="你好！"),
        ]
        result = lc_to_chat_messages(msgs)
        assert result[0].role == "system"
        assert result[1].role == "user"
        assert result[2].role == "assistant"

    def test_tool_message_conversion(self):
        from langchain_core.messages import ToolMessage
        from app.agent.nodes.bridge import lc_to_chat_messages

        msgs = [ToolMessage(content="结果42", tool_call_id="c1", name="calc")]
        result = lc_to_chat_messages(msgs)
        assert result[0].role == "tool"
        assert result[0].tool_call_id == "c1"

    def test_build_tool_definitions(self):
        from app.agent.tools import ALL_TOOLS
        from app.agent.nodes.bridge import build_tool_definitions

        defs = build_tool_definitions(ALL_TOOLS)
        assert len(defs) >= 3
        names = [d.name for d in defs]
        assert "calculator" in names
        # 每个定义都应有 name、description、parameters
        for d in defs:
            assert d.name
            assert d.description
            assert isinstance(d.parameters, dict)


# ==================== 5. OpenAI 格式转换 ====================


class TestOpenAIConversion:
    def test_to_openai_messages(self):
        from app.llm.models import ChatMessage
        from app.llm.providers.openai_like import OpenAILikeClient

        client = OpenAILikeClient(
            api_key="fake", base_url="http://fake", default_model="m", provider_name="test"
        )
        msgs = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
        ]
        result = client._to_openai_messages(msgs)
        assert result[0] == {"role": "system", "content": "sys"}
        assert result[1] == {"role": "user", "content": "hi"}


# ==================== 6. 长期记忆 ====================


class TestMemory:
    def test_namespace(self):
        from app.memory.store import user_namespace
        assert user_namespace("u1") == ("user", "u1")

    @pytest.mark.asyncio
    async def test_hash_embed(self):
        from app.memory.embeddings import hash_embed
        vecs = hash_embed(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == len(vecs[1])  # 同维度
        # 相同输入得相同输出
        assert hash_embed(["abc"]) == hash_embed(["abc"])

    @pytest.mark.asyncio
    async def test_memory_add_search(self):
        from app.memory.store import get_memory_service
        mem = await get_memory_service()
        await mem.add_memory("test_user", "用户喜欢 Python")
        results = await mem.search_memory("test_user", "编程偏好")
        assert any("Python" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_get_all_memories_returns_written_items(self):
        """回归：get_all_memories 曾用 aget(ns, limit=) 调用，签名不存在 →
        TypeError 被 except 吞掉 → 无论写入多少条都返回空列表。"""
        from app.memory.store import get_memory_service

        mem = await get_memory_service()
        await mem.add_memory("list_user", "事实一", key="k1")
        await mem.add_memory("list_user", "事实二", key="k2")
        all_items = await mem.get_all_memories("list_user")
        contents = {m["content"] for m in all_items}
        assert {"事实一", "事实二"} <= contents, f"应列出全部记忆，实际 {all_items}"

    @pytest.mark.asyncio
    async def test_delete_memory_removes_it(self):
        from app.memory.store import get_memory_service

        mem = await get_memory_service()
        await mem.add_memory("del_user", "待删除", key="gone")
        await mem.delete_memory("del_user", "gone")
        assert all(m["key"] != "gone" for m in await mem.get_all_memories("del_user"))


# ==================== 7. 用户画像（内存兜底）====================


class TestProfile:
    @pytest.mark.asyncio
    async def test_profile_memory_fallback(self):
        from app.profile.service import ProfileService
        ps = ProfileService()
        # 强制使用内存兜底
        ps._use_neo4j = False
        await ps.add_interest("test_u", "机器学习")
        await ps.add_preference("test_u", "语言", "Python")
        profile = await ps.get_profile("test_u")
        assert profile["source"] == "memory_fallback"
        assert "机器学习" in profile["interests"]
        assert profile["preferences"]["语言"] == ["Python"]


# ==================== 8. 配置 ====================


class TestConfig:
    def test_config_loads(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.app_name == "Self-Agent"
        assert s.llm_default_provider in ("glm", "openai", "anthropic")

    def test_postgres_dsn_format(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.postgres_dsn.startswith("postgresql://")
        assert "selfagent" in s.postgres_dsn

    def test_redis_url(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.redis_url.startswith("redis://")


# ==================== 9. Skill 系统 ====================


class TestSkills:
    def test_skill_registration(self):
        from app.skills.registry import skill_registry
        import app.skills.builtin  # 触发注册  # noqa: F401
        skills = skill_registry.list_skills()
        names = [s["name"] for s in skills]
        assert "math_assistant" in names

    def test_skill_load_injects_tools(self):
        from app.skills.registry import skill_registry
        from app.agent import registry as tool_reg
        import app.skills.builtin  # noqa
        skill_registry.load("math_assistant", tool_registry=tool_reg)
        assert "advanced_math" in [t.name for t in tool_reg.get_all_tools()]


# ==================== 10. 异常体系 ====================


class TestExceptions:
    def test_app_error_attributes(self):
        from app.core.exceptions import LLMError
        e = LLMError("测试", provider="glm")
        assert e.code == "LLM_ERROR"
        assert e.status_code == 502
        assert e.provider == "glm"


# ==================== 11. 安全防护 ====================


class TestSecurity:
    def test_calculator_blocks_code_injection(self):
        """calculator 必须阻止代码注入。"""
        from app.agent.tools import calculator
        # 各种注入尝试都应被拒绝
        for evil in ["__import__('os')", "eval('1')", "(1).__class__", "open('/etc/passwd')"]:
            result = calculator.invoke({"expression": evil})
            assert "无法计算" in result or "不支持" in result, f"{evil} 未被阻止：{result}"

    @pytest.mark.asyncio
    async def test_cypher_injection_blocked(self):
        """set_attribute 必须校验属性名防 Cypher 注入。"""
        from app.profile.service import ProfileService
        ps = ProfileService()
        ps._use_neo4j = False
        # 含特殊字符的属性名应被拒绝
        with pytest.raises(ValueError):
            await ps.set_attribute("u1", "bad`name", "value")
        # 合法属性名应通过
        await ps.set_attribute("u1", "valid_name", "value")

    def test_ssrf_validation_dev_allows_localhost(self):
        """开发环境允许 localhost（便于调试）。"""
        from app.a2a.client import _validate_agent_url
        # dev 环境不拦截（is_dev=True）
        result = _validate_agent_url("http://localhost:8001")
        assert result is None, f"dev localhost 应允许：{result}"


# ==================== 12. 用户认证 ====================


class TestAuth:
    def test_password_hash_and_verify(self):
        """密码哈希可校验，且哈希不可逆推。"""
        from app.auth.jwt_service import hash_password, verify_password

        h = hash_password("mypassword")
        assert h != "mypassword"
        assert verify_password("mypassword", h)
        assert not verify_password("wrong", h)

    def test_password_hash_unique(self):
        """同一密码两次哈希结果不同（盐）。"""
        from app.auth.jwt_service import hash_password

        assert hash_password("abc") != hash_password("abc")

    def test_jwt_create_and_decode(self):
        """JWT 签发与解码一致。"""
        from app.auth.jwt_service import create_token, decode_token

        token = create_token(user_id="u123", tenant_id="tenantX", username="alice")
        payload = decode_token(token)
        assert payload["sub"] == "u123"
        assert payload["tenant"] == "tenantX"
        assert payload["username"] == "alice"

    def test_jwt_invalid_rejected(self):
        """无效 token 被拒绝。"""
        from app.auth.jwt_service import AuthError, decode_token

        with pytest.raises(AuthError):
            decode_token("not.a.valid.token")

    def test_long_password_truncated_safely(self):
        """超长密码（>72字节）不报错，bcrypt 自动截断。"""
        from app.auth.jwt_service import hash_password, verify_password

        long_pwd = "x" * 200
        h = hash_password(long_pwd)
        assert verify_password(long_pwd, h)


# ==================== 13. 多租户隔离 ====================


class TestMultiTenant:
    def test_namespace_isolation_when_enabled(self):
        """多租户开启时，不同租户同 user_id 命名空间隔离。"""
        import app.core.config as cfg
        from app.auth.tenant import memory_namespace

        orig = cfg.get_settings().multi_tenant_enabled
        cfg.get_settings().multi_tenant_enabled = True
        try:
            ns_a = memory_namespace("tenantA", "user1")
            ns_b = memory_namespace("tenantB", "user1")
            assert ns_a != ns_b
            assert ns_a == ("tenant", "tenantA", "user", "user1")
        finally:
            cfg.get_settings().multi_tenant_enabled = orig

    def test_namespace_not_isolated_when_disabled(self):
        """多租户关闭时，退化为不隔离。"""
        from app.auth.tenant import memory_namespace

        ns = memory_namespace("default", "user1")
        assert ns == ("user", "user1")


# ==================== 14. RAG 分块 ====================


class TestRAG:
    def test_chunk_text_basic(self):
        """文本分块产生多个块。"""
        from app.rag.service import chunk_text

        text = "A" * 1200
        chunks = chunk_text(text, size=500, overlap=50)
        assert len(chunks) >= 2
        assert all(len(c) <= 500 for c in chunks)

    def test_chunk_overlap(self):
        """相邻块有重叠（保上下文）。"""
        from app.rag.service import chunk_text

        text = "0123456789" * 100  # 1000 字符
        chunks = chunk_text(text, size=100, overlap=20)
        if len(chunks) >= 2:
            # 第二块开头应与第一块结尾有重叠
            overlap_part = chunks[0][-20:]
            assert chunks[1][:20] == overlap_part

    def test_chunk_empty(self):
        """空文本返回空列表。"""
        from app.rag.service import chunk_text

        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunk_short_text(self):
        """短文本只产生一块。"""
        from app.rag.service import chunk_text

        assert len(chunk_text("短文本", size=500)) == 1


# ==================== 15. 用量统计 ====================


class TestStats:
    def test_cost_estimation_free_model(self):
        """免费模型成本为 0。"""
        from app.services.stats_service import estimate_cost

        assert estimate_cost("glm-4.5-flash", 10000, 5000) == 0.0

    def test_cost_estimation_paid_model(self):
        """收费模型成本 > 0 且随 token 增长。"""
        from app.services.stats_service import estimate_cost

        small = estimate_cost("gpt-4o", 1000, 1000)
        large = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert small > 0
        assert large > small

    def test_cost_unknown_model_uses_default(self):
        """未知模型用保守默认价（不报错）。"""
        from app.services.stats_service import estimate_cost

        cost = estimate_cost("unknown-model-xyz", 1000, 1000)
        assert cost > 0  # 默认价非 0


# ==================== 16. 可观测指标 ====================


class TestObservability:
    def test_record_and_get_metrics(self):
        """请求计数和延迟采集正确。"""
        from app.services.observability import get_metrics, record_request

        record_request("/test-ep", 100.0, 200)
        record_request("/test-ep", 200.0, 200)
        metrics = get_metrics()
        assert metrics["total_requests"] >= 2
        assert "/test-ep" in metrics["avg_latency_ms"]

    def test_metrics_has_infrastructure_status(self):
        """指标含基础设施连通性。"""
        from app.services.observability import get_metrics

        metrics = get_metrics()
        infra = metrics["infrastructure"]
        assert "postgres" in infra
        assert "redis" in infra
        assert "checkpointer_persistent" in infra


# ==================== 17. 限流身份识别 ====================


class TestRateLimit:
    def test_identity_extraction(self):
        """限流中间件能从 ASGI scope 提取身份标识。"""
        from app.middleware.rate_limit import _get_identity

        # 模拟带 IP 的 ASGI scope（无 auth 头）
        scope = {
            "type": "http",
            "headers": [],
            "client": ("192.168.1.1", 12345),
            "path": "/chat",
        }
        identity = _get_identity(scope)
        assert identity.startswith("ip:")
        assert "192.168.1.1" in identity


