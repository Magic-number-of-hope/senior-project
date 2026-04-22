# -*- coding: utf-8 -*-
"""实时输出智能体 — RealtimeAgent（语音/文字回复）

新架构下，RealtimeAgent 不再直接调用导航工具。
语音由 Whisper 转写后，意图分析和导航由服务端管线处理，
结果通过文本注入的方式回传给 RealtimeAgent 做语音播报。
"""
from agentscope.agent import RealtimeAgent
from agentscope.realtime import DashScopeRealtimeModel
from agentscope.tool import Toolkit

from config.settings import DASHSCOPE_API_KEY, REALTIME_MODEL_NAME
from prompts.interaction_prompt import INTERACTION_PROMPT


def create_interaction_agent() -> RealtimeAgent:
    """创建实时输出智能体实例"""
    model = DashScopeRealtimeModel(
        model_name=REALTIME_MODEL_NAME,
        api_key=DASHSCOPE_API_KEY,
    )
    toolkit = Toolkit()

    return RealtimeAgent(
        name="小导",
        sys_prompt=INTERACTION_PROMPT,
        model=model,
        toolkit=toolkit,
    )
