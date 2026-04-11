# -*- coding: utf-8 -*-
"""导航场景多智能体服务端（Whisper ASR + 视频分析架构）

新架构数据流：
  前端音频(PCM16) → 后端 Whisper ASR → 文本
    ├─→ 意图识别智能体(ReActAgent): 判断是否导航 → 槽位填充
    │     └─→ 导航校验智能体(ReActAgent): POI 校验 + 路线规划
    └─→ 实时输出智能体(RealtimeAgent): 语音/文本回复

  前端视频帧(JPEG) → 抽帧 + 变化检测 → qwen-vl-max 分析
    └─→ 实时输出智能体: 融合视觉信息回复
"""
import asyncio
import base64
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

# 确保 myAgent 目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

from agentscope import logger
from agentscope.agent import RealtimeAgent
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg
from agentscope.realtime import (
    DashScopeRealtimeModel,
    GeminiRealtimeModel,
    OpenAIRealtimeModel,
    ClientEvents,
    ServerEvents,
)
from agentscope.tool import Toolkit
from models.intent_schema import IntentResult
from models.nav_result_schema import NeedSelectionResult

from prompts.interaction_prompt import INTERACTION_PROMPT
from config.settings import (
    DASHSCOPE_API_KEY,
    AMAP_API_KEY,
    AMAP_WEB_KEY,
    AMAP_WEB_SECRET,
    REALTIME_MODEL_NAME,
    NAV_TRIGGER_KEYWORDS,
)

app = FastAPI()


@app.on_event("shutdown")
async def _shutdown_cleanup() -> None:
    """应用关闭时清理全局资源。"""
    from tools.amap_tools import close_amap_session

    await close_amap_session()


# ── 导航关键词检测 ──
_NAV_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in NAV_TRIGGER_KEYWORDS),
)
_CURRENT_LOCATION_HINT_PATTERN = re.compile(
    r"我现在|当前位置|附近|周边|离我|就近|最近|这里|这儿",
)
_CONTEXT_CONTINUATION_PATTERN = re.compile(
    r"再去|然后去|接着去|继续去|下一站|下一步",
)

# ── 挂起的 POI 选择状态（session_id → 选择上下文）──
_pending_nav: dict = {}

# ── 会话导航上下文记忆（基于 AgentScope InMemoryMemory）──
_nav_context_memory = InMemoryMemory()
_NAV_CONTEXT_MARK = "nav_context"

# ── 会话级分流锁（避免同一会话并发分流导致串台）──
_session_route_locks: dict = {}

# ── 会话级当前位置缓存（session_id -> {location,name,...}）──
_session_current_location: dict = {}

# ── 会话级 Agent 注入锁（避免 append/create 并发交错导致漏播报）──
_session_agent_input_locks: dict = {}


def _get_session_route_lock(session_id: str) -> asyncio.Lock:
    """获取会话级文本分流锁。"""
    lock = _session_route_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_route_locks[session_id] = lock
    return lock


def _get_session_agent_input_lock(session_id: str) -> asyncio.Lock:
    """获取会话级 Agent 注入锁。"""
    lock = _session_agent_input_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_agent_input_locks[session_id] = lock
    return lock


async def _load_nav_context(session_id: str) -> dict:
    """从 AgentScope 记忆中读取会话最新导航槽位。"""
    msgs = await _nav_context_memory.get_memory(
        mark=session_id,
        prepend_summary=False,
    )
    for msg in reversed(msgs):
        if not isinstance(msg.content, str):
            continue
        try:
            data = json.loads(msg.content)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


async def _save_nav_context(session_id: str, slots: dict) -> None:
    """将会话最新导航槽位写入 AgentScope 记忆（仅保留最新一条）。"""
    msgs = await _nav_context_memory.get_memory(
        mark=session_id,
        prepend_summary=False,
    )
    if msgs:
        await _nav_context_memory.delete([m.id for m in msgs])

    await _nav_context_memory.add(
        Msg(
            name=session_id,
            role="system",
            content=json.dumps(slots, ensure_ascii=False),
            metadata={"type": _NAV_CONTEXT_MARK},
        ),
        marks=[_NAV_CONTEXT_MARK, session_id],
    )


def detect_nav_intent(text: str) -> bool:
    """检测文本中是否包含导航意图关键词"""
    if not text or len(text.strip()) < 2:
        return False
    return bool(_NAV_PATTERN.search(text))


def _get_missing_slots(slots: dict, intent_type: str = "") -> list[str]:
    """按意图类型返回缺失的必要槽位。"""
    missing = []

    # 生活服务类（如“附近加油站”）不应强制要求 destination。
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

    # 生活服务搜索默认可用当前位置作为检索中心。
    if intent_type == "life_service":
        return True

    text = (user_text or "").strip()
    if not text:
        return False

    # 明确是“继续上一段路线”时，优先沿用上下文而不是当前位置。
    if _CONTEXT_CONTINUATION_PATTERN.search(text):
        return False

    # 用户显式提到“我现在/附近”等，优先当前位置。
    if _CURRENT_LOCATION_HINT_PATTERN.search(text):
        return True

    # 常见“去某地”且未给起点时，也优先当前位置。
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
    if step_texts:
        parts.append(f"先{step_texts}。")
    if len(steps) > 3:
        parts.append(f"共{len(steps)}个导航步骤，已发送到您的设备上。")

    return "".join(parts)


def _validate_need_selection_result(nav_result: dict) -> dict:
    """严格校验 need_selection 输出格式，不做兼容转换。"""
    validated = NeedSelectionResult.model_validate(nav_result)
    result = validated.model_dump(mode="python")

    # 前端需要 merged candidates 字段，按接口要求直接生成。
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


