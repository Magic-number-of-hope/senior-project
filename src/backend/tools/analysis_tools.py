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

from models.intent_schema import IntentResult
from models.nav_result_schema import NeedSelectionResult, RouteResult, ErrorResult


# 全局意图识别智能体单例
_comp_agent = None
_comp_lock = asyncio.Lock()
_comp_reply_lock = asyncio.Lock()

_nav_agent = None
_nav_lock = asyncio.Lock()
_nav_reply_lock = asyncio.Lock()


def _extract_text_content_strict(content) -> str:
    """从模型返回内容中提取纯文本，未提取到则抛错。"""
    if isinstance(content, str):
        text = content.strip()
        if not text:
            raise ValueError("模型返回空文本")
        return text

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        text = "\n".join(t for t in texts if isinstance(t, str)).strip()
        if not text:
            raise ValueError("模型返回中未包含 text block")
        return text

    raise ValueError(f"不支持的模型返回类型: {type(content)}")


def _parse_json_dict_strict(text: str) -> dict:
    """严格解析 JSON 字典：仅接受单个 JSON 对象。"""
    cleaned = (text or "").strip()

    # qwen3-max 偶发输出 ```json ... ``` 包裹，这里仅去掉最外层围栏。
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            head = lines[0].strip().lower()
            if head in ("```", "```json", "```jsonc"):
                cleaned = "\n".join(lines[1:-1]).strip()

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return parsed


def _validate_intent_result_strict(text: str) -> str:
    """校验意图识别输出并返回规范化 JSON。"""
    data = _parse_json_dict_strict(text)

    # 意图模型偶发将数组槽位输出为 null，这里规范化为 [] 以匹配 schema。
    slots = data.get("slots")
    if isinstance(slots, dict):
        for key in ("waypoints", "sequence"):
            if slots.get(key) is None:
                slots[key] = []

    validated = IntentResult.model_validate(data)
    return validated.model_dump_json(ensure_ascii=False)


def _normalize_navigation_result_for_validation(data: dict) -> dict:
    """在严格校验前归一化导航结果。"""
    if data.get("status") not in ("ok", "success"):
        return data

    # life_service 一类结果可能返回“附近 POI 列表”而非终点路线。
    # 这类 payload 没有 destination，但会带 waypoints/waypoint_locations。
    if data.get("destination_name") or data.get("destination_location"):
        return data

    existing_candidates = data.get("destination_candidates")
    if isinstance(existing_candidates, list) and existing_candidates:
        return {
            "status": "need_selection",
            "origin_candidates": data.get("origin_candidates", []),
            "destination_candidates": existing_candidates,
            "origin_name": data.get("origin_name"),
            "origin_location": data.get("origin_location"),
            "destination_name": None,
            "destination_location": None,
        }

    waypoint_names = data.get("waypoints") or []
    waypoint_locations = data.get("waypoint_locations") or []
    if not isinstance(waypoint_names, list) or not waypoint_names:
        return data

    destination_candidates = []
    for index, raw_name in enumerate(waypoint_names):
        name = str(raw_name or "").strip()
        if not name:
            continue

        candidate = {"name": name}
        if index < len(waypoint_locations):
            location = str(waypoint_locations[index] or "").strip()
            if location:
                candidate["location"] = location
        destination_candidates.append(candidate)

    if not destination_candidates:
        return data

    return {
        "status": "need_selection",
        "origin_candidates": data.get("origin_candidates", []),
        "destination_candidates": destination_candidates,
        "origin_name": data.get("origin_name"),
        "origin_location": data.get("origin_location"),
        "destination_name": None,
        "destination_location": None,
    }


def _validate_navigation_result_strict(text: str) -> str:
    """校验导航校验输出并返回规范化 JSON。"""
    data = _normalize_navigation_result_for_validation(_parse_json_dict_strict(text))
    status = data.get("status")

    if status == "need_selection":
        waypoint_groups = data.get("waypoint_candidates") or []
        waypoint_candidates = []
        if isinstance(waypoint_groups, list):
            for group in waypoint_groups:
                if not isinstance(group, dict):
                    continue
                candidates = group.get("candidates") or []
                if isinstance(candidates, list) and candidates:
                    waypoint_candidates = candidates
                    break

        payload = {
            "status": data.get("status"),
            "origin_candidates": data.get("origin_candidates", []),
            "destination_candidates": data.get("destination_candidates", []) or waypoint_candidates,
            "origin_name": data.get("origin_name"),
            "origin_location": data.get("origin_location"),
            "destination_name": data.get("destination_name"),
            "destination_location": data.get("destination_location"),
        }
        validated = NeedSelectionResult.model_validate(payload)
        return validated.model_dump_json(ensure_ascii=False)

    if status in ("ok", "success"):
        validated = RouteResult.model_validate(data)
        return validated.model_dump_json(ensure_ascii=False)

    if status == "error":
        validated = ErrorResult.model_validate(data)
        return validated.model_dump_json(ensure_ascii=False)

    raise ValueError(f"未知导航结果 status: {status}")


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
    # 同一阶段串行调用，避免一个 agent 实例被并发 reply 导致上下文交错。
    async with _comp_reply_lock:
        reply = await agent.reply(user_msg)
    logger.info("[NAV-TRIGGER] 意图识别智能体回复完成")

    result_text = _extract_text_content_strict(reply.content)
    normalized = _validate_intent_result_strict(result_text)
    logger.info("[NAV-TRIGGER] 分析结果: %s", normalized[:200])
    return normalized


async def _async_run_navigation(navigation_request) -> str:
    """异步执行导航校验 — 第二阶段。"""
    if isinstance(navigation_request, str):
        request_text = navigation_request
    else:
        request_text = json.dumps(navigation_request, ensure_ascii=False)

    logger.info("[NAV-TRIGGER] 开始导航校验: %s", request_text[:200])
    agent = await _get_nav_agent()
    msg = Msg(name="intent_result", content=request_text, role="user")

    # 导航阶段同理串行，确保 ReAct 中间思考链不被并发请求污染。
    async with _nav_reply_lock:
        reply = await agent.reply(msg)

    result_text = _extract_text_content_strict(reply.content)
    normalized = _validate_navigation_result_strict(result_text)
    logger.info("[NAV-TRIGGER] 导航校验结果: %s", normalized[:200])
    return normalized


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
