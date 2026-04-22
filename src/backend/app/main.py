# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config.settings import FRONTEND_DIST_DIR
from app.routers.http_routes import router as http_router
from app.routers.ws_handler import router as ws_router


_FRONTEND_APP_PATH = Path(__file__).resolve().parents[2] / "front"
_FRONTEND_DIST_PATH = Path(FRONTEND_DIST_DIR).resolve()
_FRONTEND_DIST_INDEX = _FRONTEND_DIST_PATH / "index.html"


def _frontend_dist_needs_build() -> bool:
    if not _FRONTEND_DIST_INDEX.exists():
        return True
    dist_mtime = _FRONTEND_DIST_INDEX.stat().st_mtime
    watch_files = [
        _FRONTEND_APP_PATH / "package.json",
        _FRONTEND_APP_PATH / "vue.config.js",
        _FRONTEND_APP_PATH / "babel.config.js",
        _FRONTEND_APP_PATH / "public" / "index.html",
        _FRONTEND_APP_PATH / "vite.config.js",
    ]
    watch_dirs = [_FRONTEND_APP_PATH / "src", _FRONTEND_APP_PATH / "public"]

    for file_path in watch_files:
        if file_path.exists() and file_path.stat().st_mtime > dist_mtime:
            return True
    for root_dir in watch_dirs:
        if not root_dir.exists():
            continue
        for file_path in root_dir.rglob("*"):
            if file_path.is_file() and file_path.stat().st_mtime > dist_mtime:
                return True
    return False


def _maybe_build_frontend_dist() -> None:
    auto_build = os.getenv("AUTO_BUILD_FRONTEND", "1").strip().lower()
    if auto_build in {"0", "false", "no", "off"}:
        return
    if not _FRONTEND_APP_PATH.exists() or not _frontend_dist_needs_build():
        return

    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        print("[BOOT] FRONTEND_BUILD: 未找到 npm，跳过自动构建")
        return
    try:
        print("[BOOT] FRONTEND_BUILD: 检测到前端变更，开始构建 dist...")
        subprocess.run([npm_cmd, "run", "build"], cwd=str(_FRONTEND_APP_PATH), check=True)
        print("[BOOT] FRONTEND_BUILD: 前端构建完成")
    except subprocess.CalledProcessError as exc:
        print(f"[BOOT] FRONTEND_BUILD: 构建失败，将继续使用现有产物。exit={exc.returncode}")


_maybe_build_frontend_dist()


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    try:
        yield
    finally:
        from tools.amap_tools import close_amap_session

        await close_amap_session()


app = FastAPI(title="小导导航后端", lifespan=_app_lifespan)
app.include_router(http_router)
app.include_router(ws_router)

if _FRONTEND_DIST_INDEX.exists():
    for asset_dir in ("assets", "js", "css"):
        asset_path = _FRONTEND_DIST_PATH / asset_dir
        if asset_path.exists() and asset_path.is_dir():
            app.mount(f"/{asset_dir}", StaticFiles(directory=str(asset_path)), name=f"frontend_{asset_dir}")