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

from config.settings import DASHSCOPE_API_KEY, COMPREHENSION_MODEL_NAME
from prompts.comprehension_prompt import COMPREHENSION_PROMPT
from tools.user_profile_tools import load_user_profile


def _resolve_dashscope_model_name(model_name: str) -> str:
    """将新命名模型映射到当前 AgentScope/DashScope 可用名称。"""
    alias_map = {
        "qwen3.6-plus": "qwen-plus",
    }
    return alias_map.get(model_name, model_name)


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
    resolved_model_name = _resolve_dashscope_model_name(COMPREHENSION_MODEL_NAME)
    if resolved_model_name != COMPREHENSION_MODEL_NAME:
        logger.warning(
            "[COMP-AGENT] 模型名兼容映射: %s -> %s",
            COMPREHENSION_MODEL_NAME,
            resolved_model_name,
        )

    model = DashScopeChatModel(
        model_name=resolved_model_name,
        api_key=DASHSCOPE_API_KEY,
        stream=True,
    )
    formatter = DashScopeChatFormatter()
    toolkit = Toolkit()
    toolkit.register_tool_function(get_user_profile)

    logger.info(
        "[COMP-AGENT] 创建意图识别智能体 (requested_model=%s, actual_model=%s, tools=%s)",
        COMPREHENSION_MODEL_NAME,
        resolved_model_name,
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
