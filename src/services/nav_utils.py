# -*- coding: utf-8 -*-
"""Navigation utility helpers shared by server flow."""

import json
import re
from typing import Optional

from models.nav_result_schema import NeedSelectionResult

_CURRENT_LOCATION_HINT_PATTERN = re.compile(
    r"我现在|当前位置|附近|周边|离我|就近|最近|这里|这儿",
)
_CONTEXT_CONTINUATION_PATTERN = re.compile(
    r"再去|然后去|接着去|继续去|下一站|下一步",
)


def _get_missing_slots(slots: dict, intent_type: str = "") -> list[str]:
    """按意图类型返回缺失的必要槽位。"""
    missing = []

    if intent_type == "life_service":
        required = ("origin", "poi_type")
    else:
        required = ("origin", "destination", "travel_mode")

    for key in required:
        if not slots.get(key):
            missing.append(key)
    return missing


def _should_use_current_location(
    user_text: str,
    intent_type: str,
    slots: dict,
) -> bool:
    """判断在起点缺失时，是否优先采用当前位置补全。"""
    if slots.get("origin"):
        return False

    if intent_type == "life_service":
        return True

    text = (user_text or "").strip()
    if not text:
        return False

    if _CONTEXT_CONTINUATION_PATTERN.search(text):
        return False

    if _CURRENT_LOCATION_HINT_PATTERN.search(text):
        return True

    return bool(slots.get("destination") or slots.get("poi_type"))


def _build_nav_broadcast_text(nav_data: Optional[dict], user_text: str) -> str:
    """将导航结果转为精简口语化文本，供 RealtimeAgent 语音播报。"""
    if not nav_data or not isinstance(nav_data, dict):
        return f"用户问了：{user_text}，但未能获取导航结果，请告知用户稍后重试。"

    nav_result = nav_data.get("navigation_result")
    slots = nav_data.get("slots", {})
    intent_type = nav_data.get("intent_type", "") or ""
    poi_type = slots.get("poi_type", "")
    poi_constraint = slots.get("poi_constraint", "")
    waypoints = [
        str(w).strip()
        for w in (slots.get("waypoints", []) or [])
        if str(w).strip()
    ]
    origin = slots.get("origin", "出发地")
    dest = slots.get("destination", "目的地")

    if not nav_result or not isinstance(nav_result, dict):
        return (
            f"用户想从{origin}到{dest}，但导航校验未返回有效结果，"
            "请告诉用户稍后重试。"
        )

    status = nav_result.get("status", "")
    if status == "need_selection":
        if intent_type == "life_service":
            return (
                f"用户想在{origin}附近找{poi_type or '目标地点'}，"
                "存在多个候选，请引导用户选择具体地点。"
            )
        return (
            f"用户想从{origin}到{dest}，地点存在歧义，"
            "请引导用户从候选地点中选择。"
        )

    if status not in ("ok", "success"):
        if intent_type == "life_service":
            msg = nav_result.get("message") or ""
            constraint = poi_constraint or "当前范围"
            if msg:
                return (
                    f"用户想在{origin}附近找{poi_type or '目标地点'}（{constraint}），"
                    f"当前未找到。请告知用户：{msg}，并建议放宽搜索半径后重试。"
                )
            return (
                f"用户想在{origin}附近找{poi_type or '目标地点'}（{constraint}），"
                "当前未找到，请建议放宽搜索半径后重试。"
            )
        return (
            f"用户想从{origin}到{dest}，但导航路线规划失败，"
            "请告诉用户检查地点后重试。"
        )

    origin_name = nav_result.get("origin_name", origin)
    dest_name = nav_result.get("destination_name", dest)
    distance = nav_result.get("distance", "")
    taxi_cost = nav_result.get("taxi_cost", "")

    steps = nav_result.get("steps", [])
    first_steps = steps[:3]
    step_texts = "、".join(s.get("instruction", "") for s in first_steps)

    parts = [
        f"[请用口语化方式播报以下导航结果]",
        f"从{origin_name}到{dest_name}，",
    ]
    if distance:
        km = round(int(distance) / 1000, 1) if distance.isdigit() else distance
        parts.append(f"全程约{km}公里，")
    if taxi_cost:
        parts.append(f"预计打车{taxi_cost}元，")
    if waypoints:
        parts.append(f"途经{'、'.join(waypoints)}，")
    if step_texts:
        parts.append(f"先{step_texts}。")
    if len(steps) > 3:
        parts.append(f"共{len(steps)}个导航步骤，已发送到您的设备上。")

    return "".join(parts)


def _validate_need_selection_result(nav_result: dict) -> dict:
    """严格校验 need_selection 输出格式，不做兼容转换。"""
    payload = {
        "status": nav_result.get("status"),
        "origin_candidates": nav_result.get("origin_candidates", []),
        "destination_candidates": nav_result.get("destination_candidates", []),
        "origin_name": nav_result.get("origin_name"),
        "origin_location": nav_result.get("origin_location"),
        "destination_name": nav_result.get("destination_name"),
        "destination_location": nav_result.get("destination_location"),
    }
    validated = NeedSelectionResult.model_validate(payload)
    result = validated.model_dump(mode="python")

    merged = []
    for c in result["origin_candidates"]:
        item = dict(c)
        item["selection_group"] = "origin"
        merged.append(item)
    for c in result["destination_candidates"]:
        item = dict(c)
        item["selection_group"] = "destination"
        merged.append(item)
    result["candidates"] = merged
    return result


def _tool_response_to_json(resp: object) -> Optional[dict]:
    """将 ToolResponse 转为 JSON 字典。"""
    try:
        raw = resp.content[0]
        text = raw["text"] if isinstance(raw, dict) else raw.text
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _extract_radius_from_constraint(text: str) -> int:
    """从约束文本提取半径(米)，提取失败返回 500。"""
    s = (text or "").strip()
    if not s:
        return 500

    m_km = re.search(r"(\d+(?:\.\d+)?)\s*公里", s)
    if m_km:
        return max(100, int(float(m_km.group(1)) * 1000))

    m_m = re.search(r"(\d+)\s*米", s)
    if m_m:
        return max(100, int(m_m.group(1)))

    return 500


def _build_radius_retry_list(base_radius: int) -> list[int]:
    """构建附近搜索扩圈序列。"""
    candidates = [base_radius, 500, 1000, 2000]
    radii = []
    for r in candidates:
        rr = max(100, min(5000, int(r)))
        if rr not in radii:
            radii.append(rr)
    return radii


def _parse_nav_result(text: str) -> dict:
    """严格解析智能体返回：仅允许单个 JSON 对象。"""
    if not text:
        raise ValueError("模型返回为空，无法解析 JSON")

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回不是 JSON 对象")
    return parsed