async def _ensure_map_fields(
    nav_result: dict,
    slots: dict,
    *,
    fetch_polyline: bool = True,
) -> dict:
    """确保路线结果中包含前端地图所需的 origin_location / destination_location / polyline。

    LLM 不输出 polyline（太长会导致生成极慢），此函数直接调 API 获取。
    """
    # 回填坐标
    if not nav_result.get("origin_location") and slots.get("origin_location"):
        nav_result["origin_location"] = slots["origin_location"]
    if not nav_result.get("destination_location") and slots.get("destination_location"):
        nav_result["destination_location"] = slots["destination_location"]

    # 通过 API 获取 polyline（可按需异步回填）
    origin_loc = nav_result.get("origin_location", "")
    dest_loc = nav_result.get("destination_location", "")
    polyline = nav_result.get("polyline", "")
    if fetch_polyline and origin_loc and dest_loc and (not polyline or len(polyline) < 50):
        logger.info("[NAV] 通过 API 获取 polyline ...")
        try:
            from tools.amap_tools import route_planning
            mode = slots.get("travel_mode", "driving")
            resp = await route_planning(
                origin_loc,
                dest_loc,
                mode=mode,
                include_polyline=True,
            )
            raw = resp.content[0]
            text = raw["text"] if isinstance(raw, dict) else raw.text
            route_data = json.loads(text)
            if route_data.get("status") in ("ok", "success"):
                if route_data.get("polyline"):
                    nav_result["polyline"] = route_data["polyline"]
                if not nav_result.get("origin_location"):
                    nav_result["origin_location"] = route_data.get("origin_location", "")
                if not nav_result.get("destination_location"):
                    nav_result["destination_location"] = route_data.get("destination_location", "")
        except Exception as e:
            logger.warning("[NAV] polyline 获取失败: %s", e)

    return nav_result


async def _backfill_polyline_and_push(
    websocket: WebSocket,
    nav_result: dict,
    slots: dict,
) -> None:
    """异步补全 polyline，并将更新后的路线结果再次推送到前端。"""
    try:
        if nav_result.get("polyline"):
            return

        await _ensure_map_fields(nav_result, slots, fetch_polyline=True)
        if nav_result.get("polyline"):
            await websocket.send_json({
                "type": "nav_route_result",
                "route_result": nav_result,
            })
    except Exception as e:
        logger.warning("[NAV] 异步回填 polyline 失败: %s", e)


async def _send_route_result_fast(
    websocket: WebSocket,
    nav_result: dict,
    slots: dict,
) -> None:
    """优先返回首屏路线结果，再异步补全 polyline。"""
    await _ensure_map_fields(nav_result, slots, fetch_polyline=False)
    await websocket.send_json({
        "type": "nav_route_result",
        "route_result": nav_result,
    })
    asyncio.create_task(_backfill_polyline_and_push(websocket, nav_result, slots))


async def _try_direct_route_planning(slots: dict) -> Optional[dict]:
    """坐标齐全时直接调用高德路线规划，绕过导航校验 LLM。"""
    origin_loc = slots.get("origin_location", "")
    dest_loc = slots.get("destination_location", "")
    if not origin_loc or not dest_loc:
        return None

    try:
        from tools.amap_tools import route_planning

        mode = slots.get("travel_mode", "driving")
        resp = await route_planning(
            origin=origin_loc,
            destination=dest_loc,
            mode=mode,
            include_polyline=False,
        )
        raw = resp.content[0]
        text = raw["text"] if isinstance(raw, dict) else raw.text
        route_data = json.loads(text)
        if route_data.get("status") not in ("ok", "success"):
            return None

        return {
            "status": "success",
            "origin_name": slots.get("origin", ""),
            "destination_name": slots.get("destination", ""),
            "origin_location": origin_loc,
            "destination_location": dest_loc,
            "distance": route_data.get("distance", ""),
            "duration": route_data.get("duration", ""),
            "taxi_cost": route_data.get("taxi_cost", ""),
            "steps": route_data.get("steps", []),
        }
    except Exception as e:
        logger.warning("[NAV] 直接路线规划失败，回退 LLM 流程: %s", e)
        return None


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


async def _try_life_service_nearby_retry(slots: dict) -> Optional[dict]:
    """life_service 在小半径无结果时自动扩圈重试。"""
    origin_loc = slots.get("origin_location", "")
    poi_type = slots.get("poi_type", "")
    if not origin_loc or not poi_type:
        return None

    try:
        lng, lat = [x.strip() for x in origin_loc.split(",", 1)]
    except Exception:
        return None

    from tools.amap_tools import search_nearby_pois

    base_radius = _extract_radius_from_constraint(slots.get("poi_constraint", ""))
    radii = _build_radius_retry_list(base_radius)

    for radius in radii:
        resp = await search_nearby_pois(lng, lat, poi_type, radius=radius)
        data = _tool_response_to_json(resp)
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
    return {
        "status": "error",
        "message": f"在当前位置{max_radius}米内未找到{poi_type}，建议放宽范围后重试。",
    }


async def _try_fast_nav_without_llm(slots: dict) -> Optional[dict]:
    """优先走纯高德快路径：歧义检测 + 直接规划，避免导航校验 LLM 时延。"""
    origin_name = slots.get("origin", "")
    dest_name = slots.get("destination", "")
    mode = slots.get("travel_mode", "")
    if not origin_name or not dest_name or not mode:
        return None

    origin_loc = slots.get("origin_location", "")
    dest_loc = slots.get("destination_location", "")

    # 坐标已齐全：直接路线规划
    if origin_loc and dest_loc:
        return await _try_direct_route_planning(slots)

    from tools.amap_tools import geocode

    logger.info("[NAV-FAST] 进入无LLM快路径 geocode 检测")

    # 并发 geocode，减少等待
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
        origin_resp = None
        dest_resp = None

    origin_data = _tool_response_to_json(origin_resp) if origin_resp else {
        "status": "ok",
        "name": origin_name,
        "location": origin_loc,
    }
    dest_data = _tool_response_to_json(dest_resp) if dest_resp else {
        "status": "ok",
        "name": dest_name,
        "location": dest_loc,
    }

    if not origin_data or not dest_data:
        return None

    # 任一侧歧义：直接返回候选，避免等待 LLM 组织
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

    # 无结果或错误：返回 None 回退到 LLM
    if origin_data.get("status") != "ok" or dest_data.get("status") != "ok":
        return None

    # 两侧都已解析成功，直接路线规划
    slots_with_loc = dict(slots)
    slots_with_loc["origin"] = origin_data.get("name", origin_name) or origin_name
    slots_with_loc["destination"] = dest_data.get("name", dest_name) or dest_name
    slots_with_loc["origin_location"] = origin_data.get("location", origin_loc) or origin_loc
    slots_with_loc["destination_location"] = dest_data.get("location", dest_loc) or dest_loc

    direct_result = await _try_direct_route_planning(slots_with_loc)
    if direct_result is None:
        return None

    # 同步写回，确保后续上下文一致
    slots.update(slots_with_loc)
    return direct_result


