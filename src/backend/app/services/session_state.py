# -*- coding: utf-8 -*-
"""会话级导航状态与上下文记忆。"""
import asyncio
import json
import re

from agentscope import logger
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from services.nav_utils import _should_use_current_location


pending_nav: dict = {}
pending_nav_route_broadcast: dict = {}
session_current_location: dict = {}

_nav_context_memory = InMemoryMemory()
_nav_context_mark = "nav_context"
_session_route_locks: dict = {}
_session_agent_input_locks: dict = {}

_MODE_CHANGE_ONLY_PATTERN = re.compile(
    r"(改成|切换|换成|换条|走|导航方式|驾车|开车|步行|走路|骑行|骑车|公交|地铁|最快|最短|少收费|不走高速)",
)


def normalize_travel_mode_value(mode: object) -> str:
    """将出行方式统一为 driving|walking|transit|bicycling。"""
    raw = str(getattr(mode, "value", mode) or "").strip().lower()
    if raw.startswith("travelmode."):
        raw = raw.split(".", 1)[1]
    alias_map = {
        "riding": "bicycling",
        "bike": "bicycling",
        "bicycle": "bicycling",
    }
    return alias_map.get(raw, raw)


def normalize_waypoints_by_mode(slots: dict) -> dict:
    """仅允许驾车模式保留途经点，其他模式统一清理。"""
    if not isinstance(slots, dict):
        return slots

    mode = normalize_travel_mode_value(slots.get("travel_mode", ""))
    if mode and slots.get("travel_mode") != mode:
        slots["travel_mode"] = mode
    if mode and mode != "driving":
        had_waypoints = bool(
            slots.get("waypoints")
            or slots.get("waypoint_locations")
            or slots.get("sequence")
        )
        slots.pop("waypoints", None)
        slots.pop("waypoint_locations", None)
        slots.pop("sequence", None)
        if had_waypoints:
            logger.info("[NAV] 非驾车模式(%s)清理途经点", mode)
    return slots


def should_preserve_previous_route_points(user_text: str, slots: dict, prev_slots: dict) -> bool:
    """模式/偏好微调场景中，沿用上轮已解析的起终点与途经点。"""
    if not isinstance(slots, dict) or not isinstance(prev_slots, dict):
        return False
    if not prev_slots.get("origin_location") or not prev_slots.get("destination_location"):
        return False

    text = (user_text or "").strip()
    if not text:
        return False
    if re.search(r"从.+到|去.+|前往.+", text):
        return False
    if not _MODE_CHANGE_ONLY_PATTERN.search(text):
        return False

    has_route_adjustment = bool(
        slots.get("travel_mode")
        or slots.get("preference")
        or slots.get("time_constraint")
    )
    return has_route_adjustment


def get_session_route_lock(session_id: str) -> asyncio.Lock:
    lock = _session_route_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_route_locks[session_id] = lock
    return lock


def get_session_agent_input_lock(session_id: str) -> asyncio.Lock:
    lock = _session_agent_input_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_agent_input_locks[session_id] = lock
    return lock


async def load_nav_context(session_id: str) -> dict:
    msgs = await _nav_context_memory.get_memory(mark=session_id, prepend_summary=False)
    for msg in reversed(msgs):
        if not isinstance(msg.content, str):
            continue
        try:
            data = json.loads(msg.content)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


async def save_nav_context(session_id: str, slots: dict) -> None:
    msgs = await _nav_context_memory.get_memory(mark=session_id, prepend_summary=False)
    if msgs:
        await _nav_context_memory.delete([msg.id for msg in msgs])

    await _nav_context_memory.add(
        Msg(
            name=session_id,
            role="system",
            content=json.dumps(slots, ensure_ascii=False),
            metadata={"type": _nav_context_mark},
        ),
        marks=[_nav_context_mark, session_id],
    )


