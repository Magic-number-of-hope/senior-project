# -*- coding: utf-8 -*-
"""HTTP API 与前端静态入口。"""
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from config.settings import AMAP_API_KEY, AMAP_WEB_KEY, AMAP_WEB_SECRET, AMAP_WEB_SERVICE_HOST, FRONTEND_DEV_URL, FRONTEND_DIST_DIR

router = APIRouter()

_frontend_dist_path = Path(FRONTEND_DIST_DIR).resolve()
_frontend_dist_index = _frontend_dist_path / "index.html"


@router.get("/")
async def get_index():
    if _frontend_dist_index.exists():
        return FileResponse(_frontend_dist_index)
    if FRONTEND_DEV_URL:
        return RedirectResponse(url=FRONTEND_DEV_URL, status_code=307)
    return JSONResponse(status_code=503, content={"error": "frontend_not_available", "message": "前端不可用：请启动前端开发服务，或构建 dist 产物。"})


@router.get("/favicon.ico")
async def favicon():
    favicon_path = _frontend_dist_path / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return FileResponse(Path(__file__).resolve().parents[2] / "front" / "public" / "favicon.ico")


@router.get("/api/check-models")
async def check_models() -> dict:
    return {
        "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "amap": bool(os.getenv("AMAP_API_KEY")),
    }


@router.get("/api/amap-key")
async def get_amap_key() -> dict:
    return {
        "key": AMAP_WEB_KEY or AMAP_API_KEY,
        "secret": AMAP_WEB_SECRET,
        "service_host": AMAP_WEB_SERVICE_HOST,
    }
