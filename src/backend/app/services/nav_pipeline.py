# -*- coding: utf-8 -*-
"""导航分流与 Stage 1/2 管线。"""
import re
import traceback
from typing import Optional

from agentscope import logger
from agentscope.agent import RealtimeAgent
from agentscope.realtime import ClientEvents
from fastapi import WebSocket

from config.settings import NAV_TRIGGER_KEYWORDS
from models.intent_schema import IntentResult
from services.nav_routing import (
    _send_route_result_fast,
    _try_direct_route_planning,
    _try_fast_nav_without_llm,
    _try_life_service_nearby_retry,
)
from services.nav_utils import (
    _build_nav_broadcast_text,
    _get_missing_slots,
    _parse_nav_result,
    _tool_response_to_json,
    _validate_need_selection_result,
)
from tools.video_tools import get_current_visual_state

from app.services.session_state import (
    build_nav_memory_hint_for_llm,
    get_session_agent_input_lock,
    get_session_route_lock,
    hydrate_nav_slots_from_context,
    normalize_waypoints_by_mode,
    pending_nav,
    pending_nav_route_broadcast,
    save_nav_context,
)


_NAV_PATTERN = re.compile("|".join(re.escape(kw) for kw in NAV_TRIGGER_KEYWORDS))


def detect_nav_intent(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    return bool(_NAV_PATTERN.search(text))


async def inject_text_to_agent(agent: Optional[RealtimeAgent], session_id: str, text: str) -> None:
    if not text.strip() or not agent:
        return
    lock = get_session_agent_input_lock(session_id)
    async with lock:
        try:
            append_event = ClientEvents.from_json({"type": "client_text_append", "session_id": session_id, "text": text})
            await agent.handle_input(append_event)
            create_event = ClientEvents.from_json({"type": "client_response_create", "session_id": session_id})
            await agent.handle_input(create_event)
        except Exception as exc:
            logger.error("[BROADCAST] 注入播报失败(session=%s): %s", session_id, exc)


async def send_nav_status(websocket: WebSocket, status: str, message: str) -> None:
    await websocket.send_json({"type": "nav_status_update", "status": status, "message": message})


async def send_nav_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "nav_error", "message": message})
    except Exception:
        pass


async def publish_need_selection(session_id: str, websocket: WebSocket, slots: dict, nav_result: dict, intent_type: str = "basic_navigation", *, log_wait: bool = False) -> bool:
    nav_result = _validate_need_selection_result(nav_result)
    origin_cands = nav_result.get("origin_candidates", [])
    dest_cands = nav_result.get("destination_candidates", [])

    waypoint_names = [str(w).strip() for w in (slots.get("waypoints", []) or []) if str(w).strip()]
    waypoint_locs = [str(w).strip() for w in (slots.get("waypoint_locations", []) or []) if str(w).strip()]
    waypoint_pending_index = None
    if waypoint_names and len(waypoint_locs) < len(waypoint_names):
        waypoint_pending_index = len(waypoint_locs)

    resolved_origin_name = nav_result.get("origin_name") or slots.get("origin")
    resolved_origin_location = nav_result.get("origin_location") or slots.get("origin_location")
    resolved_destination_name = nav_result.get("destination_name") or slots.get("destination")
    resolved_destination_location = nav_result.get("destination_location") or slots.get("destination_location")

    waypoint_need_selection = bool(
        waypoint_pending_index is not None
        and dest_cands
        and not origin_cands
        and resolved_destination_name
        and resolved_destination_location
    )

    merged_candidates = []
    if waypoint_need_selection:
        for candidate in dest_cands:
            item = dict(candidate)
            item["selection_group"] = "waypoint"
            merged_candidates.append(item)
    else:
        merged_candidates = list(nav_result.get("candidates", []))

    if not origin_cands and not dest_cands:
        logger.warning("[NAV] need_selection 但候选为空，跳过等待选择")
        return False

    origin_resolved = None
    if resolved_origin_name and resolved_origin_location:
        origin_resolved = {"name": resolved_origin_name, "location": resolved_origin_location, "cityname": ""}
    destination_resolved = None
    if resolved_destination_name and resolved_destination_location:
        destination_resolved = {"name": resolved_destination_name, "location": resolved_destination_location, "cityname": ""}

    await websocket.send_json({
        "type": "nav_poi_candidates",
        "candidates": merged_candidates,
        "origin_candidates": origin_cands,
        "destination_candidates": dest_cands,
    })
    pending_nav[session_id] = {
        "slots": slots,
        "intent_type": intent_type,
        "origin_resolved": origin_resolved,
        "destination_resolved": destination_resolved,
        "waypoint_resolved": None,
        "waypoint_pending_index": waypoint_pending_index,
        "has_origin_candidates": len(origin_cands) > 0,
        "has_destination_candidates": len(dest_cands) > 0 and not waypoint_need_selection,
        "has_waypoint_candidates": waypoint_need_selection,
    }
    if log_wait:
        logger.info("[NAV] 等待用户选择候选地点 session=%s", session_id)
    return True