# ═══════════════════════════════════════════
#  导航分析管线
# ═══════════════════════════════════════════

async def run_nav_pipeline(
    user_text: str,
    websocket: WebSocket,
) -> tuple[bool, Optional[dict], str]:
    """异步执行导航分析管线并推送结果到前端。

    流程: 用户文本 → 意图识别智能体 → (导航校验智能体) → 前端
    """
    try:
        await websocket.send_json({
            "type": "nav_status_update",
            "status": "processing",
            "message": "正在分析导航意图...",
        })
        logger.info("[NAV] 触发导航管线: %s", user_text)

        from tools.analysis_tools import _async_run_navigation, _async_trigger
        result_text = await _async_trigger(user_text)

        logger.info("[NAV] 分析结果: %s", result_text[:200])

        nav_data = _parse_nav_result(result_text)
        nav_data = IntentResult.model_validate(nav_data).model_dump(mode="python")

        # 非导航需求直接返回
        if nav_data.get("is_navigation") is False:
            await websocket.send_json({
                "type": "nav_status_update",
                "status": "done",
                "message": "非导航需求",
            })
            return False, nav_data, result_text

        # 推送意图识别结果
        if "intent_type" in nav_data:
            await websocket.send_json({
                "type": "nav_intent_result",
                "intent_result": {
                    "intent_type": nav_data.get("intent_type", ""),
                    "slots": nav_data.get("slots", {}),
                    "confidence": nav_data.get("confidence", 0),
                    "needs_clarification": nav_data.get(
                        "needs_clarification", False,
                    ),
                    "clarification_question": nav_data.get(
                        "clarification_question", None,
                    ),
                },
            })

        if nav_data.get("needs_clarification"):
            await websocket.send_json({
                "type": "nav_status_update",
                "status": "done",
                "message": nav_data.get(
                    "clarification_question", "需要补充导航信息",
                ),
            })
            return True, nav_data, result_text

        # ── 必要槽位缺失时跳过 Stage 2，由上层处理 ──
        slots = nav_data.get("slots", {})
        intent_type = nav_data.get("intent_type", "")
        _required_missing = _get_missing_slots(slots, intent_type)
        if _required_missing:
            logger.info(
                "[NAV] 必要槽位缺失 %s，跳过 Stage 2",
                _required_missing,
            )
            await websocket.send_json({
                "type": "nav_status_update",
                "status": "done",
                "message": "等待补充导航信息",
            })
            return True, nav_data, result_text

        navigation_request = {
            "intent_type": nav_data.get("intent_type", ""),
            "slots": nav_data.get("slots", {}),
        }
        nav_result_text = await _async_run_navigation(navigation_request)
        nav_result = _parse_nav_result(nav_result_text)
        nav_data["navigation_result"] = nav_result

        status = nav_result.get("status", "")

        if intent_type == "life_service" and status in ("need_selection", "error"):
            retry_result = await _try_life_service_nearby_retry(slots)
            if isinstance(retry_result, dict):
                nav_result = retry_result
                nav_data["navigation_result"] = nav_result
                status = nav_result.get("status", "")

        if status in ("ok", "success"):
            await _send_route_result_fast(
                websocket,
                nav_result,
                nav_data.get("slots", {}),
            )
        elif status == "need_selection":
            nav_result = _validate_need_selection_result(nav_result)
            nav_data["navigation_result"] = nav_result
            await websocket.send_json({
                "type": "nav_poi_candidates",
                "candidates": nav_result["candidates"],
                "origin_candidates": nav_result["origin_candidates"],
                "destination_candidates": nav_result["destination_candidates"],
            })

        await websocket.send_json({
            "type": "nav_status_update",
            "status": "done",
            "message": "导航分析完成",
        })
        return True, nav_data, result_text

    except Exception as e:
        logger.error("[NAV] 导航管线异常: %s", e)
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "nav_error",
                "message": f"导航分析失败: {str(e)}",
            })
        except Exception:
            pass
        return False, None, ""


async def _inject_text_to_agent(
    agent: Optional[RealtimeAgent],
    session_id: str,
    text: str,
) -> None:
    """将文本注入 RealtimeAgent 并触发回复生成。"""
    if not text.strip():
        return
    if not agent:
        logger.warning("[BROADCAST] 注入失败：agent 不存在，session=%s", session_id)
        return

    lock = _get_session_agent_input_lock(session_id)
    async with lock:
        try:
            logger.info("[BROADCAST] 开始注入播报文本，session=%s", session_id)

            # 1. 追加文本到对话上下文
            append_event = ClientEvents.from_json({
                "type": "client_text_append",
                "session_id": session_id,
                "text": text,
            })
            await agent.handle_input(append_event)

            # 2. 触发模型生成回复（相当于"按回车"）
            create_event = ClientEvents.from_json({
                "type": "client_response_create",
                "session_id": session_id,
            })
            await agent.handle_input(create_event)
            logger.info("[BROADCAST] 已触发 response_create，session=%s", session_id)
        except Exception as e:
            logger.error("[BROADCAST] 注入播报失败(session=%s): %s", session_id, e)
            traceback.print_exc()


