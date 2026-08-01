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

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, get_current_user, require_admin
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


def _prepare_dir(d: Path) -> Path:
    """建目录并返回其 resolve 后的路径（阻塞操作，由调用方丢线程池）。"""
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def _list_files(d: Path) -> list[dict]:
    """列目录（阻塞操作，由调用方丢线程池）。"""
    if not d.exists():
        return []
    return [
        {"name": f.name, "size_bytes": f.stat().st_size}
        for f in d.iterdir()
        if f.is_file()
    ]


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
    # 文件系统操作全部丢到线程池：mkdir/resolve/write_bytes 都是阻塞调用，
    # 直接在 async handler 里跑会卡住整个事件循环——写一个 20MB 的文件期间，
    # 所有其他请求（包括正在流式输出的对话）都会被顶住。
    upload_dir_resolved = await asyncio.to_thread(_prepare_dir, upload_dir)
    saved_name = f"{uuid.uuid4().hex[:8]}_{safe_basename}"
    saved_path = await asyncio.to_thread(lambda: (upload_dir / saved_name).resolve())
    # 精确校验：保存路径的父目录必须等于 upload_dir（防穿越，比 startswith 可靠）
    if saved_path.parent != upload_dir_resolved:
        return JSONResponse(status_code=400, content={"error": "路径校验失败"})
    await asyncio.to_thread(saved_path.write_bytes, content)

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
                chunks = await get_rag_service().ingest(
                    kb_id, text, source=safe_basename, tenant_id=user.tenant_id,
                )
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
async def list_uploads(user: CurrentUser = Depends(require_admin)):
    """列出已上传文件。

    限管理员：上传目录是所有租户共用的扁平目录，没有按用户/租户分区，
    普通用户能列出他人上传的文件名。在做完按用户分目录之前，先收紧权限。
    """
    files = await asyncio.to_thread(_list_files, Path(get_settings().upload_dir))
    return {"count": len(files), "files": files}
