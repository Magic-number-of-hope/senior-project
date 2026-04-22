# -*- coding: utf-8 -*-
"""路线规划辅助 — 快路径、直接规划、附近重试。"""
import asyncio
from typing import Optional

from agentscope import logger
from fastapi import WebSocket

from app.services.nav_utils import (
    build_radius_retry_list,
    extract_radius_from_constraint,
    tool_response_to_json,
)


async def ensure_map_fields(nav_result: dict, slots: dict) -> dict:
    """确保前端 JS API 路线规划所需字段齐全。"""
    if not nav_result.get("origin_location") and slots.get("origin_location"):
        nav_result["origin_location"] = slots["origin_location"]
    if not nav_result.get("destination_location") and slots.get("destination_location"):
        nav_result["destination_location"] = slots["destination_location"]
    if not nav_result.get("route_mode"):
        nav_result["route_mode"] = slots.get("travel_mode", "driving")

    waypoint_names = [
        str(w).strip()
        for w in (nav_result.get("waypoints", []) or slots.get("waypoints", []) or [])
        if str(w).strip()
    ]
    nav_result["waypoints"] = waypoint_names

    waypoint_locations = (
        list(nav_result.get("waypoint_locations", []) or [])
        or list(slots.get("waypoint_locations", []) or [])
    )
    if not waypoint_locations and waypoint_names:
        try:
            from app.tools.amap_tools import geocode
            resolved = []
            for wp_name in waypoint_names:
                resp = await geocode(wp_name)
                data = tool_response_to_json(resp)
                if isinstance(data, dict) and data.get("status") == "ok" and data.get("location"):
                    resolved.append(data["location"])
            if resolved:
                waypoint_locations = resolved
                slots["waypoint_locations"] = resolved
        except Exception as e:
            logger.warning("[NAV] 途经点坐标解析失败: %s", e)

    if waypoint_locations:
        nav_result["waypoint_locations"] = waypoint_locations

    # 清理遗留字段
    for key in ("polyline", "routes", "segments", "route_count"):
        nav_result.pop(key, None)
    return nav_result


async def send_route_result_fast(websocket: WebSocket, nav_result: dict, slots: dict) -> None:
    """返回前端 JS API 所需导航参数。"""
    await ensure_map_fields(nav_result, slots)
    await websocket.send_json({"type": "nav_route_result", "route_result": nav_result})


async def try_direct_route_planning(slots: dict) -> Optional[dict]:
    """坐标齐全时直接返回前端所需参数，绕过导航校验 LLM。"""
    origin_loc = slots.get("origin_location", "")
    dest_loc = slots.get("destination_location", "")
    if not origin_loc or not dest_loc:
        return None
    try:
        from app.tools.amap_tools import geocode
        mode = slots.get("travel_mode", "driving")
        waypoint_locations = list(slots.get("waypoint_locations", []) or [])
        waypoint_names = [str(w).strip() for w in (slots.get("waypoints", []) or []) if str(w).strip()]
        if not waypoint_locations and waypoint_names:
            resolved = []
            for wp_name in waypoint_names:
                resp = await geocode(wp_name)
                data = tool_response_to_json(resp)
                if not isinstance(data, dict) or data.get("status") != "ok" or not data.get("location"):
                    return None
                resolved.append(data["location"])
            waypoint_locations = resolved
            slots["waypoint_locations"] = resolved
        return {
            "status": "success",
            "origin_name": slots.get("origin", ""),
            "destination_name": slots.get("destination", ""),
            "origin_location": origin_loc,
            "destination_location": dest_loc,
            "route_mode": mode,
            "waypoints": waypoint_names,
            "waypoint_locations": waypoint_locations,
            "distance": "", "duration": "", "taxi_cost": "", "steps": [],
        }
    except Exception as e:
        logger.warning("[NAV] 直接路线规划失败: %s", e)
        return None


