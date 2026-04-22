# -*- coding: utf-8 -*-
"""视频帧分析工具 — 抽帧 + 变化检测 + qwen-vl-max 分析"""
import asyncio
import base64
import io
import time
from typing import Optional

import numpy as np
from agentscope import logger
from openai import OpenAI

from app.config.settings import (
    DASHSCOPE_API_KEY,
    VL_MODEL_NAME,
    VIDEO_FRAME_INTERVAL,
    VIDEO_CHANGE_THRESHOLD,
)

# OpenAI 兼容客户端（DashScope）
_vl_client: Optional[OpenAI] = None

# 上一帧灰度直方图，用于变化检测
_last_histogram: Optional[np.ndarray] = None
_last_analysis_time: float = 0.0

# 当前视觉状态（供 RealtimeAgent 使用）
_current_visual_state: str = ""
_visual_state_lock = asyncio.Lock()


def _get_vl_client() -> OpenAI:
    """懒加载 VL 客户端"""
    global _vl_client
    if _vl_client is None:
        _vl_client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        logger.info("[VL] qwen-vl-max 客户端初始化完成")
    return _vl_client


def _compute_histogram(jpeg_bytes: bytes) -> Optional[np.ndarray]:
    """计算 JPEG 图片的灰度直方图（不依赖 PIL 的简化版本）。

    使用 JPEG 原始字节的统计分布近似灰度直方图。
    """
    try:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        hist, _ = np.histogram(arr, bins=64, range=(0, 256))
        # 归一化
        total = hist.sum()
        if total > 0:
            hist = hist.astype(np.float32) / total
        return hist
    except Exception:
        return None


def detect_change(jpeg_bytes: bytes) -> bool:
    """检测当前帧与上一帧是否有明显变化。

    Args:
        jpeg_bytes: JPEG 格式图片字节

    Returns:
        True 表示有明显变化，需要分析
    """
    global _last_histogram

    current_hist = _compute_histogram(jpeg_bytes)
    if current_hist is None:
        return True  # 无法计算则默认分析

    if _last_histogram is None:
        _last_histogram = current_hist
        return True  # 第一帧必定分析

    # 计算直方图差异（L1 距离）
    diff = float(np.sum(np.abs(current_hist - _last_histogram)))
    _last_histogram = current_hist

    changed = diff > VIDEO_CHANGE_THRESHOLD
    if changed:
        logger.info("[VL] 帧变化检测: diff=%.4f > 阈值%.2f，触发分析",
                     diff, VIDEO_CHANGE_THRESHOLD)
    return changed


async def analyze_frame(
    jpeg_base64: str,
    prompt: str = "请简要描述这张图片中的场景，重点关注道路状况、交通标志、行人、车辆等驾驶相关信息。用中文回答，50字以内。",
) -> Optional[str]:
    """调用 qwen-vl-max 分析单帧图片。

    Args:
        jpeg_base64: JPEG 图片的 Base64 编码
        prompt: 分析提示词

    Returns:
        分析结果文本，失败返回 None
    """
    global _last_analysis_time

    try:
        client = _get_vl_client()

        # 构造 data URI
        image_url = f"data:image/jpeg;base64,{jpeg_base64}"

        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=VL_MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
        )

        result = completion.choices[0].message.content
        _last_analysis_time = time.time()
        logger.info("[VL] 帧分析结果: %s", result[:100] if result else "空")
        return result

    except Exception as e:
        logger.error("[VL] qwen-vl-max 调用失败: %s", e)
        return None


async def process_video_frame(jpeg_base64: str) -> Optional[str]:
    """处理一帧视频：变化检测 → 分析 → 更新状态。

    流程:
        视频帧 → 变化检测 → (有变化时) 调用 qwen-vl-max → 更新当前状态

    Args:
        jpeg_base64: JPEG 图片的 Base64 编码

    Returns:
        如果进行了分析，返回分析结果；否则返回 None
    """
    global _current_visual_state

    jpeg_bytes = base64.b64decode(jpeg_base64)

    # 抽帧节流：仅每隔 VIDEO_FRAME_INTERVAL 秒允许一次分析尝试
    now = time.time()
    if (
        _last_analysis_time > 0
        and (now - _last_analysis_time) < VIDEO_FRAME_INTERVAL
    ):
        return None

    # 变化检测
    if not detect_change(jpeg_bytes):
        return None

    # 调用 qwen-vl-max 分析
    result = await analyze_frame(jpeg_base64)
    if result:
        async with _visual_state_lock:
            _current_visual_state = result
    return result


async def get_current_visual_state() -> str:
    """获取当前视觉状态描述（供 RealtimeAgent 使用）。

    Returns:
        最近一次视觉分析的结果文本
    """
    async with _visual_state_lock:
        return _current_visual_state


def reset_visual_state():
    """重置视觉状态（断开连接时调用）。"""
    global _last_histogram, _last_analysis_time, _current_visual_state
    _last_histogram = None
    _last_analysis_time = 0.0
    _current_visual_state = ""
