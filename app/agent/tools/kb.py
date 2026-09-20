"""知识库检索工具（Agentic RAG）
--------------------------------
把 RAG 检索从「每轮固定注入」升级为「Agent 自己决定何时检索」的工具：

- 旧行为：请求带 kb_ids 时，每轮都检索一次并注入系统提示——不管这轮
  问题是否需要知识库，检索成本固定付、无关内容照样挤占上下文。
- 新行为：search_knowledge_base 作为普通工具注册进注册表，模型按需调用，
  还能换着 query 多检索几轮（Agentic RAG 的多跳/迭代形态）。

知识库范围与租户从图的 configurable 里取（见 graph.run_agent /
_stream_graph 组装 config 的地方）——工具自身不接受 kb_ids 参数，
模型无法越权检索未关联给本次对话（本次租户）的知识库。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.core.logging import get_logger

logger = get_logger(__name__)

# 单块内容在工具输出里的上限（整条输出还会被 tools_node 按
# TOOL_RESULT_MAX_CHARS 统一截断，这里只是防单块独占）
_PER_CHUNK_CHARS = 600


def _kb_context(config: RunnableConfig | None) -> tuple[list[str], str]:
    """从图的 configurable 里取本次对话关联的知识库与租户。"""
    conf: dict[str, Any] = (config or {}).get("configurable") or {}
    kb_ids = conf.get("kb_ids") or []
    tenant_id = str(conf.get("tenant_id") or "default")
    return [str(k) for k in kb_ids if k], tenant_id


@tool
async def search_knowledge_base(
    query: str,
    kb_id: str = "",
    limit: int = 4,
    config: RunnableConfig = None,  # type: ignore[assignment]  # langchain 运行时注入，见 _get_runnable_config_param
) -> str:
    """在当前对话关联的知识库中检索相关资料（混合检索：语义 + 关键词融合）。

    当用户的问题可能需要知识库文档里的内容（产品手册、上传的资料、内部文档）
    才能回答时调用本工具；普通闲聊或已有足够上下文时不要调用。
    可以换不同的关键词多次调用以覆盖不同方面。

    Args:
        query: 检索 query。用与文档内容相近的措辞，可包含专有名词/代号/编号
            （关键词通道对字面精确命中很强）。
        kb_id: 可选。只检索指定知识库；留空则检索本次对话关联的全部知识库。
        limit: 返回块数上限，默认 4，最大 10。
    """
    from app.rag.service import get_rag_service

    limit = max(1, min(int(limit or 4), 10))
    kb_ids, tenant_id = _kb_context(config)
    if kb_id:
        # 允许模型只看某一个库，但必须是本次对话关联过的——防越权
        if kb_id not in kb_ids:
            return (
                f"错误：知识库 {kb_id} 未关联到本次对话。"
                f"可用的知识库：{', '.join(kb_ids) if kb_ids else '（无）'}"
            )
        kb_ids = [kb_id]
    if not kb_ids:
        return (
            "当前对话没有关联知识库。若用户希望基于文档回答，"
            "请让用户先上传文档或在对话请求里带上 kb_ids。"
        )

    rag = get_rag_service()
    # 多知识库并发检索后合并（与 build_context 相同的语义）
    try:
        per_kb = await asyncio.gather(
            *(rag.search(kb, query, limit=limit, tenant_id=tenant_id) for kb in kb_ids),
            return_exceptions=True,
        )
    except Exception as e:  # noqa: BLE001
        return f"知识库检索出错：{e}"

    merged: list[dict[str, Any]] = []
    for kb, per_kb_results in zip(kb_ids, per_kb, strict=True):
        if isinstance(per_kb_results, BaseException):
            logger.warning("知识库 %s 检索异常：%s", kb, per_kb_results)
            continue
        merged.extend(per_kb_results)

    if not merged:
        return f"知识库中没有找到与「{query}」相关的内容。可以换个措辞重试。"

    lines = [f"知识库检索到 {len(merged)} 条相关内容（query={query}）："]
    for i, hit in enumerate(merged, 1):
        content = (hit.get("content") or "").strip()[:_PER_CHUNK_CHARS]
        src = hit.get("source") or "未知来源"
        channels = "/".join(hit.get("match") or [])
        lines.append(f"[{i}] 来源: {src}（命中: {channels}）\n{content}")
    return "\n\n".join(lines)
