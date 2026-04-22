# -*- coding: utf-8 -*-
"""导航分析管线 — 从原 run_server.py 中提取的核心导航逻辑。

包含：
  - run_nav_pipeline: 意图分析 + 导航校验
  - route_text_by_flowchart: 文本分流
  - inject_text_to_agent: 播报注入
  - 各类辅助函数
"""
import asyncio
import json
import traceback
from typing import Optional

from agentscope import logger
from agentscope.agent import RealtimeAgent
from agentscope.realtime import ClientEvents
from fastapi import WebSocket

from app.models.intent_schema import IntentResult
from app.services.nav_routing import (
    send_route_result_fast,
    try_direct_route_planning,
    try_fast_nav_without_llm,
    try_life_service_nearby_retry,
)
from app.services.nav_utils import (
    build_nav_broadcast_text,
    get_missing_slots,
    parse_nav_result,
    should_use_current_location,
    validate_need_selection_result,
)
from app.services.session_state import (
    build_nav_memory_hint_for_llm,
    get_session_agent_input_lock,
    get_session_route_lock,
    load_nav_context,
    pending_nav,
    pending_nav_route_broadcast,
    save_nav_context,
    session_current_location,
)


# ═══════════════════════════════════════════
#  Agent 注入
# ═══════════════════════════════════════════

async def inject_text_to_agent(
    agent: Optional[RealtimeAgent],
    session_id: str,
    text: str,
) -> None:
    """将文本注入 RealtimeAgent 并触发回复生成。"""
    if not text.strip() or not agent:
        return
    lock = get_session_agent_input_lock(session_id)
    async with lock:
        try:
            append_event = ClientEvents.from_json({"type": "client_text_append", "session_id": session_id, "text": text})
            await agent.handle_input(append_event)
            create_event = ClientEvents.from_json({"type": "client_response_create", "session_id": session_id})
            await agent.handle_input(create_event)
        except Exception as e:
            logger.error("[BROADCAST] 注入播报失败(session=%s): %s", session_id, e)


# ═══════════════════════════════════════════
#  导航状态推送
# ═══════════════════════════════════════════

async def send_nav_status(websocket: WebSocket, status: str, message: str) -> None:
    await websocket.send_json({"type": "nav_status_update", "status": status, "message": message})


async def send_nav_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "nav_error", "message": message})
    except Exception:
        pass


# ═══════════════════════════════════════════
#  POI 候选推送
# ═══════════════════════════════════════════

async def publish_need_selection(
    session_id: str,
    websocket: WebSocket,
    slots: dict,
    nav_result: dict,
    intent_type: str = "basic_navigation",
) -> None:
    nav_result = validate_need_selection_result(nav_result)
    origin_cands = nav_result.get("origin_candidates", [])
    dest_cands = nav_result.get("destination_candidates", [])

    origin_resolved = None
    if nav_result.get("origin_name") and nav_result.get("origin_location"):
        origin_resolved = {"name": nav_result["origin_name"], "location": nav_result["origin_location"], "cityname": ""}
    destination_resolved = None
    if nav_result.get("destination_name") and nav_result.get("destination_location"):
        destination_resolved = {"name": nav_result["destination_name"], "location": nav_result["destination_location"], "cityname": ""}

    await websocket.send_json({
        "type": "nav_poi_candidates",
        "candidates": nav_result["candidates"],
        "origin_candidates": origin_cands,
        "destination_candidates": dest_cands,
    })
    pending_nav[session_id] = {
        "slots": slots,
        "intent_type": intent_type,
        "origin_resolved": origin_resolved,
        "destination_resolved": destination_resolved,
        "has_origin_candidates": len(origin_cands) > 0,
        "has_destination_candidates": len(dest_cands) > 0,
    }
    logger.info("[NAV] 等待用户选择候选地点 (origin=%d, dest=%d)", len(origin_cands), len(dest_cands))


# ═══════════════════════════════════════════
#  导航播报
# ═══════════════════════════════════════════

async def broadcast_nav_summary(
    agent: Optional[RealtimeAgent],
    session_id: str,
    nav_result: object,
    slots: dict,
    intent_type: str = "",
) -> None:
    from app.tools.video_tools import get_current_visual_state
    await save_nav_context(session_id, dict(slots))
    nav_data = {"navigation_result": nav_result, "slots": slots, "intent_type": intent_type}
    visual_state = await get_current_visual_state()
    summary = build_nav_broadcast_text(nav_data, "")
    if visual_state:
        summary += f"\n当前视觉环境：{visual_state}"
    await inject_text_to_agent(agent, session_id, summary)


def defer_nav_broadcast_until_frontend(session_id: str, slots: dict, intent_type: str) -> None:
    pending_nav_route_broadcast[session_id] = {"slots": dict(slots or {}), "intent_type": intent_type or ""}
    logger.info("[NAV] 等待前端回传完整路线用于播报 session=%s", session_id)


# ═══════════════════════════════════════════
#  统一执行 Stage 2
# ═══════════════════════════════════════════

