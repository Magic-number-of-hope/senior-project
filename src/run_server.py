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
from agentscope.realtime import (
    DashScopeRealtimeModel,
    GeminiRealtimeModel,
    OpenAIRealtimeModel,
    ClientEvents,
    ServerEvents,
)
from agentscope.tool import Toolkit

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


# ── 导航关键词检测 ──
_NAV_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in NAV_TRIGGER_KEYWORDS),
)

# ── 挂起的 POI 选择状态（session_id → 选择上下文）──
_pending_nav: dict = {}

# ── 会话导航上下文记忆（session_id → 上一次完整 slots）──
_nav_context: dict = {}


def detect_nav_intent(text: str) -> bool:
    """检测文本中是否包含导航意图关键词"""
    if not text or len(text.strip()) < 2:
        return False
    return bool(_NAV_PATTERN.search(text))


def _build_nav_broadcast_text(nav_data: Optional[dict], user_text: str) -> str:
    """将导航结果转为精简口语化文本，供 RealtimeAgent 语音播报。"""
    if not nav_data or not isinstance(nav_data, dict):
        return f"用户问了：{user_text}，但未能获取导航结果，请告知用户稍后重试。"

    nav_result = nav_data.get("navigation_result")
    slots = nav_data.get("slots", {})
    origin = slots.get("origin", "出发地")
    dest = slots.get("destination", "目的地")

    if not nav_result or not isinstance(nav_result, dict):
        return (
            f"用户想从{origin}到{dest}，但导航校验未返回有效结果，"
            "请告诉用户稍后重试。"
        )

    status = nav_result.get("status", "")
    if status == "need_selection":
        return (
            f"用户想从{origin}到{dest}，地点存在歧义，"
            "请引导用户从候选地点中选择。"
        )

    if status not in ("ok", "success"):
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


def _normalize_need_selection(nav_result: dict) -> dict:
    """统一归一化 need_selection 返回格式。

    导航智能体可能返回多种结构，全部转为标准格式：
      {
        "status": "need_selection",
        "origin_candidates": [...],
        "destination_candidates": [...],
        "candidates": [...]   # merged with selection_group tag
      }
    """
    origin_cands = nav_result.get("origin_candidates", [])
    dest_cands = nav_result.get("destination_candidates", [])
    raw_candidates = nav_result.get(
        "candidates", nav_result.get("poi_candidates", []),
    )

    if not origin_cands and not dest_cands and isinstance(raw_candidates, list):
        # 格式 A: candidates=[{origin_candidates:[], destination_candidates:[]}]
        if (
            len(raw_candidates) == 1
            and isinstance(raw_candidates[0], dict)
            and (
                "origin_candidates" in raw_candidates[0]
                or "destination_candidates" in raw_candidates[0]
            )
        ):
            wrapper = raw_candidates[0]
            origin_cands = wrapper.get("origin_candidates", [])
            dest_cands = wrapper.get("destination_candidates", [])

        # 格式 B: 笛卡尔积 candidates=[{origin:{...}, destination:{...}}, ...]
        elif (
            len(raw_candidates) > 0
            and isinstance(raw_candidates[0], dict)
            and "origin" in raw_candidates[0]
            and "destination" in raw_candidates[0]
        ):
            seen_origins = {}
            seen_dests = {}
            for item in raw_candidates:
                o = item.get("origin", {})
                d = item.get("destination", {})
                o_key = o.get("location", o.get("name", ""))
                d_key = d.get("location", d.get("name", ""))
                if o_key and o_key not in seen_origins:
                    seen_origins[o_key] = dict(o)
                if d_key and d_key not in seen_dests:
                    seen_dests[d_key] = dict(d)
            origin_cands = list(seen_origins.values())[:5]
            dest_cands = list(seen_dests.values())[:5]

        # 格式 C: 扁平候选列表（单侧歧义）
        elif len(raw_candidates) > 0 and isinstance(raw_candidates[0], dict):
            if "name" in raw_candidates[0]:
                origin_cands = raw_candidates[:5]

    # 构建带 selection_group 标签的 merged 列表
    merged = []
    for c in origin_cands[:5]:
        item = dict(c)
        item["selection_group"] = "origin"
        merged.append(item)
    for c in dest_cands[:5]:
        item = dict(c)
        item["selection_group"] = "destination"
        merged.append(item)

    nav_result["origin_candidates"] = origin_cands[:5]
    nav_result["destination_candidates"] = dest_cands[:5]
    nav_result["candidates"] = merged
    return nav_result


