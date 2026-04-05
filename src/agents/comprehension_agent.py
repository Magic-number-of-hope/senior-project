# -*- coding: utf-8 -*-
"""理解分析智能体 — 意图识别 + 槽位填充 + 判断是否导航 + 调用导航智能体"""
import asyncio
from typing import Any

from agentscope import logger
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.message import Msg, TextBlock
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, ToolResponse

from config.settings import DASHSCOPE_API_KEY, CHAT_MODEL_NAME
from prompts.comprehension_prompt import COMPREHENSION_PROMPT
from tools.user_profile_tools import load_user_profile


def get_user_profile(user_id: str = "default") -> ToolResponse:
    """查询用户画像信息，获取常用地点和偏好。

    Args:
        user_id: 用户ID，默认"default"

    Returns:
        用户画像信息
    """
    logger.info("[PROFILE] 查询用户画像: %s", user_id)
    profile_json = load_user_profile(user_id)
    return ToolResponse(content=[TextBlock(type="text", text=profile_json)])


def create_comprehension_agent() -> ReActAgent:
    """创建意图识别和槽位填充智能体实例。

    该智能体负责：
    1. 判断用户文本是否为导航需求
    2. 若是导航需求，进行意图识别和槽位填充
    3. 输出结构化 JSON 给服务端
    4. 若非导航需求，返回 non_navigation 标记
    """
    model = DashScopeChatModel(
        model_name=CHAT_MODEL_NAME,
        api_key=DASHSCOPE_API_KEY,
        stream=True,
    )
    formatter = DashScopeChatFormatter()
    toolkit = Toolkit()
    toolkit.register_tool_function(get_user_profile)

    logger.info(
        "[COMP-AGENT] 创建意图识别智能体 (model=%s, tools=%s)",
        CHAT_MODEL_NAME,
        list(toolkit.tools.keys()),
    )

    return ReActAgent(
        name="意图识别智能体",
        sys_prompt=COMPREHENSION_PROMPT,
        model=model,
        formatter=formatter,
        toolkit=toolkit,
        max_iters=10,
    )