async def _send_nav_status(
    websocket: WebSocket,
    status: str,
    message: str,
) -> None:
    """统一发送导航状态更新事件。"""
    await websocket.send_json({
        "type": "nav_status_update",
        "status": status,
        "message": message,
    })


async def _send_nav_error(websocket: WebSocket, message: str) -> None:
    """统一发送导航错误事件。"""
    try:
        await websocket.send_json({
            "type": "nav_error",
            "message": message,
        })
    except Exception:
        pass


async def _publish_need_selection(
    session_id: str,
    websocket: WebSocket,
    slots: dict,
    nav_result: dict,
    intent_type: str = "basic_navigation",
    *,
    log_wait: bool = False,
) -> None:
    """统一处理 need_selection：严格校验后推送候选、缓存挂起状态。"""
    nav_result = _validate_need_selection_result(nav_result)
    origin_cands = nav_result.get("origin_candidates", [])
    dest_cands = nav_result.get("destination_candidates", [])

    origin_resolved = None
    if nav_result.get("origin_name") and nav_result.get("origin_location"):
        origin_resolved = {
            "name": nav_result.get("origin_name"),
            "location": nav_result.get("origin_location"),
            "cityname": "",
        }

    destination_resolved = None
    if nav_result.get("destination_name") and nav_result.get("destination_location"):
        destination_resolved = {
            "name": nav_result.get("destination_name"),
            "location": nav_result.get("destination_location"),
            "cityname": "",
        }

    await websocket.send_json({
        "type": "nav_poi_candidates",
        "candidates": nav_result["candidates"],
        "origin_candidates": origin_cands,
        "destination_candidates": dest_cands,
    })

    _pending_nav[session_id] = {
        "slots": slots,
        "intent_type": intent_type,
        "origin_resolved": origin_resolved,
        "destination_resolved": destination_resolved,
        "has_origin_candidates": len(origin_cands) > 0,
        "has_destination_candidates": len(dest_cands) > 0,
    }

    if log_wait:
        logger.info(
            "[NAV] 等待用户选择候选地点 (origin=%d, dest=%d)",
            len(origin_cands), len(dest_cands),
        )


async def _broadcast_nav_summary(
    agent: Optional[RealtimeAgent],
    session_id: str,
    nav_result: object,
    slots: dict,
    intent_type: str = "",
) -> None:
    """统一播报导航结果并融合视觉上下文。"""
    from tools.video_tools import get_current_visual_state

    await _save_nav_context(session_id, dict(slots))
    nav_data = {
        "navigation_result": nav_result,
        "slots": slots,
        "intent_type": intent_type,
    }
    visual_state = await get_current_visual_state()
    summary = _build_nav_broadcast_text(nav_data, "")
    if visual_state:
        summary += f"\n当前视觉环境：{visual_state}"
    logger.info("[NAV] 准备注入路线播报，session=%s，summary=%s", session_id, summary[:180])
    await _inject_text_to_agent(agent, session_id, summary)


async def _execute_navigation_with_slots(
    slots: dict,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
    intent_type: str = "basic_navigation",
    *,
    processing_message: str,
    error_log_prefix: str,
    error_message_prefix: str,
    origin_info: Optional[dict] = None,
    dest_info: Optional[dict] = None,
) -> None:
    """统一执行 Stage 2 路线规划并处理结果。"""
    from tools.analysis_tools import _async_run_navigation

    try:
        await _send_nav_status(websocket, "processing", processing_message)

        # 快路径1：纯高德（含歧义检测与直接规划），无 LLM。
        fast_nav_result = await _try_fast_nav_without_llm(slots)
        if isinstance(fast_nav_result, dict):
            fast_status = fast_nav_result.get("status", "")
            if fast_status == "need_selection":
                await _publish_need_selection(
                    session_id,
                    websocket,
                    slots,
                    fast_nav_result,
                    intent_type=intent_type,
                    log_wait=True,
                )
                return
            if fast_status in ("ok", "success"):
                await _send_route_result_fast(websocket, fast_nav_result, slots)
                await _send_nav_status(websocket, "done", "导航分析完成")
                await _broadcast_nav_summary(
                    agent,
                    session_id,
                    fast_nav_result,
                    slots,
                    intent_type=intent_type,
                )
                return

        # 快路径：当起终点坐标齐全时，直接路线规划（不走导航校验 LLM）。
        direct_result = await _try_direct_route_planning(slots)
        if direct_result is not None:
            await _send_route_result_fast(websocket, direct_result, slots)
            await _send_nav_status(websocket, "done", "导航分析完成")
            await _broadcast_nav_summary(
                agent,
                session_id,
                direct_result,
                slots,
                intent_type=intent_type,
            )
            return

        navigation_request = {
            "intent_type": intent_type,
            "slots": slots,
        }
        nav_result_text = await _async_run_navigation(navigation_request)
        nav_result = _parse_nav_result(nav_result_text)

        if isinstance(nav_result, dict):
            status = nav_result.get("status", "")

            if intent_type == "life_service" and status in ("need_selection", "error"):
                retry_result = await _try_life_service_nearby_retry(slots)
                if isinstance(retry_result, dict):
                    nav_result = retry_result
                    status = nav_result.get("status", "")

            if status == "need_selection":
                await _publish_need_selection(
                    session_id,
                    websocket,
                    slots,
                    nav_result,
                    intent_type=intent_type,
                    log_wait=True,
                )
                return

            if status in ("ok", "success"):
                if origin_info and "origin_name" not in nav_result:
                    nav_result["origin_name"] = origin_info["name"]
                if dest_info and "destination_name" not in nav_result:
                    nav_result["destination_name"] = dest_info["name"]

                await _send_route_result_fast(websocket, nav_result, slots)

        await _send_nav_status(websocket, "done", "导航分析完成")
        await _broadcast_nav_summary(
            agent,
            session_id,
            nav_result,
            slots,
            intent_type=intent_type,
        )

    except Exception as e:
        logger.error("%s: %s", error_log_prefix, e)
        traceback.print_exc()
        await _send_nav_error(websocket, f"{error_message_prefix}: {str(e)}")


