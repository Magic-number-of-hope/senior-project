# -*- coding: utf-8 -*-
"""WebSocket 主入口 — 从原 run_server.py 提取的 WS 处理逻辑。"""
import asyncio
import base64
import os
import re
import traceback

from agentscope import logger
from agentscope.agent import RealtimeAgent
from agentscope.realtime import (
    ClientEvents,
    DashScopeRealtimeModel,
    GeminiRealtimeModel,
    OpenAIRealtimeModel,
    ServerEvents,
)
from agentscope.tool import Toolkit
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config.settings import (
    DASHSCOPE_API_KEY,
    NAV_TRIGGER_KEYWORDS,
    REALTIME_MODEL_NAME,
)
from app.prompts.interaction_prompt import INTERACTION_PROMPT
from app.services.nav_pipeline import (
    broadcast_nav_summary,
    finalize_poi_selection,
    inject_text_to_agent,
    route_text_by_flowchart,
    run_stage2_with_slots,
)
from app.services.nav_utils import get_missing_slots
from app.services.session_state import (
    cleanup_session,
    pending_nav,
    pending_nav_route_broadcast,
    session_current_location,
)

router = APIRouter()

# ── 导航关键词检测 ──
_NAV_PATTERN = re.compile("|".join(re.escape(kw) for kw in NAV_TRIGGER_KEYWORDS))