async def _ensure_map_fields(nav_result: dict, slots: dict) -> dict:
    """确保路线结果中包含前端地图所需的 origin_location / destination_location / polyline。

    LLM 不输出 polyline（太长会导致生成极慢），此函数直接调 API 获取。
    """
    # 回填坐标
    if not nav_result.get("origin_location") and slots.get("origin_location"):
        nav_result["origin_location"] = slots["origin_location"]
    if not nav_result.get("destination_location") and slots.get("destination_location"):
        nav_result["destination_location"] = slots["destination_location"]

    # 始终通过 API 获取 polyline（LLM 不再输出此字段）
    origin_loc = nav_result.get("origin_location", "")
    dest_loc = nav_result.get("destination_location", "")
    polyline = nav_result.get("polyline", "")
    if origin_loc and dest_loc and (not polyline or len(polyline) < 50):
        logger.info("[NAV] 通过 API 获取 polyline ...")
        try:
            from tools.amap_tools import route_planning
            mode = slots.get("travel_mode", "driving")
            resp = await route_planning(origin_loc, dest_loc, mode=mode)
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

        if nav_data:
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
            _required_missing = []
            if not slots.get("origin"):
                _required_missing.append("origin")
            if not slots.get("destination"):
                _required_missing.append("destination")
            if not slots.get("travel_mode"):
                _required_missing.append("travel_mode")
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
            if nav_result is not None:
                nav_data["navigation_result"] = nav_result
            else:
                nav_data["navigation_result"] = nav_result_text

            if isinstance(nav_result, dict):
                status = nav_result.get("status", "")
                if status in ("ok", "success"):
                    await _ensure_map_fields(nav_result, nav_data.get("slots", {}))
                    await websocket.send_json({
                        "type": "nav_route_result",
                        "route_result": nav_result,
                    })
                elif status == "need_selection":
                    _normalize_need_selection(nav_result)

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
        else:
            await websocket.send_json({
                "type": "nav_status_update",
                "status": "done",
                "message": result_text[:200] if result_text else "分析完成",
            })
            # JSON 提取失败时，用关键词做保底判断
            return detect_nav_intent(user_text), None, result_text

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
    if not agent or not text.strip():
        return
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


