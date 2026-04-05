# -*- coding: utf-8 -*-
"""导航分析桥接工具 — 严格两阶段执行。

流程图对应关系：
    1. Whisper 转写文本
    2. 第一模型：意图识别 + 槽位填充，仅输出 JSON
    3. 第二模型：导航校验，接收 intent + slots JSON
    4. 服务端负责事件推送与最终播报注入
"""
import asyncio
import json
import traceback

from agentscope import logger
from agentscope.tool import ToolResponse
from agentscope.message import Msg, TextBlock


# 全局意图识别智能体单例
_comp_agent = None
_comp_lock = asyncio.Lock()
_comp_reply_lock = asyncio.Lock()

_nav_agent = None
_nav_lock = asyncio.Lock()
_nav_reply_lock = asyncio.Lock()


async def _get_comp_agent():
    """懒加载意图识别智能体"""
    global _comp_agent
    async with _comp_lock:
        if _comp_agent is None:
            logger.info("[COMP-AGENT] 正在创建意图识别智能体...")
            from agents.comprehension_agent import create_comprehension_agent
            _comp_agent = create_comprehension_agent()
            logger.info("[COMP-AGENT] 意图识别智能体创建完成")
    return _comp_agent


async def _get_nav_agent():
    """懒加载导航校验智能体"""
    global _nav_agent
    async with _nav_lock:
        if _nav_agent is None:
            logger.info("[NAV-AGENT] 正在创建导航校验智能体...")
            from agents.navigation_agent import create_navigation_agent
            _nav_agent = create_navigation_agent()
            logger.info("[NAV-AGENT] 导航校验智能体创建完成")
    return _nav_agent


async def _async_trigger(user_text: str) -> str:
    """异步执行意图分析 — 第一阶段，仅返回 intent+slots JSON。

    Whisper 转写完成后调用此函数，将文本交给意图识别智能体。
    该智能体只负责判断是否导航以及输出结构化槽位，不负责路线规划。

    Args:
        user_text: Whisper 转写的用户文本

    Returns:
        意图识别智能体的回复文本（结构化 JSON）
    """
    logger.info("[NAV-TRIGGER] 开始分析: %s", user_text[:100])

    agent = await _get_comp_agent()

    user_msg = Msg(
        name="user",
        content=user_text,
        role="user",
    )

    logger.info("[NAV-TRIGGER] 调用意图识别智能体...")
    async with _comp_reply_lock:
        reply = await agent.reply(user_msg)
    logger.info("[NAV-TRIGGER] 意图识别智能体回复完成")

    # 提取回复内容
    content = reply.content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
            elif isinstance(block, str):
                texts.append(block)
        content = "\n".join(texts)

    result = content if isinstance(content, str) else str(content)
    logger.info("[NAV-TRIGGER] 分析结果: %s", result[:200])
    return result


async def _async_run_navigation(navigation_request) -> str:
    """异步执行导航校验 — 第二阶段。"""
    if isinstance(navigation_request, str):
        request_text = navigation_request
    else:
        request_text = json.dumps(navigation_request, ensure_ascii=False)

    logger.info("[NAV-TRIGGER] 开始导航校验: %s", request_text[:200])
    agent = await _get_nav_agent()
    msg = Msg(name="intent_result", content=request_text, role="user")

    async with _nav_reply_lock:
        reply = await agent.reply(msg)

    content = reply.content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
            elif isinstance(block, str):
                texts.append(block)
        content = "\n".join(texts)

    result = content if isinstance(content, str) else str(content)
    logger.info("[NAV-TRIGGER] 导航校验结果: %s", result[:200])
    return result


def trigger_navigation(user_text: str) -> ToolResponse:
    """同步版本 — 供支持工具调用的模型使用(OpenAI/Gemini)

    Args:
        user_text: 用户的完整导航相关表述

    Returns:
        导航分析结果 ToolResponse
    """
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result_text = pool.submit(
                asyncio.run, _async_trigger(user_text),
            ).result(timeout=60)
    except Exception as e:
        traceback.print_exc()
        result_text = json.dumps({
            "status": "error",
            "message": f"导航分析失败: {str(e)}",
        }, ensure_ascii=False)

    return ToolResponse(
        content=[TextBlock(type="text", text=result_text)],
        metadata={"type": "navigation_result"},
    )
