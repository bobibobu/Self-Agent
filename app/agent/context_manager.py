"""
上下文窗口管理
--------------
当对话历史过长时，自动把早期消息摘要成一段，避免超出 LLM 的 token 限制。

策略（滑动窗口 + 摘要 + 摘要缓存）：
- 保留最近 N 条消息（完整）
- 把更早的消息用 LLM 摘要成一段 system 消息
- 摘要缓存（按 thread）：同一会话复用上次的摘要，只有新积累的早期消息
  超过 _COMPRESS_EVERY 条才做一次**增量**摘要，而不是每轮全量重摘

为什么需要：
LLM 有 token 上限（如 GLM-4.5 是 128K）。多轮长对话会累积超限，
直接报错。摘要压缩让对话能无限继续，同时保留关键上下文。

摘要缓存为什么重要（2026-08 性能改造）：
ReAct 一轮内 agent 节点可能被调用多次（每次工具返回都会再进 agent），
改造前每次进入都重新摘要一遍——真实 LLM 下长会话每轮对话会多出
1~2 次摘要 LLM 调用，既加延迟又烧 token。缓存 + 迟滞后，
摘要调用从「每轮 1+ 次」降到「每 _COMPRESS_EVERY 条新消息 1 次」。
"""

from __future__ import annotations

from collections import OrderedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.logging import get_logger
from app.llm.factory import get_llm_client
from app.llm.models import ChatMessage, ChatRequest

logger = get_logger(__name__)

# 触发压缩的消息数阈值（超过则压缩早期消息）
DEFAULT_MAX_MESSAGES = 20
# 压缩后保留的近期完整消息数
DEFAULT_KEEP_RECENT = 10
# 迟滞窗口：上次摘要后又积累了多少条早期消息，才做下一次增量摘要。
# 期间直接复用旧摘要（近期消息暂时多保留几条，上限 keep_recent + _COMPRESS_EVERY）。
_COMPRESS_EVERY = 6
# 摘要缓存上限（thread 数），超过后整体清空——会话摘要丢失只是多一次摘要调用，无正确性影响
_SUMMARY_CACHE_MAX = 2000

_SUMMARY_PROMPT = """请把以下对话历史压缩成一段简洁的摘要，保留关键信息（用户意图、已做决定、重要事实、工具调用结果）。
只输出摘要正文，不要其他说明。

对话历史：
{dialog}"""

# 按 thread_key 缓存：{thread_key: {"pos": 已摘要到 dialog 的下标, "id": 边界消息 id, "summary": 摘要文本}}
# id 用来校验边界：checkpointer 的历史是追加式的，若 dialog[pos-1] 的 id 与缓存
# 记录的不一致（如会话被重置/回放），缓存作废走全量摘要。
_summary_cache: OrderedDict[str, dict] = OrderedDict()


def estimate_message_count(messages: list[BaseMessage]) -> int:
    """估算消息数（简单计数；精确 token 计数需 tokenizer，这里用粗略估算）。"""
    return len(messages)


def _summary_msg(summary: str) -> SystemMessage:
    return SystemMessage(content=f"【早期对话摘要】\n{summary}")


def _cache_store(thread_key: str, pos: int, boundary_id: str, summary: str) -> None:
    if len(_summary_cache) >= _SUMMARY_CACHE_MAX:
        _summary_cache.popitem(last=False)
    _summary_cache[thread_key] = {"pos": pos, "id": boundary_id, "summary": summary}


async def compress_if_needed(
    messages: list[BaseMessage],
    *,
    thread_key: str | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> list[BaseMessage]:
    """若消息数超阈值，压缩早期消息为摘要。

    Args:
        messages: 当前全部消息
        thread_key: 会话标识（用 scoped thread_id）。提供时启用摘要缓存：
            同一会话复用上次摘要，新早期消息不足 _COMPRESS_EVERY 条时不重摘。
        max_messages: 触发压缩的消息总数阈值
        keep_recent: 压缩后保留的近期完整消息数

    返回压缩后的消息列表（可能不变）。返回的是新列表，不影响入参。
    """
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

    def aligned(cut: int) -> int:
        while cut < len(dialog) and isinstance(dialog[cut], ToolMessage):
            cut += 1
        return cut

    cut = aligned(max(0, len(dialog) - keep_recent))

    # ---- 摘要缓存命中：边界消息 id 对得上 + 还没攒够新的早期消息 → 直接复用 ----
    entry = _summary_cache.get(thread_key) if thread_key else None
    if entry and 0 < entry["pos"] <= cut:
        boundary = dialog[entry["pos"] - 1]
        if boundary.id is not None and boundary.id == entry["id"]:
            pending = cut - entry["pos"]
            if pending < _COMPRESS_EVERY:
                logger.debug(
                    "上下文压缩：复用缓存摘要（%d 条早期已摘要，%d 条新早期暂留近期）",
                    entry["pos"], pending,
                )
                return system_msgs + [_summary_msg(entry["summary"])] + dialog[entry["pos"]:]
            # 攒够了：增量摘要 = 旧摘要 + 新积累的早期消息
            summary = await _generate_summary(
                dialog[entry["pos"]:cut], base_summary=entry["summary"],
            )
            if summary and dialog[cut - 1].id is not None:
                _cache_store(thread_key, cut, dialog[cut - 1].id, summary)
                logger.info(
                    "上下文压缩（增量）：%d 条新早期消息并入摘要（总保留 %d 条近期）",
                    pending, len(dialog) - cut,
                )
                return system_msgs + [_summary_msg(summary)] + dialog[cut:]
            # 增量摘要失败：退回复用旧摘要，宁可多带几条消息也不失败
            if entry["summary"]:
                return system_msgs + [_summary_msg(entry["summary"])] + dialog[entry["pos"]:]

    # ---- 无缓存/缓存失效：全量摘要 ----
    to_summarize = dialog[:cut]
    summary = await _generate_summary(to_summarize)
    if not summary:
        return messages  # 摘要失败则不压缩
    if thread_key and dialog[cut - 1].id is not None:
        _cache_store(thread_key, cut, dialog[cut - 1].id, summary)

    logger.info("上下文压缩：%d 条早期消息 → 摘要（保留 %d 条近期）", len(to_summarize), len(dialog) - cut)

    # 重组：system 提示 + 摘要 + 近期消息
    return system_msgs + [_summary_msg(summary)] + dialog[cut:]


async def _generate_summary(messages: list[BaseMessage], base_summary: str | None = None) -> str:
    """用轻量 LLM 把消息列表摘要成一段文本。

    base_summary 非空时做增量摘要：先给旧摘要，再给新增消息，
    让 LLM 输出合并后的新摘要——比每次全量重摘省 token 也更快。
    """
    # 拼成对话文本
    dialog_parts = []
    if base_summary:
        dialog_parts.append(f"[此前对话的已有摘要]\n{base_summary}")
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