def detect_nav_intent(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    return bool(_NAV_PATTERN.search(text))


# ═══════════════════════════════════════════
#  Whisper ASR
# ═══════════════════════════════════════════

async def whisper_transcribe(pcm_bytes: bytes):
    from app.tools.whisper_tools import transcribe_pcm16
    return await asyncio.to_thread(transcribe_pcm16, pcm_bytes)


# ═══════════════════════════════════════════
#  视频帧处理
# ═══════════════════════════════════════════

async def handle_video_frame(jpeg_base64: str, websocket: WebSocket, agent, session_id: str):
    try:
        from app.tools.video_tools import process_video_frame
        result = await process_video_frame(jpeg_base64)
        if result:
            await websocket.send_json({"type": "visual_analysis_result", "description": result})
            await inject_text_to_agent(agent, session_id, f"[视觉信息] {result}")
    except Exception as e:
        logger.error("[VIDEO] 视频帧处理失败: %s", e)


# ═══════════════════════════════════════════
#  事件转发（Agent -> 前端）
# ═══════════════════════════════════════════

async def frontend_receive(websocket: WebSocket, frontend_queue: asyncio.Queue) -> None:
    transcript_buffer: dict[str, str] = {}
    try:
        while True:
            msg = await frontend_queue.get()
            payload = msg.model_dump()
            event_type = payload.get("type")

            if event_type == "agent_response_audio_transcript_delta":
                key = f"{payload.get('response_id', '')}:{payload.get('item_id', '')}"
                transcript_buffer[key] = transcript_buffer.get(key, "") + payload.get("delta", "")
            elif event_type == "agent_response_audio_transcript_done":
                key = f"{payload.get('response_id', '')}:{payload.get('item_id', '')}"
                text = transcript_buffer.pop(key, "")
                logger.info("[AGENT-REPLY] %s", text[:200])

            await websocket.send_json(payload)
    except Exception as e:
        logger.error("[ERROR] frontend_receive error: %s", e)


# ═══════════════════════════════════════════
#  WebSocket 端点
# ═══════════════════════════════════════════

@router.websocket("/ws/{user_id}/{session_id}")
async def single_agent_endpoint(websocket: WebSocket, user_id: str, session_id: str) -> None:
    agent = None
    audio_buffer = bytearray()

    try:
        await websocket.accept()
        logger.info("Connected: user_id=%s, session_id=%s", user_id, session_id)

        frontend_queue: asyncio.Queue = asyncio.Queue()
        asyncio.create_task(frontend_receive(websocket, frontend_queue))

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect as e:
                logger.info("WebSocket disconnected: user_id=%s, session_id=%s, code=%s", user_id, session_id, getattr(e, "code", "unknown"))
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
                        api_key=DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY"),
                    )
                elif model_provider == "gemini":
                    model = GeminiRealtimeModel(
                        model_name="gemini-2.5-flash-native-audio-preview-09-2025",
                        api_key=os.getenv("GEMINI_API_KEY"),
                    )
                elif model_provider == "openai":
                    model = OpenAIRealtimeModel(
                        model_name="gpt-4o-realtime-preview",
                        api_key=os.getenv("OPENAI_API_KEY"),
                    )
                else:
                    raise ValueError(f"Unsupported model provider: {model_provider}")

                agent = RealtimeAgent(name=agent_name, sys_prompt=sys_prompt, model=model, toolkit=toolkit)
                await agent.start(frontend_queue)
                await websocket.send_json(ServerEvents.ServerSessionCreatedEvent(session_id=session_id).model_dump())
                logger.info("Session created: %s", session_id)

            # ── 音频帧追加 ──
            elif event_type == "client_audio_append":
                audio_b64 = data.get("audio", "")
                if audio_b64:
                    audio_buffer.extend(base64.b64decode(audio_b64))

            # ── 音频提交 → Whisper ──
            elif event_type == "client_audio_commit":
                if len(audio_buffer) > 3200:
                    pcm_bytes = bytes(audio_buffer)
                    audio_buffer.clear()

                    async def _whisper_and_analyze(pcm, ws):
                        transcript = await whisper_transcribe(pcm)
                        if not transcript:
                            return
                        await ws.send_json({"type": "whisper_transcription", "transcript": transcript})

                    asyncio.create_task(_whisper_and_analyze(pcm_bytes, websocket))
                else:
                    audio_buffer.clear()

            # ── 文本输入 ──
            elif event_type == "client_text_append":
                client_event = ClientEvents.from_json(data)
                user_text = client_event.text
                logger.info("[TEXT-INPUT] %s", user_text[:100])
                asyncio.create_task(
                    route_text_by_flowchart(user_text, websocket, agent, session_id, detect_nav_intent)
                )

            # ── 视频帧 ──
            elif event_type == "client_image_append":
                image_b64 = data.get("image", "")
                if image_b64:
                    asyncio.create_task(handle_video_frame(image_b64, websocket, agent, session_id))

            # ── 当前位置上报 ──
            elif event_type == "client_location_update":
                location = str(data.get("location", "")).strip()
                name = str(data.get("name", "")).strip() or "当前位置"
                if location and "," in location:
                    try:
                        lng_s, lat_s = location.split(",", 1)
                        float(lng_s.strip())
                        float(lat_s.strip())
                        session_current_location[session_id] = {
                            "name": name, "location": location,
                            "source": str(data.get("source", "browser")),
                            "accuracy": data.get("accuracy"),
                            "timestamp": data.get("timestamp"),
                        }
                    except Exception:
                        logger.warning("[LOCATION] 非法坐标，忽略: %s", location)

            # ── 槽位补充回传 ──
            elif event_type == "nav_slot_fill":
                filled = data.get("slots", {})
                pending = pending_nav.get(session_id)
                if pending and pending.get("stage") == "slot_fill":
                    slots = pending["slots"]
                    for key in ("origin", "destination", "travel_mode", "poi_type"):
                        val = filled.get(key, "")
                        if val:
                            slots[key] = val
                    intent_type = pending.get("intent_type", "")
                    still_missing = get_missing_slots(slots, intent_type)
                    if still_missing:
                        pending["missing_slots"] = still_missing
                        await websocket.send_json({
                            "type": "nav_missing_slots",
                            "missing": still_missing,
                            "current_slots": {"origin": slots.get("origin", ""), "destination": slots.get("destination", ""), "travel_mode": slots.get("travel_mode", "")},
                        })
                    else:
                        pending_nav.pop(session_id, None)
                        asyncio.create_task(run_stage2_with_slots(slots, intent_type, websocket, agent, session_id))

            # ── POI 候选选择 ──
            elif event_type in ("nav_poi_select", "user_select_poi"):
                selected_poi = data.get("poi", {})
                if not isinstance(selected_poi, dict):
                    selected_poi = {}
                selected_name = selected_poi.get("name", "")
                selected_location = selected_poi.get("location", "")
                group = selected_poi.get("selection_group", "")
                pending = pending_nav.get(session_id)

                if pending and pending.get("stage") == "slot_fill":
                    pass  # 正在等槽位，忽略
                elif pending and selected_location:
                    resolved = {"name": selected_name, "location": selected_location, "cityname": selected_poi.get("cityname", "")}
                    if group == "origin":
                        pending["origin_resolved"] = resolved
                    elif group == "destination":
                        pending["destination_resolved"] = resolved
                    else:
                        if not pending["origin_resolved"] and pending["has_origin_candidates"]:
                            pending["origin_resolved"] = resolved
                        elif not pending["destination_resolved"] and pending["has_destination_candidates"]:
                            pending["destination_resolved"] = resolved

                    origin_done = pending["origin_resolved"] is not None or not pending["has_origin_candidates"]
                    dest_done = pending["destination_resolved"] is not None or not pending["has_destination_candidates"]
                    if origin_done and dest_done:
                        asyncio.create_task(finalize_poi_selection(session_id, websocket, agent))
                    else:
                        remaining = "终点" if not dest_done else "起点"
                        await websocket.send_json({"type": "nav_status_update", "status": "waiting_selection", "message": f"已选择{selected_name}，请继续选择{remaining}候选地点"})
                else:
                    if not selected_name:
                        selected_name = str(data.get("index", ""))
                    asyncio.create_task(route_text_by_flowchart(f"我选择地点：{selected_name}", websocket, agent, session_id, detect_nav_intent))

            # ── 前端路线回传 ──
            elif event_type == "nav_js_route_result":
                route_result = data.get("route_result", {})
                if not isinstance(route_result, dict):
                    route_result = {}
                pending_broadcast = pending_nav_route_broadcast.pop(session_id, None)
                slots = (pending_broadcast or {}).get("slots", {})
                intent_type = (pending_broadcast or {}).get("intent_type", "")
                for rk, sk in [("origin_name", "origin"), ("destination_name", "destination"), ("route_mode", "travel_mode"), ("waypoints", "waypoints")]:
                    if route_result.get(rk) and not slots.get(sk):
                        slots[sk] = route_result[rk]
                await broadcast_nav_summary(agent, session_id, route_result, slots, intent_type)

            # ── 会话结束 ──
            elif event_type == "client_session_end":
                if agent:
                    await agent.stop()
                    agent = None
                cleanup_session(session_id)
                from app.tools.video_tools import reset_visual_state
                reset_visual_state()

            # ── 其它事件透传 ──
            else:
                if agent:
                    client_event = ClientEvents.from_json(data)
                    await agent.handle_input(client_event)

    except Exception as e:
        logger.error("[ERROR] WebSocket error: %s", e)
        traceback.print_exc()
        raise
    finally:
        if agent:
            try:
                await agent.stop()
            except Exception:
                pass
        cleanup_session(session_id)
        from app.tools.video_tools import reset_visual_state
        reset_visual_state()
