# -*- coding: utf-8 -*-
"""兼容启动入口。

保留原文件名，内部改为委托 app 分层结构，避免外部运行方式和测试导入断裂。
"""
import os

import uvicorn

from app.main import app
from app.services.nav_pipeline import detect_nav_intent, route_text_by_flowchart, run_nav_pipeline
from app.services.session_state import (
    normalize_travel_mode_value as _normalize_travel_mode_value,
    normalize_waypoints_by_mode as _normalize_waypoints_by_mode,
    should_preserve_previous_route_points as _should_preserve_previous_route_points,
)
from config.settings import AMAP_API_KEY


__all__ = [
    "app",
    "detect_nav_intent",
    "run_nav_pipeline",
    "route_text_by_flowchart",
    "_normalize_travel_mode_value",
    "_normalize_waypoints_by_mode",
    "_should_preserve_previous_route_points",
]


if __name__ == "__main__":
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
    amap_web_key = os.getenv("AMAP_WEB_KEY", "")
    amap_web_secret = os.getenv("AMAP_WEB_SECRET", "")
    amap_service_host = os.getenv("AMAP_WEB_SERVICE_HOST", "")
    port = int(os.getenv("RUN_SERVER_PORT", "8080"))

    print(f"[BOOT] DASHSCOPE_API_KEY: {'已设置 (' + dashscope_key[:8] + '...)' if dashscope_key else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_API_KEY:      {'已设置 (' + AMAP_API_KEY[:8] + '...)' if AMAP_API_KEY else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_WEB_KEY:      {'已设置 (' + amap_web_key[:8] + '...)' if amap_web_key else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_WEB_SECRET:   {'已设置 (' + amap_web_secret[:8] + '...)' if amap_web_secret else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_SERVICE_HOST: {amap_service_host if amap_service_host else '未设置(开发环境可使用 securityJsCode)'}")

    reload_flag = os.getenv("RUN_SERVER_RELOAD", "").strip().lower()
    reload_enabled = reload_flag in {"1", "true", "yes", "on"}
    print(f"[BOOT] PORT:              {port}")
    print(f"[BOOT] RELOAD:            {'开启' if reload_enabled else '关闭'}")

    uvicorn.run(
        "run_server:app",
        host="localhost",
        port=port,
        reload=reload_enabled,
        log_level="info",
    )