"""
RAG 知识库路由
--------------
- POST /rag/kb/{kb_id}        上传文档（文本内容）
- GET  /rag/kb/{kb_id}/search 语义检索
- DELETE /rag/kb/{kb_id}      删除知识库
- POST /chat 支持 kb_ids 参数  → 对话时自动检索增强
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.rag.service import get_rag_service

router = APIRouter()


class IngestRequest(BaseModel):
    content: str = Field(..., max_length=500000, description="文档文本内容")
    source: str = Field("", description="来源标记（文件名等）")


@router.post("/rag/kb/{kb_id}", tags=["RAG"])
async def ingest(kb_id: str, req: IngestRequest):
    """上传文档到知识库（自动分块+向量化）。"""
    count = await get_rag_service().ingest(kb_id, req.content, source=req.source)
    return {"status": "ok", "kb_id": kb_id, "chunks": count}


@router.get("/rag/kb/{kb_id}/search", tags=["RAG"])
async def search(kb_id: str, query: str, limit: int = 4):
    """语义检索知识库。"""
    results = await get_rag_service().search(kb_id, query, limit=limit)
    return {"count": len(results), "results": results}


@router.delete("/rag/kb/{kb_id}", tags=["RAG"])
async def delete_kb(kb_id: str):
    """删除整个知识库。"""
    count = await get_rag_service().delete_kb(kb_id)
    return {"status": "ok", "deleted": count}
