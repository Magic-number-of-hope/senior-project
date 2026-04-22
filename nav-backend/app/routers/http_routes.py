# -*- coding: utf-8 -*-
"""HTTP API 路由。"""
import os

from fastapi import APIRouter

from app.config.settings import AMAP_API_KEY, AMAP_WEB_KEY, AMAP_WEB_SECRET, AMAP_WEB_SERVICE_HOST

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/check-models")
async def check_models() -> dict:
    return {
        "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "amap": bool(os.getenv("AMAP_API_KEY")),
    }


@router.get("/amap-key")
async def get_amap_key() -> dict:
    return {
        "key": AMAP_WEB_KEY or AMAP_API_KEY,
        "secret": AMAP_WEB_SECRET,
        "service_host": AMAP_WEB_SERVICE_HOST,
    }
