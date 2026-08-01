"""
A2A Agent Executor
------------------
把本 Agent 的核心能力（run_agent）包装成 A2A 协议的 AgentExecutor。
这样其他 A2A 客户端就能像调用一个普通 Agent 一样调用我们。

注意：a2a-sdk 1.1.x 使用 protobuf 风格的消息类型（Part/Artifact/AgentCard），
与早期 pydantic 风格的 API 有差异。本文件按 1.1.x 的实际 API 编写。
"""

from __future__ import annotations

import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
)

from app.agent.graph import run_agent
from app.core.logging import get_logger

logger = get_logger(__name__)


class SelfAgentExecutor(AgentExecutor):
    """把 Self-Agent 暴露为 A2A 可执行 Agent。

    收到外部 Agent 的消息 → 调用内部 run_agent → 返回回复。
    """

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """执行一次 A2A 任务。"""
        user_input = context.get_user_input()
        thread_id = context.context_id or f"a2a-{uuid.uuid4().hex[:8]}"
        logger.info("A2A 收到请求 thread=%s: %s", thread_id, user_input[:80])

        async with TaskUpdater(event_queue, context.task_id, context.context_id) as updater:
            await updater.start_work()
            try:
                # 调用本 Agent 核心
                result = await run_agent(user_input, thread_id)
                reply = result["reply"]

                # 把回复作为 artifact 返回（Part 用 protobuf text 字段）
                await updater.add_artifact(
                    parts=[Part(text=reply)],
                    name="agent_reply",
                )
                await updater.complete()
                logger.info("A2A 任务完成 thread=%s", thread_id)
            except Exception as e:  # noqa: BLE001
                logger.exception("A2A 任务执行失败")
                # 失败时标记 failed（a2a-sdk 的 failed 可能要求 message，try 兜底）
                try:
                    await updater.failed()
                except Exception:  # noqa: BLE001
                    logger.warning("A2A failed 状态更新失败")

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """取消任务（当前实现为空，本 Agent 不支持中途取消）。"""
        logger.warning("A2A cancel 被调用（暂不支持）：task=%s", context.task_id)


def build_agent_card(base_url: str = "http://localhost:8000") -> AgentCard:
    """构造本 Agent 的 Agent Card（A2A 的能力清单，供发现）。

    a2a-sdk 1.1.x 的 AgentCard 字段（v1.0 协议风格）：
    name/description/version/capabilities/skills/default_input_modes/default_output_modes 等。
    """
    return AgentCard(
        name="Self-Agent",
        description="企业级通用个人助理 Agent，支持工具调用、记忆与用户画像",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(id="chat", name="对话问答", description="通用知识问答与多轮对话", tags=["chat", "qa"]),
            AgentSkill(id="tools", name="工具调用", description="支持计算器、时间、天气等工具", tags=["tools"]),
            AgentSkill(id="memory", name="记忆增强", description="接入长期记忆与画像的个性化对话", tags=["memory"]),
        ],
    )
