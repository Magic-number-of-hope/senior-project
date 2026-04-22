# -*- coding: utf-8 -*-
"""Whisper 语音识别工具 — 将 PCM16 音频转为文本"""
import os
import shutil
import tempfile
import traceback
import wave
from typing import Optional

import numpy as np
from agentscope import logger

from app.config.settings import WHISPER_MODEL_SIZE

# Whisper 模型单例（懒加载）
_whisper_model = None
_ffmpeg_checked = False


def _ensure_ffmpeg_available() -> Optional[str]:
    """确保当前进程可找到 ffmpeg 可执行文件。"""
    global _ffmpeg_checked

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        if not _ffmpeg_checked:
            logger.info("[WHISPER] ffmpeg 已就绪: %s", ffmpeg_path)
            _ffmpeg_checked = True
        return ffmpeg_path

    # 兜底：在 Windows winget 安装目录中查找 ffmpeg 并动态注入 PATH
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        winget_root = os.path.join(
            local_appdata,
            "Microsoft",
            "WinGet",
            "Packages",
        )
        if os.path.isdir(winget_root):
            try:
                candidates = [
                    os.path.join(winget_root, d)
                    for d in os.listdir(winget_root)
                    if d.startswith("Gyan.FFmpeg")
                ]
                candidates.sort(key=os.path.getmtime, reverse=True)
                for pkg_dir in candidates:
                    bin_dir = os.path.join(
                        pkg_dir,
                        "ffmpeg-8.1-full_build",
                        "bin",
                    )
                    ff_exe = os.path.join(bin_dir, "ffmpeg.exe")
                    if os.path.isfile(ff_exe):
                        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                        ffmpeg_path = shutil.which("ffmpeg")
                        if ffmpeg_path:
                            logger.info(
                                "[WHISPER] 已注入 ffmpeg PATH: %s",
                                ffmpeg_path,
                            )
                            _ffmpeg_checked = True
                            return ffmpeg_path
            except Exception as e:
                logger.warning("[WHISPER] 扫描 winget ffmpeg 目录失败: %s", e)

    logger.error("[WHISPER] 未找到 ffmpeg 可执行文件，请安装并确保在 PATH 中")
    return None


def _get_whisper_model():
    """懒加载 Whisper 模型"""
    global _whisper_model
    if _whisper_model is None:
        import whisper

        logger.info(
            "[WHISPER] 正在加载 Whisper 模型 (%s)...",
            WHISPER_MODEL_SIZE,
        )
        _whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("[WHISPER] Whisper 模型加载完成")
    return _whisper_model


def transcribe_pcm16(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    language: str = "zh",
) -> Optional[str]:
    """将 PCM16 音频字节转为文本。

    Args:
        pcm_bytes: PCM16 格式原始音频字节
        sample_rate: 采样率，默认 16000
        language: 语言代码，默认 "zh"

    Returns:
        识别出的文本，失败返回 None
    """
    if not pcm_bytes or len(pcm_bytes) < 3200:
        return None

    tmp_path = None
    try:
        model = _get_whisper_model()
        if not _ensure_ffmpeg_available():
            return None

        # 写入临时 wav 文件（标准方式，Whisper 会通过 ffmpeg 解码）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)

        result = model.transcribe(
            tmp_path,
            language=language,
            fp16=False,
        )
        text = result.get("text", "").strip()

        logger.info("[WHISPER] 识别结果: %s", text[:100])
        return text if text else None

    except Exception as e:
        logger.error("[WHISPER] 转录失败: %s", e)
        logger.debug("[WHISPER] 异常堆栈:\n%s", traceback.format_exc())
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
