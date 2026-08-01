"""
文件/图片上传路由
-----------------
- POST /upload          上传文件（文本自动提取内容，可选入 RAG）
- GET  /uploads         获取已上传文件列表

安全：
- 扩展名白名单（拒绝可执行/脚本类）
- 文件名清洗（取 basename 防路径穿越）
- 不返回服务器绝对路径
- 大小限制

支持类型：
- 文本类（txt/md/json/csv 等）：提取内容，可 auto_ingest=true 自动入 RAG
- 图片类（png/jpg）：存储，返回访问 URL
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 允许的扩展名白名单（拒绝 .exe/.php/.html/.svg 等危险类型）
_ALLOWED_EXTS = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".log",
    ".py", ".js", ".ts", ".yaml", ".yml", ".xml", ".rst",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
}
_TEXT_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".js", ".ts", ".yaml", ".yml", ".xml", ".rst"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@router.post("/upload", tags=["文件"])
async def upload_file(
    file: UploadFile = File(...),
    kb_id: str | None = Form(None),
    auto_ingest: bool = Form(False),
    user: CurrentUser = Depends(get_current_user),
):
    """上传文件（需认证）。文本类可自动提取内容入 RAG。"""
    s = get_settings()
    upload_dir = Path(s.upload_dir)

    # 文件名安全处理：取 basename 防路径穿越，校验扩展名白名单
    raw_name = file.filename or "upload"
    safe_basename = Path(raw_name).name  # 去掉任何目录部分
    if not safe_basename or safe_basename.startswith("."):
        return JSONResponse(status_code=400, content={"error": "非法文件名"})
    ext = Path(safe_basename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        return JSONResponse(status_code=400, content={"error": f"不支持的文件类型: {ext}", "allowed": sorted(_ALLOWED_EXTS)})

    # 大小校验
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > s.upload_max_size_mb:
        return JSONResponse(status_code=413, content={"error": "文件过大", "max_mb": s.upload_max_size_mb})

    # 保存（uuid 前缀防重名）
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_dir_resolved = upload_dir.resolve()
    saved_name = f"{uuid.uuid4().hex[:8]}_{safe_basename}"
    saved_path = (upload_dir / saved_name).resolve()
    # 精确校验：保存路径的父目录必须等于 upload_dir（防穿越，比 startswith 可靠）
    if saved_path.parent != upload_dir_resolved:
        return JSONResponse(status_code=400, content={"error": "路径校验失败"})
    saved_path.write_bytes(content)

    # 不返回服务器绝对路径，只返回相对 URL
    result = {
        "filename": safe_basename,
        "saved_as": saved_name,
        "size_bytes": len(content),
        "size_mb": round(size_mb, 2),
        "ext": ext,
    }

    # 文本类：提取内容，可选入 RAG
    if ext in _TEXT_EXTS:
        try:
            text = content.decode("utf-8", errors="ignore")
            result["text_length"] = len(text)
            result["is_text"] = True
            if auto_ingest and kb_id:
                from app.rag.service import get_rag_service
                chunks = await get_rag_service().ingest(kb_id, text, source=safe_basename)
                result["ingested_chunks"] = chunks
                result["kb_id"] = kb_id
                logger.info("文件 %s 已入 RAG（%d 块）", safe_basename, chunks)
        except Exception:  # noqa: BLE001
            result["text_error"] = "内容提取失败"
    elif ext in _IMAGE_EXTS:
        result["is_image"] = True
        result["url"] = f"/uploads/{saved_name}"

    logger.info("文件上传：%s (%.2f MB) user=%s", safe_basename, size_mb, user.user_id)
    return result


@router.get("/uploads", tags=["文件"])
async def list_uploads(user: CurrentUser = Depends(get_current_user)):
    """列出已上传文件（需认证）。"""
    s = get_settings()
    upload_dir = Path(s.upload_dir)
    if not upload_dir.exists():
        return {"files": []}
    files = []
    for f in upload_dir.iterdir():
        if f.is_file():
            files.append({"name": f.name, "size_bytes": f.stat().st_size})
    return {"count": len(files), "files": files}