async def _finalize_poi_selection(
    session_id: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
) -> None:
    """用户完成所有 POI 候选选择后，将已解析坐标交给导航智能体规划路线。"""
    pending = _pending_nav.pop(session_id, None)
    if not pending:
        return

    from tools.analysis_tools import _async_run_navigation
    from tools.video_tools import get_current_visual_state

    slots = pending.get("slots", {})
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

    try:
        await websocket.send_json({
            "type": "nav_status_update",
            "status": "processing",
            "message": "正在规划路线...",
        })

        navigation_request = {
            "intent_type": "basic_navigation",
            "slots": slots,
        }
        nav_result_text = await _async_run_navigation(navigation_request)
        nav_result = _parse_nav_result(nav_result_text)

        if isinstance(nav_result, dict):
            status = nav_result.get("status", "")

            if status == "need_selection":
                # 理论上不应该再出现歧义，但保底处理
                _normalize_need_selection(nav_result)
                origin_cands = nav_result.get("origin_candidates", [])
                dest_cands = nav_result.get("destination_candidates", [])
                await websocket.send_json({
                    "type": "nav_poi_candidates",
                    "candidates": nav_result["candidates"],
                    "origin_candidates": origin_cands,
                    "destination_candidates": dest_cands,
                })
                _pending_nav[session_id] = {
                    "slots": slots,
                    "origin_resolved": None,
                    "destination_resolved": None,
                    "has_origin_candidates": len(origin_cands) > 0,
                    "has_destination_candidates": len(dest_cands) > 0,
                }
                return

            if status in ("ok", "success"):
                # 补充名称信息
                if origin_info and "origin_name" not in nav_result:
                    nav_result["origin_name"] = origin_info["name"]
                if dest_info and "destination_name" not in nav_result:
                    nav_result["destination_name"] = dest_info["name"]
                await _ensure_map_fields(nav_result, slots)
                await websocket.send_json({
                    "type": "nav_route_result",
                    "route_result": nav_result,
                })

        await websocket.send_json({
            "type": "nav_status_update",
            "status": "done",
            "message": "导航分析完成",
        })

        # 播报路线
        _nav_context[session_id] = dict(slots)
        nav_data = {"navigation_result": nav_result, "slots": slots}
        visual_state = await get_current_visual_state()
        summary = _build_nav_broadcast_text(nav_data, "")
        if visual_state:
            summary += f"\n当前视觉环境：{visual_state}"
        await _inject_text_to_agent(agent, session_id, summary)

    except Exception as e:
        logger.error("[NAV] POI 选择后路线规划异常: %s", e)
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "nav_error",
                "message": f"路线规划失败: {str(e)}",
            })
        except Exception:
            pass


async def _run_stage2_with_slots(
    slots: dict,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
) -> None:
    """槽位齐全后直接调用 Stage 2（导航校验智能体），跳过 Stage 1。"""
    from tools.analysis_tools import _async_run_navigation
    from tools.video_tools import get_current_visual_state

    try:
        await websocket.send_json({
            "type": "nav_status_update",
            "status": "processing",
            "message": "正在查询路线...",
        })

        navigation_request = {
            "intent_type": "basic_navigation",
            "slots": slots,
        }
        nav_result_text = await _async_run_navigation(navigation_request)
        nav_result = _parse_nav_result(nav_result_text)

        if isinstance(nav_result, dict):
            status = nav_result.get("status", "")

            if status == "need_selection":
                _normalize_need_selection(nav_result)
                origin_cands = nav_result.get("origin_candidates", [])
                dest_cands = nav_result.get("destination_candidates", [])

                await websocket.send_json({
                    "type": "nav_poi_candidates",
                    "candidates": nav_result["candidates"],
                    "origin_candidates": origin_cands,
                    "destination_candidates": dest_cands,
                })

                _pending_nav[session_id] = {
                    "slots": slots,
                    "origin_resolved": None,
                    "destination_resolved": None,
                    "has_origin_candidates": len(origin_cands) > 0,
                    "has_destination_candidates": len(dest_cands) > 0,
                }
                logger.info(
                    "[NAV] 等待用户选择候选地点 (origin=%d, dest=%d)",
                    len(origin_cands), len(dest_cands),
                )
                return

            if status in ("ok", "success"):
                await _ensure_map_fields(nav_result, slots)
                await websocket.send_json({
                    "type": "nav_route_result",
                    "route_result": nav_result,
                })

        await websocket.send_json({
            "type": "nav_status_update",
            "status": "done",
            "message": "导航分析完成",
        })

        # 播报路线
        _nav_context[session_id] = dict(slots)
        nav_data = {"navigation_result": nav_result, "slots": slots}
        visual_state = await get_current_visual_state()
        summary = _build_nav_broadcast_text(nav_data, "")
        if visual_state:
            summary += f"\n当前视觉环境：{visual_state}"
        await _inject_text_to_agent(agent, session_id, summary)

    except Exception as e:
        logger.error("[NAV] Stage 2 执行异常: %s", e)
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "nav_error",
                "message": f"导航查询失败: {str(e)}",
            })
        except Exception:
            pass


