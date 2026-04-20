# -*- coding: utf-8 -*-
"""导航校验智能体 — 高德 POI 校验 + 地理编码 + 路线规划"""
from agentscope import logger
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit

from config.settings import DASHSCOPE_API_KEY, CHAT_MODEL_NAME
from prompts.navigation_prompt import NAVIGATION_PROMPT
from tools.amap_tools import (
    search_poi,
    search_nearby_pois,
    geocode,
    reverse_geocode,
)


def create_navigation_agent() -> ReActAgent:
    """创建导航校验智能体实例。

    该智能体负责：
    1. 接收意图识别智能体输出的结构化 JSON
    2. 对槽位中的地名进行高德 POI 搜索 & 地理编码
    3. POI 校验、纠错、歧义消解
    4. 路线规划（驾车/步行/公交/骑行）
    5. 将结果回传给上游
    """
    model = DashScopeChatModel(
        model_name=CHAT_MODEL_NAME,
        api_key=DASHSCOPE_API_KEY,
        stream=True,
    )
    formatter = DashScopeChatFormatter()
    toolkit = Toolkit()
    toolkit.register_tool_function(search_poi)
    toolkit.register_tool_function(search_nearby_pois)
    toolkit.register_tool_function(geocode)
    toolkit.register_tool_function(reverse_geocode)

    logger.info(
        "[NAV-AGENT] 创建导航校验智能体 (model=%s, tools=%s)",
        CHAT_MODEL_NAME,
        list(toolkit.tools.keys()),
    )

    return ReActAgent(
        name="导航校验智能体",
        sys_prompt=NAVIGATION_PROMPT,
        model=model,
        formatter=formatter,
        toolkit=toolkit,
        max_iters=4,
    )
