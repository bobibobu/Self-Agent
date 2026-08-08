"""
结构化输出契约测试
==================
2026-08 改造：让 LLM 输出符合 JSON Schema 的结构化结果，治「格式幻觉」。

测试层级：
1. ChatRequest 模型层：response_format 字段能正确存取
2. bridge 层：build_chat_request 透传 response_format
3. provider 层：OpenAI 兼容 client 把 response_format 传给底层 SDK
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.nodes.bridge import build_chat_request
from app.llm.models import ChatRequest
from langchain_core.messages import HumanMessage


class TestChatRequestResponseFormat:
    """ChatRequest 的 response_format 字段。"""

    def test_default_is_none(self):
        req = ChatRequest(messages=[])
        assert req.response_format is None, "默认应为 None（自由文本，向后兼容）"

    def test_can_set_json_schema(self):
        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "Decision",
                "schema": {
                    "type": "object",
                    "properties": {"approved": {"type": "boolean"}},
                    "required": ["approved"],
                },
                "strict": True,
            },
        }
        req = ChatRequest(messages=[], response_format=schema)
        assert req.response_format == schema


class TestBridgePassesResponseFormat:
    """build_chat_request 透传 response_format。"""

    def test_none_when_not_specified(self):
        req = build_chat_request([HumanMessage(content="hi")], None)
        assert req.response_format is None

    def test_passed_through(self):
        schema = {"type": "json_object"}
        req = build_chat_request([HumanMessage(content="hi")], None, response_format=schema)
        assert req.response_format == schema


class TestOpenAILikeProviderPassesResponseFormat:
    """OpenAI 兼容 provider 把 response_format 传给底层 SDK。"""

    @pytest.mark.asyncio
    async def test_chat_passes_response_format(self):
        from app.llm.providers.openai_like import OpenAILikeClient
        from app.llm.models import ChatMessage

        # 用 mock 的 client，捕获 create 调用的 kwargs
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"approved": true}'
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.model = "test"
        mock_resp.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        c = OpenAILikeClient(
            api_key="sk-test", base_url="http://x", default_model="test", provider_name="test",
        )
        c._client = mock_client

        schema = {"type": "json_object"}
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="decide")],
            response_format=schema,
        )
        await c.chat(req)

        # create 应被调用，且 response_format 在 kwargs 里
        mock_client.chat.completions.create.assert_called_once()
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs.get("response_format") == schema, (
            "OpenAI 兼容 provider 应把 response_format 透传给底层 SDK"
        )

    @pytest.mark.asyncio
    async def test_chat_omits_response_format_when_none(self):
        """不指定时不应传 response_format（保持向后兼容）。"""
        from app.llm.providers.openai_like import OpenAILikeClient
        from app.llm.models import ChatMessage

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.model = "test"
        mock_resp.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        c = OpenAILikeClient(
            api_key="sk-test", base_url="http://x", default_model="test", provider_name="test",
        )
        c._client = mock_client

        req = ChatRequest(messages=[ChatMessage(role="user", content="hi")])
        await c.chat(req)

        _, kwargs = mock_client.chat.completions.create.call_args
        assert "response_format" not in kwargs, "未指定时不应传 response_format"
