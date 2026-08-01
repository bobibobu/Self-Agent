"""
能力 B：反思 + 提示词自优化（Reflector）
---------------------------------------
定期/手动触发反思循环：
1. 从 MongoDB 取近期对话样本
2. 让 LLM 自评当前提示词下的回答质量（打分 + 指出问题）
3. 根据反馈生成优化版系统提示词
4. 存为新版本（可回滚）

安全设计：
- 优化不直接覆盖，存版本，可回滚
- 评分过低时不自动采纳（需人工确认或达到阈值）
- 反思本身用 LLM，结果做基本校验（长度/非空）
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.evolution.prompt_store import get_current_prompt, get_current_version, save_version
from app.llm.factory import get_llm_client
from app.llm.models import ChatMessage, ChatRequest

logger = get_logger(__name__)

_REFLECT_PROMPT = """你是一个 Agent 提示词优化专家。分析以下对话样本和当前系统提示词，评估回答质量并提出改进。

当前系统提示词：
---
{current_prompt}
---

近期对话样本（用户问 → 助手答）：
{samples}

请：
1. 评估当前提示词下回答的总体质量（0-10 分）
2. 指出 2-3 个可改进的方向
3. 给出优化后的完整系统提示词（直接可用，不要解释）

只输出 JSON：{"score": 8.5, "issues": ["问题1","问题2"], "improved_prompt": "优化后的完整提示词"}"""


async def reflect(
    *,
    sample_limit: int = 5,
    auto_apply_threshold: float = 6.0,
) -> dict[str, Any]:
    """执行一次反思循环。

    Args:
        sample_limit: 回顾的对话样本数
        auto_apply_threshold: 自评分低于此值时不自动采纳优化（避免越改越差）

    Returns:
        反思结果（评分、问题、是否采纳、新版本号）
    """
    current_prompt = get_current_prompt()
    current_version = get_current_version()

    # 取近期对话样本
    samples = await _fetch_recent_samples(sample_limit)
    if not samples:
        return {"status": "skipped", "reason": "无对话样本可供反思"}

    # 让 LLM 反思
    llm = get_llm_client()
    samples_text = "\n".join(
        f"- 问：{s['user_message']}\n  答：{s['agent_reply']}" for s in samples
    )
    request = ChatRequest(
        messages=[
            ChatMessage(
                role="system",
                content=_REFLECT_PROMPT.format(current_prompt=current_prompt, samples=samples_text),
            ),
            ChatMessage(role="user", content="请开始反思与优化"),
        ],
        temperature=0.3,
    )

    try:
        resp = await llm.chat(request)
    except Exception as e:  # noqa: BLE001
        logger.exception("Hermes 反思 LLM 调用失败")
        return {"status": "error", "reason": str(e)}

    result = _parse_reflection(resp.content or "")
    if not result.get("improved_prompt"):
        return {"status": "skipped", "reason": "未生成有效优化提示词", "raw": resp.content[:200]}

    score = result.get("score", 0)
    improved = result["improved_prompt"]

    # 校验优化提示词基本合理性
    if len(improved) < 20:
        return {"status": "skipped", "reason": "优化提示词过短，可能无效"}

    # 决定是否自动采纳
    applied = False
    new_version = None
    if score >= auto_apply_threshold:
        new_version = save_version(
            improved,
            source="hermes_reflect",
            score=score,
            note="; ".join(result.get("issues", [])),
        )
        applied = True
        logger.info("Hermes 反思完成：评分 %.1f，已采纳为新版本 %s", score, new_version)
    else:
        logger.info("Hermes 反思完成：评分 %.1f < 阈值 %.1f，未自动采纳", score, auto_apply_threshold)

    return {
        "status": "ok",
        "previous_version": current_version,
        "new_version": new_version,
        "applied": applied,
        "score": score,
        "issues": result.get("issues", []),
    }


async def _fetch_recent_samples(limit: int) -> list[dict[str, Any]]:
    """从 MongoDB 取近期对话样本。"""
    try:
        from app.db.manager import db_manager

        if db_manager.mongo is None:
            return []
        cursor = db_manager.mongo["conversation_events"].find(
            {"error": None, "agent_reply": {"$exists": True, "$ne": ""}}
        ).sort("ts", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [
            {"user_message": d.get("user_message", ""), "agent_reply": d.get("agent_reply", "")}
            for d in docs
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("取对话样本失败：%s", e)
        return []


def _parse_reflection(text: str) -> dict[str, Any]:
    """解析反思 LLM 输出的 JSON（容错）。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(text)
        return {
            "score": float(data.get("score", 0)),
            "issues": data.get("issues", []) or [],
            "improved_prompt": data.get("improved_prompt", "") or "",
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.debug("反思结果 JSON 解析失败：%s", text[:100])
        return {}