async def retry_without_waypoints_if_needed(slots: dict, websocket: WebSocket, session_id: str, intent_type: str) -> bool:
    waypoints = [str(w).strip() for w in (slots.get("waypoints", []) or []) if str(w).strip()]
    if not waypoints:
        return False

    slots.pop("waypoints", None)
    slots.pop("waypoint_locations", None)
    await send_nav_status(websocket, "processing", "途经点存在歧义，正在忽略途经点重试规划...")

    retry_result = await _try_fast_nav_without_llm(slots)
    if isinstance(retry_result, dict):
        retry_status = retry_result.get("status", "")
        if retry_status in ("ok", "success"):
            await _send_route_result_fast(websocket, retry_result, slots)
            await send_nav_status(websocket, "done", "已忽略歧义途经点并完成路线规划")
            defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
            return True
        if retry_status == "need_selection":
            published = await publish_need_selection(session_id, websocket, slots, retry_result, intent_type=intent_type, log_wait=True)
            if published:
                return True

    direct_result = await _try_direct_route_planning(slots)
    if isinstance(direct_result, dict):
        await _send_route_result_fast(websocket, direct_result, slots)
        await send_nav_status(websocket, "done", "已忽略歧义途经点并完成路线规划")
        defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
        return True

    await send_nav_error(websocket, f"途经点“{waypoints[0]}”存在歧义，请说更完整名称")
    await send_nav_status(websocket, "done", "需要补充更精确的途经点")
    return True


async def broadcast_nav_summary(agent: Optional[RealtimeAgent], session_id: str, nav_result: object, slots: dict, intent_type: str = "") -> None:
    normalize_waypoints_by_mode(slots)
    await save_nav_context(session_id, dict(slots))
    nav_data = {"navigation_result": nav_result, "slots": slots, "intent_type": intent_type}
    visual_state = await get_current_visual_state()
    summary = _build_nav_broadcast_text(nav_data, "")
    if visual_state:
        summary += f"\n当前视觉环境：{visual_state}"
    await inject_text_to_agent(agent, session_id, summary)


def defer_nav_broadcast_until_frontend(session_id: str, slots: dict, intent_type: str) -> None:
    pending_nav_route_broadcast[session_id] = {"slots": dict(slots or {}), "intent_type": intent_type or ""}
    logger.info("[NAV] 等待前端回传完整路线用于播报 session=%s", session_id)


async def ensure_life_service_origin_location(slots: dict, intent_type: str) -> dict:
    if intent_type != "life_service":
        return slots
    if slots.get("origin_location") or not slots.get("origin"):
        return slots
    try:
        from tools.amap_tools import geocode

        resp = await geocode(slots.get("origin", ""))
        data = _tool_response_to_json(resp)
        if isinstance(data, dict) and data.get("status") == "ok" and data.get("location"):
            slots["origin_location"] = data["location"]
            if data.get("name"):
                slots["origin"] = data["name"]
            if data.get("cityname"):
                slots["origin_cityname"] = data["cityname"]
            logger.info("[NAV] life_service 预解析起点坐标 origin=%s location=%s", slots.get("origin", ""), slots.get("origin_location", ""))
    except Exception as exc:
        logger.warning("[NAV] life_service 起点预解析失败: %s", exc)
    return slots


