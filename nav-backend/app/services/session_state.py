# -*- coding: utf-8 -*-
"""会话级状态管理 — 锁、位置缓存、导航上下文记忆、挂起状态。"""
import asyncio
import json

from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

# ── 挂起的 POI 选择状态 (session_id -> dict) ──
pending_nav: dict = {}

# ── 路线播报等待前端回传 (session_id -> dict) ──
pending_nav_route_broadcast: dict = {}

# ── 会话导航上下文记忆 ──
_nav_context_memory = InMemoryMemory()
_NAV_CONTEXT_MARK = "nav_context"

# ── 会话级锁 ──
_session_route_locks: dict = {}
_session_agent_input_locks: dict = {}

# ── 会话级当前位置缓存 ──
session_current_location: dict = {}


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
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


async def save_nav_context(session_id: str, slots: dict) -> None:
    msgs = await _nav_context_memory.get_memory(mark=session_id, prepend_summary=False)
    if msgs:
        await _nav_context_memory.delete([m.id for m in msgs])
    await _nav_context_memory.add(
        Msg(name=session_id, role="system", content=json.dumps(slots, ensure_ascii=False), metadata={"type": _NAV_CONTEXT_MARK}),
        marks=[_NAV_CONTEXT_MARK, session_id],
    )


async def build_nav_memory_hint_for_llm(session_id: str) -> str:
    payload = {}
    prev = await load_nav_context(session_id)
    if isinstance(prev, dict) and prev:
        allowed_keys = ("origin", "origin_location", "destination", "destination_location", "travel_mode", "waypoints", "waypoint_locations", "poi_type", "poi_constraint")
        slots = {k: prev[k] for k in allowed_keys if prev.get(k) not in (None, "", [], {})}
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


def cleanup_session(session_id: str) -> None:
    pending_nav.pop(session_id, None)
    pending_nav_route_broadcast.pop(session_id, None)
    session_current_location.pop(session_id, None)
    _session_route_locks.pop(session_id, None)
    _session_agent_input_locks.pop(session_id, None)