async def _finalize_poi_selection(
    session_id: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
) -> None:
    """用户完成所有 POI 候选选择后，将已解析坐标交给导航智能体规划路线。"""
    pending = _pending_nav.pop(session_id, None)
    if not pending:
        return

    slots = pending.get("slots", {})
    intent_type = pending.get("intent_type", "basic_navigation")
    origin_info = pending.get("origin_resolved")
    dest_info = pending.get("destination_resolved")

    # 用已选择的 POI 信息更新 slots，附带坐标供导航智能体直接使用
    if origin_info:
        slots["origin"] = origin_info["name"]
        slots["origin_location"] = origin_info["location"]
    if dest_info:
        slots["destination"] = dest_info["name"]
        slots["destination_location"] = dest_info["location"]

    logger.info(
        "[NAV] POI 选择完成，交给导航智能体规划: %s(%s) → %s(%s)",
        slots.get("origin", ""),
        slots.get("origin_location", ""),
        slots.get("destination", ""),
        slots.get("destination_location", ""),
    )
    await _execute_navigation_with_slots(
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


async def _run_stage2_with_slots(
    slots: dict,
    intent_type: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
) -> None:
    """槽位齐全后直接调用 Stage 2（导航校验智能体），跳过 Stage 1。"""
    await _execute_navigation_with_slots(
        slots=slots,
        websocket=websocket,
        agent=agent,
        session_id=session_id,
        intent_type=intent_type,
        processing_message="正在查询路线...",
        error_log_prefix="[NAV] Stage 2 执行异常",
        error_message_prefix="导航查询失败",
    )


async def route_text_by_flowchart(
    user_text: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
) -> None:
    """按流程图执行文本分流：意图判断 → 导航/闲聊 → RealtimeAgent。"""
    # 同一会话串行化分流处理，避免快速输入导致上下文并发覆盖。
    async with _get_session_route_lock(session_id):
        is_navigation, nav_data, _ = await run_nav_pipeline(
            user_text, websocket,
        )

        # 查询当前视觉状态并融合到最终播报输入
        from tools.video_tools import get_current_visual_state
        visual_state = await get_current_visual_state()

        if is_navigation and isinstance(nav_data, dict):
            # ── 必要槽位缺失检测：起点、终点、出行方式 ──
            slots = nav_data.get("slots", {})
            intent_type = nav_data.get("intent_type", "")

            # 先尝试用当前位置补全起点（若本轮未给出 origin）。
            current_loc = _session_current_location.get(session_id)
            origin_from_current_location = False
            if (
                current_loc
                and current_loc.get("location")
                and _should_use_current_location(user_text, intent_type, slots)
            ):
                slots["origin"] = current_loc.get("name") or "当前位置"
                slots["origin_location"] = current_loc["location"]
                origin_from_current_location = True
                logger.info(
                    "[NAV] 使用当前位置补全起点 origin=%s, location=%s",
                    slots.get("origin", ""),
                    slots.get("origin_location", ""),
                )

            # 从会话上下文补全缺失槽位（如用户说"坐公交怎么走"，沿用上次起终点）
            prev = await _load_nav_context(session_id)
            if prev:
                filled_from_context = set()

                if intent_type == "life_service":
                    # 附近服务类场景只补 origin/travel_mode，禁止补 destination。
                    # 目的地应由 poi_type 触发搜索得到，不能继承上次终点。
                    fill_keys = ("origin", "travel_mode")
                else:
                    fill_keys = ("origin", "destination", "travel_mode")

                for key in fill_keys:
                    if not slots.get(key) and prev.get(key):
                        slots[key] = prev[key]
                        filled_from_context.add(key)
                        logger.info("[NAV] 从上下文补全 %s=%s", key, prev[key])

                # 若本轮地点名称与上轮不同，清理可能残留的旧坐标，避免错配。
                if (
                    slots.get("origin") and prev.get("origin")
                    and slots["origin"] != prev["origin"]
                    and not origin_from_current_location
                ):
                    if slots.pop("origin_location", None):
                        logger.info("[NAV] 起点变化，清理旧坐标 origin_location")

                if (
                    slots.get("destination") and prev.get("destination")
                    and slots["destination"] != prev["destination"]
                ):
                    if slots.pop("destination_location", None):
                        logger.info("[NAV] 终点变化，清理旧坐标 destination_location")

                # 仅在"地点名称也沿用上下文"时，才复用对应坐标。
                if (
                    "origin" in filled_from_context
                    and not slots.get("origin_location")
                    and prev.get("origin_location")
                ):
                    slots["origin_location"] = prev["origin_location"]

                if (
                    "destination" in filled_from_context
                    and not slots.get("destination_location")
                    and prev.get("destination_location")
                ):
                    slots["destination_location"] = prev["destination_location"]

            # 附近服务场景：显式清理 destination，避免误用上轮终点直出旧路线。
            if intent_type == "life_service":
                # 这里即使上游误带 destination，也要在分流层兜底清理。
                if slots.pop("destination", None) is not None:
                    logger.info("[NAV] life_service 场景清理 destination")
                if slots.pop("destination_location", None) is not None:
                    logger.info("[NAV] life_service 场景清理 destination_location")

            missing_slots = _get_missing_slots(slots, intent_type)

            # 保存当前槽位到上下文（即使不完整也更新已有部分）
            await _save_nav_context(session_id, dict(slots))

            if missing_slots:
                _pending_nav[session_id] = {
                    "slots": dict(slots),
                    "intent_type": intent_type,
                    "stage": "slot_fill",
                    "missing_slots": list(missing_slots),
                    "origin_resolved": None,
                    "destination_resolved": None,
                    "has_origin_candidates": False,
                    "has_destination_candidates": False,
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
                logger.info(
                    "[NAV] 必要槽位缺失: %s，等待用户补充", missing_slots,
                )
                return

            # run_nav_pipeline 可能因初始缺槽位而跳过 Stage 2；
            # 若此处已通过上下文补齐，则立即补跑 Stage 2，避免直接进入兜底一句话播报。
            nav_result = nav_data.get("navigation_result")
            if not nav_result:
                logger.info("[NAV] 槽位已补齐但尚未执行 Stage 2，立即补跑导航校验")
                await _run_stage2_with_slots(
                    slots=slots,
                    intent_type=intent_type,
                    websocket=websocket,
                    agent=agent,
                    session_id=session_id,
                )
                return

        # 导航但信息不足（其他情况追问）
        if isinstance(nav_data, dict) and nav_data.get("needs_clarification"):
            ask = nav_data.get("clarification_question") or "请补充导航信息。"
            if visual_state:
                ask = f"{ask}\n当前视觉环境：{visual_state}"
            logger.info("[BROADCAST] 追问澄清: %s", ask[:120])
            await _inject_text_to_agent(agent, session_id, ask)
            return

        if is_navigation:
            # need_selection: 存储挂起状态，等用户选完再播报，不提前触发 Agent
            nav_result = (nav_data or {}).get("navigation_result")
            if isinstance(nav_result, dict) and nav_result.get("status") == "need_selection":
                slots = (nav_data or {}).get("slots", {})

                await _publish_need_selection(
                    session_id,
                    websocket,
                    slots,
                    nav_result,
                    intent_type=(nav_data or {}).get("intent_type", "basic_navigation"),
                    log_wait=True,
                )
                return  # 不播报，等待用户选择

            # 构建精简口语化摘要，避免向 RealtimeAgent 注入过大 JSON
            summary = _build_nav_broadcast_text(nav_data, user_text)
            if visual_state:
                summary += f"\n当前视觉环境：{visual_state}"

            logger.info("[BROADCAST] 注入播报文本: %s", summary[:200])
            await _inject_text_to_agent(agent, session_id, summary)
            return

        # 非导航请求：直接走闲聊/问答链路
        non_nav_text = user_text
        if visual_state:
            non_nav_text = f"{user_text}\n[视觉状态] {visual_state}"

        await _inject_text_to_agent(agent, session_id, non_nav_text)


def _parse_nav_result(text: str) -> dict:
    """严格解析智能体返回：仅允许单个 JSON 对象。"""
    if not text:
        raise ValueError("模型返回为空，无法解析 JSON")

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回不是 JSON 对象")
    return parsed


# ═══════════════════════════════════════════
#  Whisper ASR 处理
# ═══════════════════════════════════════════

async def whisper_transcribe(pcm_bytes: bytes) -> Optional[str]:
    """在线程池中调用 Whisper 转写，避免阻塞事件循环。"""
    from tools.whisper_tools import transcribe_pcm16
    return await asyncio.to_thread(transcribe_pcm16, pcm_bytes)


# ═══════════════════════════════════════════
#  视频帧处理
# ═══════════════════════════════════════════

async def handle_video_frame(
    jpeg_base64: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
) -> None:
    """处理一帧视频：变化检测 → qwen-vl-max → 更新状态 → 推送。"""
    try:
        from tools.video_tools import process_video_frame
        result = await process_video_frame(jpeg_base64)
        if result:
            # 推送视觉分析结果到前端
            await websocket.send_json({
                "type": "visual_analysis_result",
                "description": result,
            })
            logger.info("[VIDEO] 视觉分析: %s", result[:80])

            # 将视觉信息注入 RealtimeAgent 上下文
            await _inject_text_to_agent(
                agent,
                session_id,
                f"[视觉信息] {result}",
            )
    except Exception as e:
        logger.error("[VIDEO] 视频帧处理失败: %s", e)


# ═══════════════════════════════════════════
#  HTTP 路由
# ═══════════════════════════════════════════

@app.get("/")
async def get() -> FileResponse:
    """Serve the HTML test page."""
    html_path = Path(__file__).parent / "chatbot.html"
    return FileResponse(html_path)


@app.get("/api/check-models")
async def check_models() -> dict:
    """Check which model API keys are available."""
    return {
        "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "amap": bool(os.getenv("AMAP_API_KEY")),
    }


@app.get("/api/amap-key")
async def get_amap_key() -> dict:
    """返回高德 JS API 所需的 Web 端 Key 和安全密钥。"""
    return {
        "key": AMAP_WEB_KEY or AMAP_API_KEY,
        "secret": AMAP_WEB_SECRET,
    }


# ═══════════════════════════════════════════
#  事件转发（Agent → 前端）
# ═══════════════════════════════════════════

async def frontend_receive(
    websocket: WebSocket,
    frontend_queue: asyncio.Queue,
) -> None:
    """从 RealtimeAgent 队列取出事件转发给前端。"""
    transcript_buffer: dict[str, str] = {}

    try:
        while True:
            msg = await frontend_queue.get()
            payload = msg.model_dump()

            # 日志记录：真实文本在 delta 事件里累积，done 事件通常不带 transcript
            event_type = payload.get("type")
            if event_type == "agent_response_audio_transcript_delta":
                response_id = payload.get("response_id", "")
                item_id = payload.get("item_id", "")
                key = f"{response_id}:{item_id}"
                delta = payload.get("delta", "")
                transcript_buffer[key] = transcript_buffer.get(key, "") + delta

            elif event_type == "agent_response_audio_transcript_done":
                response_id = payload.get("response_id", "")
                item_id = payload.get("item_id", "")
                key = f"{response_id}:{item_id}"
                text = transcript_buffer.pop(key, "")
                logger.info("[AGENT-REPLY] %s", text[:200])

            await websocket.send_json(payload)

    except Exception as e:
        print(f"[ERROR] frontend_receive error: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════
#  WebSocket 主入口
# ═══════════════════════════════════════════

@app.websocket("/ws/{user_id}/{session_id}")
async def single_agent_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
) -> None:
    """WebSocket 端点 — Whisper ASR + 意图分析 + 视频处理。

    新架构核心流程：
      1. 前端发送 PCM16 音频帧 (client_audio_append)
      2. 后端缓冲音频，收到 client_audio_commit 后用 Whisper 转文字
        3. 转写文本先进入意图识别智能体并完成是否导航分流
            a) 非导航：直接注入 RealtimeAgent
            b) 导航：导航校验后再注入 RealtimeAgent播报
      4. 前端发送视频帧 (client_image_append)
      5. 后端抽帧+变化检测 → qwen-vl-max → 状态给 RealtimeAgent
    """
    agent = None
    audio_buffer = bytearray()  # PCM16 音频缓冲

    try:
        await websocket.accept()
        logger.info(
            "Connected: user_id=%s, session_id=%s",
            user_id, session_id,
        )

        frontend_queue: asyncio.Queue = asyncio.Queue()
        asyncio.create_task(
            frontend_receive(websocket, frontend_queue),
        )

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect as e:
                logger.info(
                    "WebSocket disconnected: user_id=%s, session_id=%s, "
                    "code=%s",
                    user_id, session_id,
                    getattr(e, "code", "unknown"),
                )
                break

            event_type = data.get("type", "")

            # ── 会话创建 ──
            if event_type == "client_session_create":
                client_event = ClientEvents.from_json(data)
                config = client_event.config
                agent_name = config.get("agent_name", "小导")
                model_provider = config.get("model_provider", "dashscope")

                sys_prompt = INTERACTION_PROMPT
                toolkit = Toolkit()

                if model_provider == "dashscope":
                    model = DashScopeRealtimeModel(
                        model_name=REALTIME_MODEL_NAME,
                        api_key=(
                            DASHSCOPE_API_KEY
                            or os.getenv("DASHSCOPE_API_KEY")
                        ),
                    )
                    logger.info(
                        "[SESSION] DashScope 模式 — "
                        "Whisper ASR + 意图识别 + 导航校验",
                    )

                elif model_provider == "gemini":
                    model = GeminiRealtimeModel(
                        model_name=(
                            "gemini-2.5-flash-native-audio-"
                            "preview-09-2025"
                        ),
                        api_key=os.getenv("GEMINI_API_KEY"),
                    )

                elif model_provider == "openai":
                    model = OpenAIRealtimeModel(
                        model_name="gpt-4o-realtime-preview",
                        api_key=os.getenv("OPENAI_API_KEY"),
                    )

                else:
                    raise ValueError(
                        f"Unsupported model provider: {model_provider}",
                    )

                agent = RealtimeAgent(
                    name=agent_name,
                    sys_prompt=sys_prompt,
                    model=model,
                    toolkit=toolkit,
                )
                await agent.start(frontend_queue)

                await websocket.send_json(
                    ServerEvents.ServerSessionCreatedEvent(
                        session_id=session_id,
                    ).model_dump(),
                )
                logger.info("Session created: %s", session_id)

            # ── 音频帧追加（缓冲 PCM16）──
            elif event_type == "client_audio_append":
                audio_b64 = data.get("audio", "")
                if audio_b64:
                    audio_buffer.extend(base64.b64decode(audio_b64))

                # 这里不直接转发给 RealtimeAgent，遵循流程图：
                # 先 Whisper 转文本，再做意图分流后统一注入。

            # ── 音频提交（Whisper 转写，仅回传文本）──
            elif event_type == "client_audio_commit":
                # 用 Whisper 转写缓冲的音频
                if len(audio_buffer) > 3200:
                    pcm_bytes = bytes(audio_buffer)
                    audio_buffer.clear()

                    async def _whisper_and_analyze(
                        pcm: bytes, ws: WebSocket,
                    ) -> None:
                        transcript = await whisper_transcribe(pcm)
                        if not transcript:
                            return
                        logger.info(
                            "[WHISPER] 转写结果: %s", transcript[:100],
                        )
                        # 推送转写文本到前端
                        await ws.send_json({
                            "type": "whisper_transcription",
                            "transcript": transcript,
                        })

                    asyncio.create_task(
                        _whisper_and_analyze(pcm_bytes, websocket),
                    )
                else:
                    audio_buffer.clear()

            # ── 文本输入 ──
            elif event_type == "client_text_append":
                client_event = ClientEvents.from_json(data)
                user_text = client_event.text
                logger.info("[TEXT-INPUT] %s", user_text[:100])

                # 文本同样按流程图分流
                asyncio.create_task(
                    route_text_by_flowchart(
                        user_text,
                        websocket,
                        agent,
                        session_id,
                    ),
                )

            # ── 视频帧（抽帧 + 变化检测 + qwen-vl-max）──
            elif event_type == "client_image_append":
                image_b64 = data.get("image", "")
                if image_b64:
                    asyncio.create_task(
                        handle_video_frame(
                            image_b64,
                            websocket,
                            agent,
                            session_id,
                        ),
                    )

            # ── 前端上报当前位置 ──
            elif event_type == "client_location_update":
                location = str(data.get("location", "")).strip()
                name = str(data.get("name", "")).strip() or "当前位置"

                if location and "," in location:
                    try:
                        lng_s, lat_s = location.split(",", 1)
                        float(lng_s.strip())
                        float(lat_s.strip())
                        _session_current_location[session_id] = {
                            "name": name,
                            "location": location,
                            "source": str(data.get("source", "browser")),
                            "accuracy": data.get("accuracy"),
                            "timestamp": data.get("timestamp"),
                        }
                        logger.info(
                            "[LOCATION] 更新当前位置 session=%s name=%s location=%s",
                            session_id,
                            name,
                            location,
                        )
                    except Exception:
                        logger.warning("[LOCATION] 非法坐标，忽略: %s", location)

            # ── 前端补充缺失槽位回传 ──
            elif event_type == "nav_slot_fill":
                filled = data.get("slots", {})
                pending = _pending_nav.get(session_id)
                if pending and pending.get("stage") == "slot_fill":
                    slots = pending["slots"]
                    # 合并用户补充的槽位
                    for key in ("origin", "destination", "travel_mode", "poi_type"):
                        val = filled.get(key, "")
                        if val:
                            slots[key] = val

                    # 重新检查是否还有缺失
                    intent_type = pending.get("intent_type", "")
                    still_missing = _get_missing_slots(slots, intent_type)

                    if still_missing:
                        pending["missing_slots"] = still_missing
                        await websocket.send_json({
                            "type": "nav_missing_slots",
                            "missing": still_missing,
                            "current_slots": {
                                "origin": slots.get("origin", ""),
                                "destination": slots.get("destination", ""),
                                "travel_mode": slots.get("travel_mode", ""),
                            },
                        })
                    else:
                        # 槽位已齐全，清除 slot_fill 状态，直接进 Stage 2
                        _pending_nav.pop(session_id, None)
                        logger.info(
                            "[NAV] 槽位补充完毕: %s, 直接启动 Stage 2",
                            slots,
                        )
                        asyncio.create_task(
                            _run_stage2_with_slots(
                                slots,
                                pending.get("intent_type", "basic_navigation"),
                                websocket,
                                agent,
                                session_id,
                            ),
                        )

            # ── 前端 POI 候选选择回传 ──
            elif event_type in ("nav_poi_select", "user_select_poi"):
                selected_poi = data.get("poi", {})
                if not isinstance(selected_poi, dict):
                    selected_poi = {}

                selected_name = selected_poi.get("name", "")
                selected_location = selected_poi.get("location", "")
                group = selected_poi.get("selection_group", "")

                pending = _pending_nav.get(session_id)
                if pending and pending.get("stage") == "slot_fill":
                    # 正在等待槽位补充，忽略 POI 选择事件
                    logger.info("[NAV] 忽略 POI 选择：当前处于槽位补充阶段")
                elif pending and selected_location:
                    resolved = {
                        "name": selected_name,
                        "location": selected_location,
                        "cityname": selected_poi.get("cityname", ""),
                    }

                    if group == "origin":
                        pending["origin_resolved"] = resolved
                    elif group == "destination":
                        pending["destination_resolved"] = resolved
                    else:
                        # 无分组信息，按缺失顺序填充
                        if (
                            not pending["origin_resolved"]
                            and pending["has_origin_candidates"]
                        ):
                            pending["origin_resolved"] = resolved
                        elif (
                            not pending["destination_resolved"]
                            and pending["has_destination_candidates"]
                        ):
                            pending["destination_resolved"] = resolved

                    origin_done = (
                        pending["origin_resolved"] is not None
                        or not pending["has_origin_candidates"]
                    )
                    dest_done = (
                        pending["destination_resolved"] is not None
                        or not pending["has_destination_candidates"]
                    )

                    if origin_done and dest_done:
                        logger.info(
                            "[NAV] 全部候选已选择完毕，开始规划路线",
                        )
                        asyncio.create_task(
                            _finalize_poi_selection(
                                session_id, websocket, agent,
                            ),
                        )
                    else:
                        remaining = (
                            "终点" if not dest_done else "起点"
                        )
                        await websocket.send_json({
                            "type": "nav_status_update",
                            "status": "waiting_selection",
                            "message": (
                                f"已选择{selected_name}，"
                                f"请继续选择{remaining}候选地点"
                            ),
                        })
                else:
                    # 无挂起状态或无坐标，回退到旧逻辑
                    if not selected_name:
                        selected_name = str(data.get("index", ""))
                    select_text = f"我选择地点：{selected_name}"
                    asyncio.create_task(
                        route_text_by_flowchart(
                            select_text,
                            websocket,
                            agent,
                            session_id,
                        ),
                    )

            # ── 会话结束 ──
            elif event_type == "client_session_end":
                if agent:
                    await agent.stop()
                    agent = None
                _pending_nav.pop(session_id, None)
                _session_current_location.pop(session_id, None)
                from tools.video_tools import reset_visual_state
                reset_visual_state()

            # ── 其它事件透传给 RealtimeAgent ──
            else:
                if agent:
                    client_event = ClientEvents.from_json(data)
                    await agent.handle_input(client_event)

    except Exception as e:
        print(f"[ERROR] WebSocket error: {e}")
        traceback.print_exc()
        raise
    finally:
        if agent:
            try:
                await agent.stop()
            except Exception:
                pass
        _pending_nav.pop(session_id, None)
        _session_current_location.pop(session_id, None)
        from tools.video_tools import reset_visual_state
        reset_visual_state()


if __name__ == "__main__":
    from config.settings import AMAP_API_KEY as _amap_key

    _dk = os.getenv("DASHSCOPE_API_KEY", "")
    _wk = os.getenv("AMAP_WEB_KEY", "")
    _ws = os.getenv("AMAP_WEB_SECRET", "")
    print(
        f"[BOOT] DASHSCOPE_API_KEY: "
        f"{'已设置 (' + _dk[:8] + '...)' if _dk else '⚠ 未设置!'}",
    )
    print(
        f"[BOOT] AMAP_API_KEY:      "
        f"{'已设置 (' + _amap_key[:8] + '...)' if _amap_key else '⚠ 未设置!'}",
    )
    print(
        f"[BOOT] AMAP_WEB_KEY:      "
        f"{'已设置 (' + _wk[:8] + '...)' if _wk else '⚠ 未设置!'}",
    )
    print(
        f"[BOOT] AMAP_WEB_SECRET:   "
        f"{'已设置 (' + _ws[:8] + '...)' if _ws else '⚠ 未设置!'}",
    )

    uvicorn.run(
        "run_server:app",
        host="localhost",
        port=8000,
        reload=True,
        log_level="info",
    )
