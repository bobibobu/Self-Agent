"""
LLM 客户端工厂
--------------
按配置（LLM_DEFAULT_PROVIDER）创建对应的 LLMClient 实例。
GLM 与 OpenAI 共用 OpenAILikeClient（OpenAI 兼容协议），仅配置不同。

支持运行时切换 provider：
    client = get_llm_client()                       # 默认 provider
    client = get_llm_client(provider="anthropic")   # 指定 provider
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from app.core.config import get_settings
from app.core.exceptions import ConfigError
from app.llm.base import LLMClient
from app.llm.providers.anthropic import AnthropicClient
from app.llm.providers.openai_like import OpenAILikeClient

ProviderName = Literal["glm", "openai", "anthropic"]


def create_llm_client(provider: ProviderName) -> LLMClient:
    """创建指定 provider 的 LLM 客户端（每次返回新实例）。"""
    s = get_settings()

    common = {"timeout": s.llm_timeout_seconds, "max_retries": s.llm_max_retries}

    if provider == "glm":
        if not s.glm_api_key:
            raise ConfigError("GLM_API_KEY 未配置，请在 .env 中设置")
        return OpenAILikeClient(
            api_key=s.glm_api_key,
            base_url=s.glm_base_url,
            default_model=s.glm_model,
            provider_name="glm",
            **common,
        )

    if provider == "openai":
        if not s.openai_api_key:
            raise ConfigError("OPENAI_API_KEY 未配置")
        return OpenAILikeClient(
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            default_model=s.openai_model,
            provider_name="openai",
            **common,
        )

    if provider == "anthropic":
        if not s.anthropic_api_key:
            raise ConfigError("ANTHROPIC_API_KEY 未配置")
        return AnthropicClient(
            api_key=s.anthropic_api_key,
            base_url=s.anthropic_base_url,
            default_model=s.anthropic_model,
            **common,
        )

    raise ConfigError(f"未知的 LLM provider: {provider}")


@lru_cache
def get_llm_client(provider: ProviderName | None = None) -> LLMClient:
    """
    获取 LLM 客户端单例。
    provider=None 时用配置中的默认 provider（LLM_DEFAULT_PROVIDER）。
    """
    s = get_settings()
    target = provider or s.llm_default_provider  # type: ignore[arg-type]
    return create_llm_client(target)  # type: ignore[arg-type]


def reset_llm_clients() -> None:
    """清空客户端缓存，让下一次调用按**当前**配置重建。

    供运行时配置热替换（/admin/llm-config）调用：换 key / 换 provider 后
    不重启进程即可生效。lru_cache 单例持有旧的 key，必须显式失效。
    """
    get_llm_client.cache_clear()