async def execute_navigation_with_slots(slots: dict, websocket: WebSocket, agent: Optional[RealtimeAgent], session_id: str, intent_type: str = "basic_navigation", *, processing_message: str, error_log_prefix: str, error_message_prefix: str, origin_info: Optional[dict] = None, dest_info: Optional[dict] = None) -> None:
    from tools.analysis_tools import _async_run_navigation

    try:
        normalize_waypoints_by_mode(slots)
        await send_nav_status(websocket, "processing", processing_message)

        fast_nav_result = await _try_fast_nav_without_llm(slots)
        if isinstance(fast_nav_result, dict):
            fast_status = fast_nav_result.get("status", "")
            if fast_status == "need_selection":
                published = await publish_need_selection(session_id, websocket, slots, fast_nav_result, intent_type=intent_type, log_wait=True)
                if published:
                    return
                if await retry_without_waypoints_if_needed(slots, websocket, session_id, intent_type):
                    return
            if fast_status in ("ok", "success"):
                await _send_route_result_fast(websocket, fast_nav_result, slots)
                await send_nav_status(websocket, "done", "导航分析完成")
                defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
                return

        direct_result = await _try_direct_route_planning(slots)
        if isinstance(direct_result, dict):
            direct_status = direct_result.get("status", "")
            if direct_status == "need_selection":
                published = await publish_need_selection(session_id, websocket, slots, direct_result, intent_type=intent_type, log_wait=True)
                if published:
                    return
                if await retry_without_waypoints_if_needed(slots, websocket, session_id, intent_type):
                    return
            if direct_status in ("ok", "success"):
                await _send_route_result_fast(websocket, direct_result, slots)
                await send_nav_status(websocket, "done", "导航分析完成")
                defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
                return

        nav_result_text = await _async_run_navigation({"intent_type": intent_type, "slots": slots})
        nav_result = _parse_nav_result(nav_result_text)
        if isinstance(nav_result, dict):
            status = nav_result.get("status", "")
            if intent_type == "life_service" and status in ("need_selection", "error"):
                retry_result = await _try_life_service_nearby_retry(slots)
                if isinstance(retry_result, dict):
                    nav_result = retry_result
                    status = nav_result.get("status", "")
            if status == "need_selection":
                published = await publish_need_selection(session_id, websocket, slots, nav_result, intent_type=intent_type, log_wait=True)
                if published:
                    return
                if await retry_without_waypoints_if_needed(slots, websocket, session_id, intent_type):
                    return
                await send_nav_error(websocket, "地点存在歧义但未返回可选候选，请补充更准确名称")
                await send_nav_status(websocket, "done", "需要补充地点信息")
                return
            if status in ("ok", "success"):
                if origin_info and "origin_name" not in nav_result:
                    nav_result["origin_name"] = origin_info["name"]
                if dest_info and "destination_name" not in nav_result:
                    nav_result["destination_name"] = dest_info["name"]
                await _send_route_result_fast(websocket, nav_result, slots)
                await send_nav_status(websocket, "done", "导航分析完成")
                defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
                return

        await send_nav_status(websocket, "done", "导航分析完成")
        await broadcast_nav_summary(agent, session_id, nav_result, slots, intent_type=intent_type)
    except Exception as exc:
        logger.error("%s: %s", error_log_prefix, exc)
        traceback.print_exc()
        await send_nav_error(websocket, f"{error_message_prefix}: {exc}")