async def execute_navigation_with_slots(
    slots: dict,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
    intent_type: str = "basic_navigation",
    *,
    processing_message: str = "正在规划路线...",
    origin_info: Optional[dict] = None,
    dest_info: Optional[dict] = None,
) -> None:
    from app.tools.analysis_tools import async_run_navigation
    try:
        await send_nav_status(websocket, "processing", processing_message)

        # 快路径1：纯高德
        fast_result = await try_fast_nav_without_llm(slots)
        if isinstance(fast_result, dict):
            fast_status = fast_result.get("status", "")
            if fast_status == "need_selection":
                await publish_need_selection(session_id, websocket, slots, fast_result, intent_type)
                return
            if fast_status in ("ok", "success"):
                await send_route_result_fast(websocket, fast_result, slots)
                await send_nav_status(websocket, "done", "导航分析完成")
                defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
                return

        # 快路径2：坐标齐全直出
        direct_result = await try_direct_route_planning(slots)
        if direct_result is not None:
            await send_route_result_fast(websocket, direct_result, slots)
            await send_nav_status(websocket, "done", "导航分析完成")
            defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
            return

        # 调用 LLM 导航校验
        nav_result_text = await async_run_navigation({"intent_type": intent_type, "slots": slots})
        nav_result = parse_nav_result(nav_result_text)

        if isinstance(nav_result, dict):
            status = nav_result.get("status", "")
            if intent_type == "life_service" and status in ("need_selection", "error"):
                retry_result = await try_life_service_nearby_retry(slots)
                if isinstance(retry_result, dict):
                    nav_result = retry_result
                    status = nav_result.get("status", "")
            if status == "need_selection":
                await publish_need_selection(session_id, websocket, slots, nav_result, intent_type)
                return
            if status in ("ok", "success"):
                if origin_info and "origin_name" not in nav_result:
                    nav_result["origin_name"] = origin_info["name"]
                if dest_info and "destination_name" not in nav_result:
                    nav_result["destination_name"] = dest_info["name"]
                await send_route_result_fast(websocket, nav_result, slots)
                await send_nav_status(websocket, "done", "导航分析完成")
                defer_nav_broadcast_until_frontend(session_id, slots, intent_type)
                return

        await send_nav_status(websocket, "done", "导航分析完成")
        await broadcast_nav_summary(agent, session_id, nav_result, slots, intent_type)

    except Exception as e:
        logger.error("[NAV] 路线规划异常: %s", e)
        traceback.print_exc()
        await send_nav_error(websocket, f"路线规划失败: {e}")


async def finalize_poi_selection(
    session_id: str, websocket: WebSocket, agent: Optional[RealtimeAgent],
) -> None:
    pending = pending_nav.pop(session_id, None)
    if not pending:
        return
    slots = pending.get("slots", {})
    intent_type = pending.get("intent_type", "basic_navigation")
    origin_info = pending.get("origin_resolved")
    dest_info = pending.get("destination_resolved")
    if origin_info:
        slots["origin"] = origin_info["name"]
        slots["origin_location"] = origin_info["location"]
    if dest_info:
        slots["destination"] = dest_info["name"]
        slots["destination_location"] = dest_info["location"]
    await execute_navigation_with_slots(
        slots=slots, websocket=websocket, agent=agent, session_id=session_id,
        intent_type=intent_type, origin_info=origin_info, dest_info=dest_info,
    )


async def run_stage2_with_slots(
    slots: dict, intent_type: str, websocket: WebSocket,
    agent: Optional[RealtimeAgent], session_id: str,
) -> None:
    await execute_navigation_with_slots(
        slots=slots, websocket=websocket, agent=agent, session_id=session_id,
        intent_type=intent_type, processing_message="正在查询路线...",
    )


# ═══════════════════════════════════════════
#  导航意图管线（Stage 1）
# ═══════════════════════════════════════════

