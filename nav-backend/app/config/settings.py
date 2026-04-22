# -*- coding: utf-8 -*-
"""全局配置 — 所有可调参数统一从环境变量读取。"""
import os

# ── API 密钥 ──
DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
AMAP_API_KEY: str = os.getenv("AMAP_API_KEY", "")
AMAP_WEB_KEY: str = os.getenv("AMAP_WEB_KEY", "")
AMAP_WEB_SECRET: str = os.getenv("AMAP_WEB_SECRET", "")
AMAP_WEB_SERVICE_HOST: str = os.getenv("AMAP_WEB_SERVICE_HOST", "")

# ── 模型名称 ──
CHAT_MODEL_NAME: str = os.getenv("CHAT_MODEL_NAME", "qwen-max")
COMPREHENSION_MODEL_NAME: str = os.getenv("COMPREHENSION_MODEL_NAME", "qwen3-max")
REALTIME_MODEL_NAME: str = os.getenv("REALTIME_MODEL_NAME", "qwen3-omni-flash-realtime")
VL_MODEL_NAME: str = os.getenv("VL_MODEL_NAME", "qwen-vl-max")

# ── Whisper 配置 ──
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")

# ── 视频处理 ──
VIDEO_FRAME_INTERVAL: float = float(os.getenv("VIDEO_FRAME_INTERVAL", "1.0"))
VIDEO_CHANGE_THRESHOLD: float = float(os.getenv("VIDEO_CHANGE_THRESHOLD", "0.15"))

# ── 存储 ──
STORAGE_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
USER_PROFILE_PATH: str = os.path.join(STORAGE_DIR, "user_profiles")

# ── 导航触发关键词 ──
NAV_TRIGGER_KEYWORDS: list[str] = [
    "导航", "去", "到", "怎么走", "路线", "带我去",
    "开车", "打车", "坐地铁", "骑车", "步行",
    "附近", "找一下", "有没有", "推荐", "哪里有",
    "加油站", "停车场", "充电桩", "服务区",
]