async def finalize_poi_selection(session_id: str, websocket: WebSocket, agent: Optional[RealtimeAgent]) -> None:
    pending = pending_nav.pop(session_id, None)
    if not pending:
        return
    slots = pending.get("slots", {})
    intent_type = pending.get("intent_type", "basic_navigation")
    origin_info = pending.get("origin_resolved")
    dest_info = pending.get("destination_resolved")
    waypoint_info = pending.get("waypoint_resolved")
    waypoint_pending_index = pending.get("waypoint_pending_index")

    if origin_info:
        slots["origin"] = origin_info["name"]
        slots["origin_location"] = origin_info["location"]
    if dest_info:
        slots["destination"] = dest_info["name"]
        slots["destination_location"] = dest_info["location"]
    if waypoint_info and isinstance(waypoint_pending_index, int) and waypoint_pending_index >= 0:
        waypoint_names = list(slots.get("waypoints", []) or [])
        waypoint_locs = list(slots.get("waypoint_locations", []) or [])
        while len(waypoint_names) <= waypoint_pending_index:
            waypoint_names.append("")
        while len(waypoint_locs) <= waypoint_pending_index:
            waypoint_locs.append("")
        waypoint_names[waypoint_pending_index] = waypoint_info.get("name", waypoint_names[waypoint_pending_index])
        waypoint_locs[waypoint_pending_index] = waypoint_info.get("location", waypoint_locs[waypoint_pending_index])
        slots["waypoints"] = [w for w in waypoint_names if str(w).strip()]
        slots["waypoint_locations"] = [w for w in waypoint_locs if str(w).strip()]

    await execute_navigation_with_slots(
        slots=slots,
        websocket=websocket,
        agent=agent,
        session_id=session_id,
        intent_type=intent_type,
        processing_message="正在规划路线...",
        error_log_prefix="[NAV] POI 选择后路线规划异常",
        error_message_prefix="路线规划失败",
        origin_info=origin_info,
        dest_info=dest_info,
    )


async def run_stage2_with_slots(slots: dict, intent_type: str, websocket: WebSocket, agent: Optional[RealtimeAgent], session_id: str) -> None:
    await execute_navigation_with_slots(
        slots=slots,
        websocket=websocket,
        agent=agent,
        session_id=session_id,
        intent_type=intent_type,
        processing_message="正在查询路线...",
        error_log_prefix="[NAV] Stage 2 执行异常",
        error_message_prefix="导航查询失败",
    )


async def run_nav_pipeline(user_text: str, websocket: WebSocket, session_id: Optional[str] = None, raw_user_text: Optional[str] = None) -> tuple[bool, Optional[dict], str]:
    try:
        source_text = raw_user_text or user_text
        await send_nav_status(websocket, "processing", "正在分析导航意图...")
        from tools.analysis_tools import _async_run_navigation, _async_trigger

        result_text = await _async_trigger(user_text)
        nav_data = _parse_nav_result(result_text)
        nav_data = IntentResult.model_validate(nav_data).model_dump(mode="python")

        if nav_data.get("is_navigation") is False:
            await send_nav_status(websocket, "done", "非导航需求")
            return False, nav_data, result_text
        if nav_data.get("needs_clarification"):
            await send_nav_status(websocket, "done", nav_data.get("clarification_question", "需要补充导航信息"))
            return True, nav_data, result_text

        slots = nav_data.get("slots", {})
        intent_type = nav_data.get("intent_type", "")
        if session_id:
            slots = await hydrate_nav_slots_from_context(session_id, source_text, intent_type, slots)
            nav_data["slots"] = slots

        if "intent_type" in nav_data:
            await websocket.send_json({
                "type": "nav_intent_result",
                "intent_result": {
                    "intent_type": nav_data.get("intent_type", ""),
                    "slots": nav_data.get("slots", {}),
                    "confidence": nav_data.get("confidence", 0),
                    "needs_clarification": nav_data.get("needs_clarification", False),
                    "clarification_question": nav_data.get("clarification_question"),
                },
            })

        required_missing = _get_missing_slots(slots, intent_type)
        if required_missing:
            await send_nav_status(websocket, "done", "等待补充导航信息")
            return True, nav_data, result_text

        slots = await ensure_life_service_origin_location(slots, intent_type)
        nav_data["slots"] = slots
        nav_result_text = await _async_run_navigation({"intent_type": intent_type, "slots": slots})
        nav_result = _parse_nav_result(nav_result_text)
        nav_data["navigation_result"] = nav_result

        status = nav_result.get("status", "")
        if status == "need_selection":
            has_any_candidates = bool(nav_result.get("candidates") or nav_result.get("origin_candidates") or nav_result.get("destination_candidates"))
            has_waypoints = bool(slots.get("waypoints") or slots.get("waypoint_locations"))
            if not has_any_candidates and has_waypoints:
                fast_retry = await _try_fast_nav_without_llm(slots)
                if isinstance(fast_retry, dict):
                    nav_result = fast_retry
                    nav_data["navigation_result"] = nav_result
                    status = nav_result.get("status", "")

        if intent_type == "life_service" and status in ("need_selection", "error"):
            retry_result = await _try_life_service_nearby_retry(slots)
            if isinstance(retry_result, dict):
                nav_result = retry_result
                nav_data["navigation_result"] = nav_result
                status = nav_result.get("status", "")

        if status in ("ok", "success"):
            await _send_route_result_fast(websocket, nav_result, nav_data.get("slots", {}))
        elif status == "need_selection":
            nav_result = _validate_need_selection_result(nav_result)
            nav_data["navigation_result"] = nav_result
            await websocket.send_json({
                "type": "nav_poi_candidates",
                "candidates": nav_result["candidates"],
                "origin_candidates": nav_result["origin_candidates"],
                "destination_candidates": nav_result["destination_candidates"],
            })

        await send_nav_status(websocket, "done", "导航分析完成")
        return True, nav_data, result_text
    except Exception as exc:
        logger.error("[NAV] 导航管线异常: %s", exc)
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "nav_error", "message": f"导航分析失败: {exc}"})
        except Exception:
            pass
        return False, None, ""


