# -*- coding: utf-8 -*-
"""理解分析智能体 — 意图识别 + 槽位填充。"""
from agentscope import logger
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.message import TextBlock
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, ToolResponse

from app.config.settings import COMPREHENSION_MODEL_NAME, DASHSCOPE_API_KEY
from app.prompts.comprehension_prompt import COMPREHENSION_PROMPT
from app.tools.user_profile_tools import load_user_profile

_MODEL_ALIAS = {"qwen3.6-plus": "qwen-plus"}


def get_user_profile(user_id: str = "default") -> ToolResponse:
    """查询用户画像信息。"""
    logger.info("[PROFILE] 查询用户画像: %s", user_id)
    return ToolResponse(content=[TextBlock(type="text", text=load_user_profile(user_id))])


def create_comprehension_agent() -> ReActAgent:
    """创建意图识别和槽位填充智能体实例。"""
    resolved = _MODEL_ALIAS.get(COMPREHENSION_MODEL_NAME, COMPREHENSION_MODEL_NAME)
    model = DashScopeChatModel(model_name=resolved, api_key=DASHSCOPE_API_KEY, stream=True)
    toolkit = Toolkit()
    toolkit.register_tool_function(get_user_profile)
    logger.info("[COMP-AGENT] 创建意图识别智能体 (model=%s, tools=%s)", resolved, list(toolkit.tools.keys()))
    return ReActAgent(
        name="意图识别智能体",
        sys_prompt=COMPREHENSION_PROMPT,
        model=model,
        formatter=DashScopeChatFormatter(),
        toolkit=toolkit,
        max_iters=10,
    )
