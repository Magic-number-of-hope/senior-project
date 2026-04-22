# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers.http_routes import router as http_router
from app.routers.ws_handler import router as ws_router


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    """应用生命周期：关闭时清理全局资源。"""
    try:
        yield
    finally:
        from app.tools.amap_tools import close_amap_session
        await close_amap_session()


app = FastAPI(title="小导 — 车载导航助手后端", lifespan=_app_lifespan)

# 注册路由
app.include_router(http_router)
app.include_router(ws_router)

# 生产环境挂载前端静态文件（Vue build 产物）
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