async def route_text_by_flowchart(user_text: str, websocket: WebSocket, agent: Optional[RealtimeAgent], session_id: str) -> None:
    async with get_session_route_lock(session_id):
        llm_text = user_text
        if detect_nav_intent(user_text):
            memory_hint = await build_nav_memory_hint_for_llm(session_id)
            if memory_hint:
                llm_text = f"{user_text}{memory_hint}"

        is_navigation, nav_data, _ = await run_nav_pipeline(llm_text, websocket, session_id=session_id, raw_user_text=user_text)
        visual_state = await get_current_visual_state()

        if is_navigation and isinstance(nav_data, dict):
            slots = nav_data.get("slots", {})
            intent_type = nav_data.get("intent_type", "")
            missing_slots = _get_missing_slots(slots, intent_type)
            await save_nav_context(session_id, dict(slots))
            if missing_slots:
                pending_nav[session_id] = {
                    "slots": dict(slots),
                    "intent_type": intent_type,
                    "stage": "slot_fill",
                    "missing_slots": list(missing_slots),
                    "origin_resolved": None,
                    "destination_resolved": None,
                    "has_origin_candidates": False,
                    "has_destination_candidates": False,
                    "has_waypoint_candidates": False,
                }
                await websocket.send_json({
                    "type": "nav_missing_slots",
                    "missing": missing_slots,
                    "current_slots": {
                        "origin": slots.get("origin", ""),
                        "destination": slots.get("destination", ""),
                        "travel_mode": slots.get("travel_mode", ""),
                    },
                })
                return

            nav_result = nav_data.get("navigation_result")
            if not nav_result:
                await run_stage2_with_slots(slots, intent_type, websocket, agent, session_id)
                return

        if isinstance(nav_data, dict) and nav_data.get("needs_clarification"):
            ask = nav_data.get("clarification_question") or "请补充导航信息。"
            if visual_state:
                ask = f"{ask}\n当前视觉环境：{visual_state}"
            await inject_text_to_agent(agent, session_id, ask)
            return

        if is_navigation:
            nav_result = (nav_data or {}).get("navigation_result")
            if isinstance(nav_result, dict) and nav_result.get("status") == "need_selection":
                await publish_need_selection(session_id, websocket, (nav_data or {}).get("slots", {}), nav_result, intent_type=(nav_data or {}).get("intent_type", "basic_navigation"), log_wait=True)
                return
            if isinstance(nav_result, dict) and nav_result.get("status") in ("ok", "success"):
                defer_nav_broadcast_until_frontend(session_id, (nav_data or {}).get("slots", {}), (nav_data or {}).get("intent_type", ""))
                return

            summary = _build_nav_broadcast_text(nav_data, user_text)
            if visual_state:
                summary += f"\n当前视觉环境：{visual_state}"
            await inject_text_to_agent(agent, session_id, summary)
            return

        non_nav_text = user_text
        if visual_state:
            non_nav_text = f"{user_text}\n[视觉状态] {visual_state}"
        await inject_text_to_agent(agent, session_id, non_nav_text)
