# -*- coding: utf-8 -*-
"""导航校验智能体 — 高德 POI 校验 + 地理编码。"""
from agentscope import logger
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit

from app.config.settings import CHAT_MODEL_NAME, DASHSCOPE_API_KEY
from app.prompts.navigation_prompt import NAVIGATION_PROMPT
from app.tools.amap_tools import geocode, reverse_geocode, search_nearby_pois, search_poi


def create_navigation_agent() -> ReActAgent:
    """创建导航校验智能体实例。"""
    model = DashScopeChatModel(model_name=CHAT_MODEL_NAME, api_key=DASHSCOPE_API_KEY, stream=True)
    toolkit = Toolkit()
    toolkit.register_tool_function(search_poi)
    toolkit.register_tool_function(search_nearby_pois)
    toolkit.register_tool_function(geocode)
    toolkit.register_tool_function(reverse_geocode)
    logger.info("[NAV-AGENT] 创建导航校验智能体 (model=%s, tools=%s)", CHAT_MODEL_NAME, list(toolkit.tools.keys()))
    return ReActAgent(
        name="导航校验智能体",
        sys_prompt=NAVIGATION_PROMPT,
        model=model,
        formatter=DashScopeChatFormatter(),
        toolkit=toolkit,
        max_iters=4,
    )