async def route_text_by_flowchart(
    user_text: str,
    websocket: WebSocket,
    agent: Optional[RealtimeAgent],
    session_id: str,
) -> None:
    """按流程图执行文本分流：意图判断 → 导航/闲聊 → RealtimeAgent。"""
    is_navigation, nav_data, raw_result = await run_nav_pipeline(
        user_text, websocket,
    )

    # 查询当前视觉状态并融合到最终播报输入
    from tools.video_tools import get_current_visual_state
    visual_state = await get_current_visual_state()

    if is_navigation and isinstance(nav_data, dict):
        # ── 必要槽位缺失检测：起点、终点、出行方式 ──
        slots = nav_data.get("slots", {})

        # 从会话上下文补全缺失槽位（如用户说"坐公交怎么走"，沿用上次起终点）
        prev = _nav_context.get(session_id, {})
        if prev:
            for key in ("origin", "destination", "travel_mode"):
                if not slots.get(key) and prev.get(key):
                    slots[key] = prev[key]
                    logger.info("[NAV] 从上下文补全 %s=%s", key, prev[key])
            # 同步补全已解析坐标
            for loc_key in ("origin_location", "destination_location"):
                if not slots.get(loc_key) and prev.get(loc_key):
                    slots[loc_key] = prev[loc_key]

        missing_slots = []
        if not slots.get("origin"):
            missing_slots.append("origin")
        if not slots.get("destination"):
            missing_slots.append("destination")
        if not slots.get("travel_mode"):
            missing_slots.append("travel_mode")

        # 保存当前槽位到上下文（即使不完整也更新已有部分）
        _nav_context[session_id] = dict(slots)

        if missing_slots:
            _pending_nav[session_id] = {
                "slots": dict(slots),
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

            _normalize_need_selection(nav_result)
            origin_cands = nav_result.get("origin_candidates", [])
            dest_cands = nav_result.get("destination_candidates", [])

            _pending_nav[session_id] = {
                "slots": slots,
                "origin_resolved": None,
                "destination_resolved": None,
                "has_origin_candidates": len(origin_cands) > 0,
                "has_destination_candidates": len(dest_cands) > 0,
            }
            logger.info(
                "[NAV] 等待用户选择候选地点 (origin=%d, dest=%d)",
                len(origin_cands), len(dest_cands),
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


def _parse_nav_result(text: str) -> Optional[dict]:
    """从智能体回复中提取 JSON 结构"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    json_match = re.search(r"```json\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return None


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

                if model_provider == "dashscope":
                    model = DashScopeRealtimeModel(
                        model_name=REALTIME_MODEL_NAME,
                        api_key=(
                            DASHSCOPE_API_KEY
                            or os.getenv("DASHSCOPE_API_KEY")
                        ),
                    )
                    toolkit = Toolkit()
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
                    toolkit = Toolkit()

                elif model_provider == "openai":
                    model = OpenAIRealtimeModel(
                        model_name="gpt-4o-realtime-preview",
                        api_key=os.getenv("OPENAI_API_KEY"),
                    )
                    toolkit = Toolkit()

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

            # ── 音频提交（Whisper 转写 + 意图分析）──
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

                        # 按流程图做意图分流与最终播报
                        asyncio.create_task(
                            route_text_by_flowchart(
                                transcript,
                                ws,
                                agent,
                                session_id,
                            ),
                        )

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

            # ── 前端补充缺失槽位回传 ──
            elif event_type == "nav_slot_fill":
                filled = data.get("slots", {})
                pending = _pending_nav.get(session_id)
                if pending and pending.get("stage") == "slot_fill":
                    slots = pending["slots"]
                    # 合并用户补充的槽位
                    for key in ("origin", "destination", "travel_mode"):
                        val = filled.get(key, "")
                        if val:
                            slots[key] = val

                    # 重新检查是否还有缺失
                    still_missing = []
                    if not slots.get("origin"):
                        still_missing.append("origin")
                    if not slots.get("destination"):
                        still_missing.append("destination")
                    if not slots.get("travel_mode"):
                        still_missing.append("travel_mode")

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
                                slots, websocket, agent, session_id,
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
