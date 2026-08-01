"""
多协议 LLM 抽象层
==================
统一封装 GLM(智谱) / OpenAI / Anthropic 三套主流大模型协议，
对外暴露统一的 `LLMClient` 接口，上层（Agent）无需关心底层差异。

设计要点：
- **GLM 走 OpenAI 兼容协议**：智谱 /chat/completions 端点完全兼容 OpenAI 格式，
  只需把 base_url 换成 https://open.bigmodel.cn/api/paas/v4/ 即可，零适配。
- **统一数据模型**：`ChatMessage` / `ChatRequest` / `ChatResponse` 与 provider 无关。
- **流式 & 工具调用**：统一接口同时支持 `chat()` 一次性返回与 `stream_chat()` 流式。
- **工厂路由**：`get_llm_client()` 按配置返回对应 provider 实现。

详见 docs/02-modules/01-llm-layer.md
"""

from app.llm.base import LLMClient
from app.llm.factory import get_llm_client
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    ToolDefinition,
    Usage,
)

__all__ = [
    "LLMClient",
    "get_llm_client",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ToolCall",
    "ToolDefinition",
    "Usage",
]
