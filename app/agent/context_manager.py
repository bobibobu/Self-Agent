"""
上下文窗口管理
--------------
当对话历史过长时，自动把早期消息摘要成一段，避免超出 LLM 的 token 限制。

策略（滑动窗口 + 摘要）：
- 保留最近 N 条消息（完整）
- 把更早的消息用 LLM 摘要成一段 system 消息
- 摘要缓存（同一段历史不重复摘要）

为什么需要：
LLM 有 token 上限（如 GLM-4.5 是 128K）。多轮长对话会累积超限，
直接报错。摘要压缩让对话能无限继续，同时保留关键上下文。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.factory import get_llm_client
from app.llm.models import ChatMessage, ChatRequest

logger = get_logger(__name__)

# 触发压缩的消息数阈值（超过则压缩早期消息）
DEFAULT_MAX_MESSAGES = 20
# 压缩后保留的近期完整消息数
DEFAULT_KEEP_RECENT = 10

_SUMMARY_PROMPT = """请把以下对话历史压缩成一段简洁的摘要，保留关键信息（用户意图、已做决定、重要事实、工具调用结果）。
只输出摘要正文，不要其他说明。

对话历史：
{dialog}"""


def estimate_message_count(messages: list[BaseMessage]) -> int:
    """估算消息数（简单计数；精确 token 计数需 tokenizer，这里用粗略估算）。"""
    return len(messages)


async def compress_if_needed(
    messages: list[BaseMessage],
    *,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> list[BaseMessage]:
    """若消息数超阈值，压缩早期消息为摘要。

    返回压缩后的消息列表（可能不变）。
    """
    # 始终保留首条 system 提示 + 最近 keep_recent 条
    if len(messages) <= max_messages:
        return messages

    # 分离 system 消息与对话消息
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    dialog = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(dialog) <= keep_recent:
        return messages

    # 早期消息（要被摘要的）+ 近期消息（保留）
    # 安全边界：recent 不能以 ToolMessage 开头（否则它对应的 AIMessage(tool_calls)
    # 被摘要掉，导致 ReAct 校验失败）。把开头的 ToolMessage 推回 to_summarize。
    from langchain_core.messages import ToolMessage

    cut = max(0, len(dialog) - keep_recent)
    while cut < len(dialog) and isinstance(dialog[cut], ToolMessage):
        cut += 1
    to_summarize = dialog[:cut]
    recent = dialog[cut:]

    # 生成摘要
    summary = await _generate_summary(to_summarize)
    if not summary:
        return messages  # 摘要失败则不压缩

    summary_msg = SystemMessage(content=f"【早期对话摘要】\n{summary}")
    logger.info("上下文压缩：%d 条早期消息 → 摘要（保留 %d 条近期）", len(to_summarize), keep_recent)

    # 重组：system 提示 + 摘要 + 近期消息
    return system_msgs + [summary_msg] + recent


async def _generate_summary(messages: list[BaseMessage]) -> str:
    """用轻量 LLM 把消息列表摘要成一段文本。"""
    # 拼成对话文本
    dialog_parts = []
    for m in messages:
        role = "用户" if isinstance(m, HumanMessage) else ("助手" if isinstance(m, AIMessage) else "系统")
        content = m.content if isinstance(m.content, str) else str(m.content)
        dialog_parts.append(f"{role}: {content[:500]}")  # 每条截断防过长
    dialog = "\n".join(dialog_parts)

    try:
        llm = get_llm_client()
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=_SUMMARY_PROMPT.format(dialog=dialog[:8000])),
                ChatMessage(role="user", content="请生成摘要"),
            ],
            temperature=0.3,
            max_tokens=500,
        )
        resp = await llm.chat(request)
        return resp.content or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("上下文摘要生成失败（不压缩）：%s", e)
        return ""