async def run_nav_pipeline(
    user_text: str, websocket: WebSocket,
) -> tuple[bool, Optional[dict], str]:
    try:
        await send_nav_status(websocket, "processing", "正在分析导航意图...")
        logger.info("[NAV] 触发导航管线: %s", user_text)

        from app.tools.analysis_tools import async_trigger, async_run_navigation
        result_text = await async_trigger(user_text)
        nav_data = parse_nav_result(result_text)
        nav_data = IntentResult.model_validate(nav_data).model_dump(mode="python")

        if nav_data.get("is_navigation") is False:
            await send_nav_status(websocket, "done", "非导航需求")
            return False, nav_data, result_text

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

        if nav_data.get("needs_clarification"):
            await send_nav_status(websocket, "done", nav_data.get("clarification_question", "需要补充导航信息"))
            return True, nav_data, result_text

        slots = nav_data.get("slots", {})
        intent_type = nav_data.get("intent_type", "")
        required_missing = get_missing_slots(slots, intent_type)
        if required_missing:
            await send_nav_status(websocket, "done", "等待补充导航信息")
            return True, nav_data, result_text

        nav_result_text = await async_run_navigation({"intent_type": intent_type, "slots": slots})
        nav_result = parse_nav_result(nav_result_text)
        nav_data["navigation_result"] = nav_result
        status = nav_result.get("status", "")

        if intent_type == "life_service" and status in ("need_selection", "error"):
            retry_result = await try_life_service_nearby_retry(slots)
            if isinstance(retry_result, dict):
                nav_result = retry_result
                nav_data["navigation_result"] = nav_result
                status = nav_result.get("status", "")

        if status in ("ok", "success"):
            await send_route_result_fast(websocket, nav_result, nav_data.get("slots", {}))
        elif status == "need_selection":
            nav_result = validate_need_selection_result(nav_result)
            nav_data["navigation_result"] = nav_result
            await websocket.send_json({
                "type": "nav_poi_candidates",
                "candidates": nav_result["candidates"],
                "origin_candidates": nav_result["origin_candidates"],
                "destination_candidates": nav_result["destination_candidates"],
            })

        await send_nav_status(websocket, "done", "导航分析完成")
        return True, nav_data, result_text

    except Exception as e:
        logger.error("[NAV] 导航管线异常: %s", e)
        traceback.print_exc()
        await send_nav_error(websocket, f"导航分析失败: {e}")
        return False, None, ""


# ═══════════════════════════════════════════
#  文本分流入口
# ═══════════════════════════════════════════

async def route_text_by_flowchart(
    user_text: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
    detect_nav_intent_fn=None,
) -> None:
    """按流程图执行文本分流：意图判断 -> 导航/闲聊 -> RealtimeAgent。"""
    async with get_session_route_lock(session_id):
        llm_text = user_text
        if detect_nav_intent_fn and detect_nav_intent_fn(user_text):
            memory_hint = await build_nav_memory_hint_for_llm(session_id)
            if memory_hint:
                llm_text = f"{user_text}{memory_hint}"

        is_navigation, nav_data, _ = await run_nav_pipeline(llm_text, websocket)

        from app.tools.video_tools import get_current_visual_state
        visual_state = await get_current_visual_state()

        if is_navigation and isinstance(nav_data, dict):
            slots = nav_data.get("slots", {})
            intent_type = nav_data.get("intent_type", "")

            # 记忆补槽
            prev_slots = await load_nav_context(session_id)
            current_loc = session_current_location.get(session_id)
            origin_from_current_location = False

            if (
                isinstance(current_loc, dict)
                and current_loc.get("location")
                and should_use_current_location(user_text, intent_type, slots)
            ):
                slots["origin"] = current_loc.get("name") or "当前位置"
                slots["origin_location"] = current_loc.get("location")
                origin_from_current_location = True

            if isinstance(prev_slots, dict) and prev_slots:
                fill_keys = ("origin", "travel_mode") if intent_type == "life_service" else ("origin", "destination", "travel_mode")
                filled_from_prev = set()
                for key in fill_keys:
                    if not slots.get(key) and prev_slots.get(key):
                        slots[key] = prev_slots[key]
                        filled_from_prev.add(key)
                if "origin" in filled_from_prev and not slots.get("origin_location") and prev_slots.get("origin_location") and not origin_from_current_location:
                    slots["origin_location"] = prev_slots["origin_location"]
                if "destination" in filled_from_prev and not slots.get("destination_location") and prev_slots.get("destination_location"):
                    slots["destination_location"] = prev_slots["destination_location"]

            if intent_type == "life_service":
                slots.pop("destination", None)
                slots.pop("destination_location", None)

            missing_slots = get_missing_slots(slots, intent_type)
            await save_nav_context(session_id, dict(slots))

            if missing_slots:
                pending_nav[session_id] = {
                    "slots": dict(slots), "intent_type": intent_type, "stage": "slot_fill",
                    "missing_slots": list(missing_slots),
                    "origin_resolved": None, "destination_resolved": None,
                    "has_origin_candidates": False, "has_destination_candidates": False,
                }
                await websocket.send_json({
                    "type": "nav_missing_slots",
                    "missing": missing_slots,
                    "current_slots": {"origin": slots.get("origin", ""), "destination": slots.get("destination", ""), "travel_mode": slots.get("travel_mode", "")},
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
                slots = (nav_data or {}).get("slots", {})
                await publish_need_selection(session_id, websocket, slots, nav_result, (nav_data or {}).get("intent_type", "basic_navigation"))
                return
            if isinstance(nav_result, dict) and nav_result.get("status") in ("ok", "success"):
                slots = (nav_data or {}).get("slots", {})
                defer_nav_broadcast_until_frontend(session_id, slots, (nav_data or {}).get("intent_type", ""))
                return
            summary = build_nav_broadcast_text(nav_data, user_text)
            if visual_state:
                summary += f"\n当前视觉环境：{visual_state}"
            await inject_text_to_agent(agent, session_id, summary)
            return

        # 非导航
        non_nav_text = user_text
        if visual_state:
            non_nav_text = f"{user_text}\n[视觉状态] {visual_state}"
        await inject_text_to_agent(agent, session_id, non_nav_text)