async def build_nav_memory_hint_for_llm(session_id: str) -> str:
    payload = {}

    prev = await load_nav_context(session_id)
    if isinstance(prev, dict) and prev:
        prev_mode = normalize_travel_mode_value(prev.get("travel_mode", ""))
        allowed_keys = (
            "origin",
            "origin_location",
            "destination",
            "destination_location",
            "travel_mode",
            "waypoints",
            "waypoint_locations",
            "poi_type",
            "poi_constraint",
        )
        slots = {}
        for key in allowed_keys:
            if key in ("waypoints", "waypoint_locations") and prev_mode != "driving":
                continue
            val = prev.get(key)
            if val not in (None, "", [], {}):
                slots[key] = val
        if slots:
            payload["last_nav_slots"] = slots

    current_loc = session_current_location.get(session_id)
    if isinstance(current_loc, dict) and current_loc.get("location"):
        payload["current_location"] = {
            "name": current_loc.get("name") or "当前位置",
            "location": current_loc.get("location"),
            "source": current_loc.get("source"),
            "accuracy": current_loc.get("accuracy"),
        }

    if not payload:
        return ""

    return (
        "\n[导航记忆，仅供意图识别与槽位提取参考：请以用户本轮输入为最高优先级，不要机械继承旧槽位]"
        f"\n{json.dumps(payload, ensure_ascii=False)}"
    )


async def hydrate_nav_slots_from_context(
    session_id: str,
    user_text: str,
    intent_type: str,
    slots: dict,
) -> dict:
    if not session_id or not isinstance(slots, dict):
        return slots

    prev_slots = await load_nav_context(session_id)
    current_loc = session_current_location.get(session_id)
    origin_from_current_location = False

    if (
        isinstance(current_loc, dict)
        and current_loc.get("location")
        and _should_use_current_location(user_text, intent_type, slots)
    ):
        slots["origin"] = current_loc.get("name") or "当前位置"
        slots["origin_location"] = current_loc.get("location")
        origin_from_current_location = True
        logger.info(
            "[NAV-MEM] 使用当前位置补全起点 origin=%s, location=%s",
            slots.get("origin", ""),
            slots.get("origin_location", ""),
        )

    if isinstance(prev_slots, dict) and prev_slots:
        if should_preserve_previous_route_points(user_text, slots, prev_slots):
            for key in (
                "origin",
                "origin_location",
                "destination",
                "destination_location",
                "waypoints",
                "waypoint_locations",
            ):
                if prev_slots.get(key):
                    slots[key] = prev_slots[key]
            logger.info(
                "[NAV-MEM] 模式微调续聊，沿用上轮已解析起终点 origin=%s destination=%s",
                slots.get("origin", ""),
                slots.get("destination", ""),
            )

        fill_keys = ("origin", "travel_mode") if intent_type == "life_service" else ("origin", "destination", "travel_mode")
        filled_from_prev = set()
        for key in fill_keys:
            if not slots.get(key) and prev_slots.get(key):
                slots[key] = prev_slots[key]
                filled_from_prev.add(key)
                logger.info("[NAV-MEM] 复用上轮槽位 %s=%s", key, prev_slots.get(key))

        if (
            "origin" in filled_from_prev
            and not slots.get("origin_location")
            and prev_slots.get("origin_location")
            and not origin_from_current_location
        ):
            slots["origin_location"] = prev_slots["origin_location"]

        if (
            "destination" in filled_from_prev
            and not slots.get("destination_location")
            and prev_slots.get("destination_location")
        ):
            slots["destination_location"] = prev_slots["destination_location"]

    if intent_type == "life_service":
        if slots.pop("destination", None) is not None:
            logger.info("[NAV] life_service 场景清理 destination")
        if slots.pop("destination_location", None) is not None:
            logger.info("[NAV] life_service 场景清理 destination_location")

    normalize_waypoints_by_mode(slots)
    return slots


def cleanup_session(session_id: str) -> None:
    pending_nav.pop(session_id, None)
    pending_nav_route_broadcast.pop(session_id, None)
    session_current_location.pop(session_id, None)
    _session_route_locks.pop(session_id, None)
    _session_agent_input_locks.pop(session_id, None)
