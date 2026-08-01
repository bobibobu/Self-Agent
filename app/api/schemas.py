"""
API 请求/响应 schema
--------------------
对外暴露的接口数据模型，与内部 LLM 模型解耦。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求。"""

    message: str = Field(..., max_length=32000, description="用户输入")
    thread_id: str = Field(default="default", max_length=128, description="会话 ID，同 ID 续接上下文")
    user_id: str | None = Field(None, max_length=128, description="用户 ID（预留画像关联）")
    kb_ids: list[str] | None = Field(None, description="RAG 知识库 ID 列表，对话时检索增强")


class ChatResponse(BaseModel):
    """对话响应。"""

    reply: str
    thread_id: str
    provider: str | None = None


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
    app: str
    version: str
    default_provider: str


# ---------- 记忆 ----------


class AddMemoryRequest(BaseModel):
    """添加长期记忆。"""

    user_id: str = Field(..., max_length=128)
    content: str = Field(..., max_length=5000, description="记忆内容，如'用户偏好简洁回答'")
    key: str | None = Field(None, max_length=128)


class SearchMemoryRequest(BaseModel):
    """语义检索记忆。"""

    user_id: str
    query: str
    limit: int = 5


# ---------- 用户画像 ----------


class AddInterestRequest(BaseModel):
    user_id: str
    interest: str


class AddPreferenceRequest(BaseModel):
    user_id: str
    key: str
    value: str