async def try_life_service_nearby_retry(slots: dict) -> Optional[dict]:
    """life_service 在小半径无结果时自动扩圈重试。"""
    origin_loc = slots.get("origin_location", "")
    poi_type = slots.get("poi_type", "")
    if not origin_loc or not poi_type:
        return None
    try:
        lng, lat = [x.strip() for x in origin_loc.split(",", 1)]
    except Exception:
        return None

    from app.tools.amap_tools import search_nearby_pois

    base_radius = extract_radius_from_constraint(slots.get("poi_constraint", ""))
    radii = build_radius_retry_list(base_radius)

    for radius in radii:
        resp = await search_nearby_pois(lng, lat, poi_type, radius=radius)
        data = tool_response_to_json(resp)
        if not isinstance(data, dict):
            continue
        if data.get("status") == "ok" and data.get("pois"):
            dest_cands = []
            for p in data.get("pois", [])[:5]:
                dest_cands.append({
                    "name": p.get("name", ""),
                    "address": p.get("address", ""),
                    "location": p.get("location", ""),
                    "cityname": p.get("cityname", ""),
                    "tel": p.get("tel", ""),
                    "type_name": p.get("type", ""),
                    "distance": str(p.get("distance", "")) if p.get("distance") is not None else "",
                })
            if dest_cands:
                slots["poi_constraint"] = f"附近{radius}米"
                return {
                    "status": "need_selection",
                    "origin_candidates": [],
                    "destination_candidates": dest_cands,
                    "origin_name": slots.get("origin", "当前位置"),
                    "origin_location": origin_loc,
                    "destination_name": None,
                    "destination_location": None,
                }

    max_radius = max(radii) if radii else base_radius
    return {"status": "error", "message": f"在当前位置{max_radius}米内未找到{poi_type}，建议放宽范围后重试。"}


async def try_fast_nav_without_llm(slots: dict) -> Optional[dict]:
    """优先走纯高德快路径：歧义检测 + 直接规划。"""
    origin_name = slots.get("origin", "")
    dest_name = slots.get("destination", "")
    mode = slots.get("travel_mode", "")
    if not origin_name or not dest_name or not mode:
        return None

    origin_loc = slots.get("origin_location", "")
    dest_loc = slots.get("destination_location", "")
    if origin_loc and dest_loc:
        return await try_direct_route_planning(slots)

    from app.tools.amap_tools import geocode
    logger.info("[NAV-FAST] 进入无LLM快路径 geocode 检测")

    origin_task = None if origin_loc else geocode(origin_name)
    dest_task = None if dest_loc else geocode(dest_name)

    if origin_task and dest_task:
        origin_resp, dest_resp = await asyncio.gather(origin_task, dest_task)
    elif origin_task:
        origin_resp = await origin_task
        dest_resp = None
    elif dest_task:
        origin_resp = None
        dest_resp = await dest_task
    else:
        origin_resp = dest_resp = None

    origin_data = tool_response_to_json(origin_resp) if origin_resp else {"status": "ok", "name": origin_name, "location": origin_loc}
    dest_data = tool_response_to_json(dest_resp) if dest_resp else {"status": "ok", "name": dest_name, "location": dest_loc}

    if not origin_data or not dest_data:
        return None

    if origin_data.get("status") == "need_selection" or dest_data.get("status") == "need_selection":
        return {
            "status": "need_selection",
            "origin_candidates": origin_data.get("candidates", []) if origin_data.get("status") == "need_selection" else [],
            "destination_candidates": dest_data.get("candidates", []) if dest_data.get("status") == "need_selection" else [],
            "origin_name": origin_data.get("name") if origin_data.get("status") == "ok" else None,
            "origin_location": origin_data.get("location") if origin_data.get("status") == "ok" else None,
            "destination_name": dest_data.get("name") if dest_data.get("status") == "ok" else None,
            "destination_location": dest_data.get("location") if dest_data.get("status") == "ok" else None,
        }

    if origin_data.get("status") != "ok" or dest_data.get("status") != "ok":
        return None

    slots_with_loc = dict(slots)
    slots_with_loc["origin"] = origin_data.get("name", origin_name) or origin_name
    slots_with_loc["destination"] = dest_data.get("name", dest_name) or dest_name
    slots_with_loc["origin_location"] = origin_data.get("location", origin_loc) or origin_loc
    slots_with_loc["destination_location"] = dest_data.get("location", dest_loc) or dest_loc

    direct_result = await try_direct_route_planning(slots_with_loc)
    if direct_result is None:
        return None
    slots.update(slots_with_loc)
    return direct_result
