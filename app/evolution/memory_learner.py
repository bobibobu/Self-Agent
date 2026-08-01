"""
能力 A：自动记忆画像学习
------------------------
对话后异步触发，用轻量 LLM 从本轮对话中抽取「值得记住的事实」：
- 用户兴趣/偏好 → 写入用户画像（Neo4j）
- 重要事实/约定 → 写入长期记忆（Store）

抽取用结构化输出（JSON），确保结果可解析、可控。
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.llm.factory import get_llm_client
from app.llm.models import ChatMessage, ChatRequest

logger = get_logger(__name__)

# 抽取提示词：让 LLM 从对话中识别值得记住的信息，输出结构化 JSON
_EXTRACT_PROMPT = """你是一个信息抽取助手。分析以下用户与助手的对话，抽取「值得长期记住」的用户信息。

只抽取明确的、稳定的信息（不要抽取临时性、一次性的内容）。分类为：
- interests：用户的兴趣领域（如"编程""机器学习""摄影"）
- preferences：用户的使用偏好（如"偏好简洁回答""喜欢中文"）
- facts：关于用户的重要事实（如"是 Python 开发者""在做微服务项目"）

如果本轮对话没有值得记住的信息，返回空数组。

只输出 JSON，不要其他文字。格式：
{"interests": ["..."], "preferences": {"key": "value"}, "facts": ["..."]}"""


async def learn_from_conversation(
    user_id: str,
    user_message: str,
    agent_reply: str,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """从一轮对话中抽取并保存用户记忆/画像（按租户隔离）。

    fire-and-forget 调用：失败只记日志，不抛异常。

    Returns:
        抽取到的信息摘要（调试用）
    """
    if not user_id:
        return {"skipped": "no user_id"}

    try:
        llm = get_llm_client()
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=_EXTRACT_PROMPT),
                ChatMessage(role="user", content=f"用户说：{user_message}\n助手回：{agent_reply}"),
            ],
            temperature=0.1,  # 低温度，确保抽取稳定
        )
        resp = await llm.chat(request)
        extracted = _parse_extraction(resp.content or "")
        if not _has_content(extracted):
            logger.debug("Hermes 学习：本轮无可抽取信息 user=%s", user_id)
            return {"extracted": extracted, "saved": False}

        # 写入画像与记忆（按租户）
        saved = await _save_learned(user_id, extracted, tenant_id)
        logger.info("Hermes 学习完成 user=%s tenant=%s：%s", user_id, tenant_id, saved)
        return {"extracted": extracted, "saved": saved}

    except Exception as e:  # noqa: BLE001
        logger.warning("Hermes 学习失败（不影响主流程）：%s", e)
        return {"error": str(e)}


def _parse_extraction(text: str) -> dict[str, Any]:
    """解析 LLM 输出的 JSON（容错：可能含 markdown 代码块）。"""
    text = text.strip()
    # 去除可能的 ```json ... ``` 包裹
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(text)
        return {
            "interests": data.get("interests", []) or [],
            "preferences": data.get("preferences", {}) or {},
            "facts": data.get("facts", []) or [],
        }
    except json.JSONDecodeError:
        logger.debug("Hermes 学习：JSON 解析失败：%s", text[:100])
        return {"interests": [], "preferences": {}, "facts": []}


def _has_content(extracted: dict[str, Any]) -> bool:
    return bool(extracted.get("interests") or extracted.get("preferences") or extracted.get("facts"))


async def _save_learned(user_id: str, extracted: dict[str, Any], tenant_id: str = "default") -> dict[str, int]:
    """把抽取结果写入画像（Neo4j）和长期记忆（Store），按租户隔离。"""
    from app.auth.tenant import scoped_user_id

    saved = {"interests": 0, "preferences": 0, "facts": 0}
    scoped_uid = scoped_user_id(tenant_id, user_id)

    # 兴趣 → 用户画像（用租户作用域的 user_id）
    for interest in extracted.get("interests", []):
        try:
            from app.profile.service import get_profile_service
            await get_profile_service().add_interest(scoped_uid, interest)
            saved["interests"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("写入兴趣失败：%s", e)

    # 偏好 → 用户画像
    for key, value in extracted.get("preferences", {}).items():
        try:
            from app.profile.service import get_profile_service
            await get_profile_service().add_preference(scoped_uid, key, str(value))
            saved["preferences"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("写入偏好失败：%s", e)

    # 事实 → 长期记忆（按租户 namespace）
    for fact in extracted.get("facts", []):
        try:
            from app.memory.store import get_memory_service
            await (await get_memory_service()).add_memory(user_id, fact, tenant_id=tenant_id)
            saved["facts"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("写入记忆失败：%s", e)

    return saved
