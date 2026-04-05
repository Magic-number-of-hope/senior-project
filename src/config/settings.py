# -*- coding: utf-8 -*-
"""全局配置"""
import os

# ── API 密钥 ──
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")           # 服务端 REST API
AMAP_WEB_KEY = os.getenv("AMAP_WEB_KEY", "")           # Web 端 JS API Key
AMAP_WEB_SECRET = os.getenv("AMAP_WEB_SECRET", "")     # Web 端 JS API 安全密钥

# ── 模型名称 ──
CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", "qwen-max")
REALTIME_MODEL_NAME = os.getenv(
    "REALTIME_MODEL_NAME", "qwen3-omni-flash-realtime",
)
VL_MODEL_NAME = os.getenv("VL_MODEL_NAME", "qwen-vl-max")

# ── Whisper 配置 ──
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

# ── 视频处理配置 ──
VIDEO_FRAME_INTERVAL = float(os.getenv("VIDEO_FRAME_INTERVAL", "1.0"))
VIDEO_CHANGE_THRESHOLD = float(os.getenv("VIDEO_CHANGE_THRESHOLD", "0.15"))

# ── 存储 ──
STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "storage",
)
USER_PROFILE_PATH = os.path.join(STORAGE_DIR, "user_profiles")

# ── 记忆压缩 ──
COMPRESSION_TRIGGER_THRESHOLD = 8000

# ── 导航触发关键词 ──
NAV_TRIGGER_KEYWORDS = [
    "导航", "去", "到", "怎么走", "路线", "带我去",
    "开车", "打车", "坐地铁", "骑车", "步行",
    "附近", "找一下", "有没有", "推荐", "哪里有",
    "加油站", "停车场", "充电桩", "服务区",
]
