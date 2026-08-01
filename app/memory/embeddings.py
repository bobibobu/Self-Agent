"""
向量化（Embedding）层
=====================
长期记忆与 RAG 的语义检索都依赖它。

为什么单独一层：
    原先记忆/RAG 用的是「按字符位置累加 ASCII 码」的哈希伪向量，
    它只反映字符分布、与语义无关——实测 cos("猫","猫咪是一种宠物")=0.43，
    而 cos("猫","tac")=0.64，一个无关的拉丁串比语义相关句子得分还高。
    也就是说检索结果基本等同随机，RAG 模块形同虚设。

现在的策略：
    配了 key            → 走真实 embedding 模型（GLM/OpenAI 兼容的 /embeddings 端点）
    没配 key            → 回退哈希伪向量，并在启动时打 WARNING 明确告知「语义检索已降级」

GLM 与 OpenAI 的 /embeddings 是同一套协议，所以复用同一个 AsyncOpenAI 客户端。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 各 provider 的默认 embedding 模型与维度
_DEFAULTS: dict[str, tuple[str, int]] = {
    "glm": ("embedding-3", 2048),
    "openai": ("text-embedding-3-small", 1536),
}

# 哈希伪向量的维度（仅降级时使用）
HASH_EMBED_DIMS = 256


def hash_embed(texts: Sequence[str]) -> list[list[float]]:
    """确定性哈希伪向量（**非语义**，仅在未配置 embedding key 时兜底）。

    保留它是为了「没有任何 key 也能把项目跑起来」，
    但它检索出来的结果没有语义意义，不要在生产依赖。
    """

    def _one(text: str) -> list[float]:
        vec = [0.0] * HASH_EMBED_DIMS
        for i, ch in enumerate(text):
            vec[i % HASH_EMBED_DIMS] = (vec[i % HASH_EMBED_DIMS] + ord(ch)) / 1000.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    return [_one(t) for t in texts]


def _resolve_provider() -> str | None:
    """决定用哪个 provider 做 embedding。返回 None 表示没有可用的 key。"""
    s = get_settings()
    choice = s.embedding_provider
    if choice == "none":
        return None
    if choice in ("glm", "openai"):
        key = s.glm_api_key if choice == "glm" else s.openai_api_key
        return choice if key else None
    # auto：优先跟随默认 LLM provider，其次任意一个有 key 的
    order = [s.llm_default_provider, "glm", "openai"]
    for p in order:
        if p == "glm" and s.glm_api_key:
            return "glm"
        if p == "openai" and s.openai_api_key:
            return "openai"
    return None


@lru_cache
def embedding_config() -> tuple[str | None, str, int]:
    """返回 (provider, model, dims)。provider 为 None 表示降级到哈希向量。"""
    s = get_settings()
    provider = _resolve_provider()
    if provider is None:
        return None, "", HASH_EMBED_DIMS
    default_model, default_dims = _DEFAULTS[provider]
    model = s.embedding_model or default_model
    dims = s.embedding_dims or default_dims
    return provider, model, dims


@lru_cache
def _client(provider: str):
    from openai import AsyncOpenAI

    s = get_settings()
    if provider == "glm":
        return AsyncOpenAI(api_key=s.glm_api_key, base_url=s.glm_base_url, timeout=s.llm_timeout_seconds)
    return AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url, timeout=s.llm_timeout_seconds)


async def aembed(texts: Sequence[str]) -> list[list[float]]:
    """异步批量向量化。LangGraph 的 index.embed 直接吃这个函数。

    远端失败时回退哈希向量而不是抛异常——检索退化好过整条对话链路挂掉。
    """
    provider, model, dims = embedding_config()
    if provider is None:
        return hash_embed(texts)

    try:
        kwargs: dict = {"model": model, "input": list(texts)}
        # OpenAI 的 text-embedding-3-* 支持降维；GLM 的 embedding-3 也支持 dimensions
        _, default_dims = _DEFAULTS[provider]
        if dims and dims != default_dims:
            kwargs["dimensions"] = dims
        resp = await _client(provider).embeddings.create(**kwargs)
        return [item.embedding for item in resp.data]
    except Exception as e:  # noqa: BLE001
        logger.warning("embedding 调用失败，本次回退哈希向量（检索质量下降）：%s", e)
        return hash_embed(texts)


def get_embed_fn() -> Callable[[Sequence[str]], object]:
    """给 LangGraph 的 index 配置用的 embed 函数。"""
    return aembed


def log_embedding_status() -> None:
    """启动时打一条明确的状态日志（降级必须可见）。"""
    provider, model, dims = embedding_config()
    if provider is None:
        logger.warning(
            "⚠️ 未配置 embedding key，长期记忆与 RAG 的语义检索已降级为哈希伪向量"
            "（检索结果无语义意义）。配置 GLM_API_KEY 或 OPENAI_API_KEY 即可启用真实向量检索。"
        )
    else:
        logger.info("向量检索：%s / %s（%d 维）", provider, model, dims)
