"""
A2A Client（调用外部 Agent）
---------------------------
让本 Agent 作为 A2A 客户端，发现并调用其他 A2A agent。

工作流：
1. 从远程 agent 的 /.well-known/agent-card.json 获取 Agent Card（发现）
2. 通过 A2AClient 发送消息（调用）
3. 拿到回复

这样本 Agent 就能编排多 Agent 协作：
    用户 → 本 Agent → 调用「翻译 Agent」→ 拿回译文 → 整合给用户

可用作 LangChain 工具（wrap as tool），让 LLM 自主决定何时委托外部 Agent。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _validate_agent_url(base_url: str) -> str | None:
    """校验目标 Agent URL 是否被允许（防 SSRF）。

    返回 None 表示通过，否则返回拒绝原因字符串。
    检查：白名单（若配置）+ 禁止私网/回环/链路本地地址。
    """
    s = get_settings()
    parsed = urlparse(base_url)
    host = parsed.hostname or ""

    # 白名单检查（生产应配置）
    if s.a2a_delegate_allowlist:
        allowed = {u.strip().rstrip("/") for u in s.a2a_delegate_allowlist.split(",") if u.strip()}
        if base_url.rstrip("/") not in allowed:
            return f"目标 Agent 不在白名单内：{base_url}"

    # 开发态放宽：允许 localhost（生产建议也走白名单）
    if not s.is_dev:
        # 禁止私网/回环/链路本地地址，防 SSRF 打内网
        try:
            # 解析主机名到 IP
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return f"禁止访问内网/回环地址：{host}"
        except (socket.gaierror, ValueError):
            return f"无法解析主机：{host}"

    return None


async def call_remote_agent(base_url: str, message: str) -> str:
    """调用一个远程 A2A Agent。

    带 SSRF 防护：校验目标 URL（白名单 + 私网过滤）。

    Args:
        base_url: 远程 Agent 的基础 URL（如 http://localhost:8001）
        message: 要发送给该 Agent 的消息

    Returns:
        该 Agent 的文本回复
    """
    # SSRF 防护
    deny_reason = _validate_agent_url(base_url)
    if deny_reason:
        logger.warning("delegate 被拒绝：%s", deny_reason)
        return deny_reason

    from a2a.client import A2ACardResolver, A2AClient
    from a2a.types import MessageSendParams

    async with httpx.AsyncClient(timeout=60) as http:
        # 1. 发现：获取远程 Agent Card
        resolver = A2ACardResolver(httpx_client=http, base_url=base_url)
        try:
            card = await resolver.get_agent_card()
            logger.info("发现远程 Agent: %s (%s)", card.name, base_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("无法获取远程 Agent Card %s：%s", base_url, e)
            return f"无法连接 Agent {base_url}：{e}"

        # 2. 调用
        client = A2AClient(httpx_client=http, agent_card=card)
        params = MessageSendParams(
            message={
                "role": "user",
                "parts": [{"type": "text", "text": message}],
                "messageId": f"msg-{id(message)}",
                "contextId": f"ctx-{id(base_url)}",
            }
        )
        try:
            response = await client.send_message(params)
            # 从响应中提取文本
            return _extract_text(response)
        except Exception as e:  # noqa: BLE001
            logger.exception("调用远程 Agent 失败")
            return f"调用 Agent {base_url} 失败：{e}"


def _extract_text(response) -> str:
    """从 A2A 响应对象中提取文本内容。"""
    if response is None:
        return "(空响应)"

    # 尝试 artifacts（任务产物）
    artifacts = getattr(response, "artifacts", None)
    if artifacts:
        texts = []
        for art in artifacts:
            for p in getattr(art, "parts", []):
                txt = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
                if txt:
                    texts.append(txt)
        if texts:
            return "\n".join(texts)

    # 尝试 message parts（消息内容）
    msg = getattr(response, "message", None)
    if msg:
        texts = []
        for p in getattr(msg, "parts", []):
            txt = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
            if txt:
                texts.append(txt)
        if texts:
            return "\n".join(texts)

    # 直接看 response 自身的 parts
    for p in getattr(response, "parts", []) or []:
        txt = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
        if txt:
            return txt

    return str(response)[:500]


# ---------- 作为 LangChain 工具暴露（LLM 可自主调用） ----------


@tool
async def delegate_to_agent(base_url: str, message: str) -> str:
    """委托任务给另一个 A2A Agent 执行。

    当本 Agent 无法独立完成某任务（如需要专业翻译、特定领域分析）时，
    可调用其他专门的 Agent 协作完成。

    Args:
        base_url: 目标 Agent 的 URL（如 http://localhost:8001）
        message: 要委托的任务描述
    """
    result = await call_remote_agent(base_url, message)
    logger.info("delegate_to_agent %s → %s", base_url, result[:80])
    return result
