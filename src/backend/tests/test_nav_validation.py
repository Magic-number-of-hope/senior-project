# -*- coding: utf-8 -*-
"""导航功能逐步验证脚本
验证项目：驾车（含途径点）、骑行、步行、公交的后端路由逻辑
"""
import sys
import asyncio
from pathlib import Path

# 确保 backend 目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.nav_routing import _normalize_mode, _ensure_map_fields, _try_direct_route_planning
from services.nav_utils import _get_missing_slots, _parse_nav_result
from tools.analysis_tools import _validate_navigation_result_strict
from run_server import (
    _normalize_travel_mode_value,
    _normalize_waypoints_by_mode,
    _should_preserve_previous_route_points,
)
from models.intent_schema import TravelMode

# ──────────────────────────────────────────────
# STEP 1：出行方式别名归一化
# ──────────────────────────────────────────────
def test_step1_mode_normalize():
    print("\n" + "="*60)
    print("STEP 1: 出行方式别名归一化")
    print("="*60)
    cases = [
        ("driving",   "driving"),
        ("walking",   "walking"),
        ("transit",   "transit"),
        ("bicycling", "bicycling"),
        (TravelMode.DRIVING,   "driving"),
        (TravelMode.WALKING,   "walking"),
        (TravelMode.BICYCLING, "bicycling"),
        ("riding",    "bicycling"),
        ("bike",      "bicycling"),
        ("bicycle",   "bicycling"),
        ("DRIVING",   "driving"),
        ("",          ""),
    ]
    all_pass = True
    for raw, expected in cases:
        got_routing = _normalize_mode(raw)
        got_server  = _normalize_travel_mode_value(raw)
        ok_r = (got_routing == expected)
        ok_s = (got_server  == expected)
        status = "✅" if (ok_r and ok_s) else "❌"
        if not (ok_r and ok_s):
            all_pass = False
        print(f"  {status} '{raw}' → routing={got_routing!r}  server={got_server!r}  (expected={expected!r})")
    return all_pass


# ──────────────────────────────────────────────
# STEP 2：途径点仅驾车保留，其余清除
# ──────────────────────────────────────────────
def test_step2_waypoint_mode_guard():
    print("\n" + "="*60)
    print("STEP 2: 途径点模式守卫（仅驾车保留途径点）")
    print("="*60)
    all_pass = True

    # 驾车 → 保留途径点
    slots_driving = {
        "travel_mode": TravelMode.DRIVING,
        "waypoints": ["武汉大学", "光谷广场"],
        "waypoint_locations": ["114.366369,30.540562", "114.410012,30.499524"],
        "sequence": ["武汉站", "武汉大学", "光谷广场"],
    }
    result = _normalize_waypoints_by_mode(dict(slots_driving))
    ok = bool(
        result.get("waypoints")
        and result.get("waypoint_locations")
        and result.get("sequence")
    )
    status = "✅" if ok else "❌"
    if not ok: all_pass = False
    print(
        f"  {status} 驾车模式保留途径点: "
        f"waypoints={result.get('waypoints')} sequence={result.get('sequence')}"
    )

    # 步行 → 清除途径点
    for mode in ["walking", "bicycling", "transit"]:
        slots = {
            "travel_mode": mode,
            "waypoints": ["武汉大学"],
            "waypoint_locations": ["114.366369,30.540562"],
            "sequence": ["武汉站", "武汉大学", "光谷广场"],
        }
        result = _normalize_waypoints_by_mode(dict(slots))
        cleared = (
            not result.get("waypoints")
            and not result.get("waypoint_locations")
            and not result.get("sequence")
        )
        status = "✅" if cleared else "❌"
        if not cleared: all_pass = False
        print(
            f"  {status} {mode} 模式清除途径点: "
            f"waypoints={result.get('waypoints')} "
            f"locs={result.get('waypoint_locations')} "
            f"sequence={result.get('sequence')}"
        )

    return all_pass


# ──────────────────────────────────────────────
# STEP 3：缺失槽位检测
# ──────────────────────────────────────────────
def test_step3_missing_slots():
    print("\n" + "="*60)
    print("STEP 3: 缺失槽位检测")
    print("="*60)
    all_pass = True

    cases = [
        # (slots, intent_type, expected_missing_set)
        ({"origin": "武汉站", "destination": "光谷", "travel_mode": "driving"},
         "basic_navigation", set()),
        ({"origin": "武汉站", "destination": ""},
         "basic_navigation", {"destination", "travel_mode"}),
        ({"origin": "", "destination": "光谷", "travel_mode": "walking"},
         "basic_navigation", {"origin"}),
        ({"origin": "武汉站", "poi_type": "加油站"},
         "life_service", set()),
        ({"origin": "武汉站"},
         "life_service", {"poi_type"}),
    ]
    for slots, intent, expected in cases:
        missing = set(_get_missing_slots(slots, intent))
        ok = (missing == expected)
        status = "✅" if ok else "❌"
        if not ok: all_pass = False
        print(f"  {status} slots={slots} intent={intent}")
        print(f"       missing={missing}  expected={expected}")
    return all_pass


# ──────────────────────────────────────────────
# STEP 3B：持续对话模式切换
# ──────────────────────────────────────────────
def test_step3b_mode_change_continuity():
    print("\n" + "="*60)
    print("STEP 3B: 持续对话模式切换（改成公交）")
    print("="*60)

    prev_slots = {
        "origin": "武汉理工大学马房山校区东院",
        "origin_location": "114.353823,30.518657",
        "destination": "武汉站",
        "destination_location": "114.424338,30.606981",
        "travel_mode": "driving",
        "waypoints": ["国立武汉大学牌楼(旧)", "东湖生态旅游风景区梨园"],
        "waypoint_locations": ["114.366000,30.533000", "114.388000,30.553000"],
        "sequence": [
            "武汉理工大学马房山校区东院",
            "国立武汉大学牌楼(旧)",
            "东湖生态旅游风景区梨园",
            "武汉站",
        ],
    }
    current_slots = {"travel_mode": "transit"}

    should_preserve = _should_preserve_previous_route_points(
        "改成公交",
        current_slots,
        prev_slots,
    )
    ok_preserve = should_preserve is True
    print(f"  {'✅' if ok_preserve else '❌'} 识别为模式微调续聊: {should_preserve}")

    hydrated = dict(current_slots)
    if should_preserve:
        for key in (
            "origin",
            "origin_location",
            "destination",
            "destination_location",
            "waypoints",
            "waypoint_locations",
            "sequence",
        ):
            if prev_slots.get(key):
                hydrated[key] = prev_slots[key]

    normalized = _normalize_waypoints_by_mode(hydrated)
    ok_normalized = (
        normalized.get("origin") == prev_slots["origin"]
        and normalized.get("destination") == prev_slots["destination"]
        and normalized.get("travel_mode") == "transit"
        and not normalized.get("waypoints")
        and not normalized.get("waypoint_locations")
        and not normalized.get("sequence")
    )
    print(
        f"  {'✅' if ok_normalized else '❌'} 改成公交后保留起终点并清理多途经点字段: "
        f"{normalized}"
    )

    return ok_preserve and ok_normalized


# ──────────────────────────────────────────────
# STEP 4：_parse_nav_result 严格 JSON 解析
# ──────────────────────────────────────────────
def test_step4_parse_nav_result():
    print("\n" + "="*60)
    print("STEP 4: _parse_nav_result 严格 JSON 解析")
    print("="*60)
    all_pass = True

    # 合法输入
    valid = '{"status":"success","origin_name":"武汉站","destination_name":"光谷广场"}'
    try:
        r = _parse_nav_result(valid)
        ok = isinstance(r, dict) and r["status"] == "success"
        status = "✅" if ok else "❌"
        if not ok: all_pass = False
        print(f"  {status} 合法 JSON 解析: {r}")
    except Exception as e:
        print(f"  ❌ 合法 JSON 解析抛出异常: {e}")
        all_pass = False

    # 非法：带 Markdown 包裹
    invalid_md = "```json\n{\"status\":\"success\"}\n```"
    try:
        r = _parse_nav_result(invalid_md)
        print(f"  ❌ Markdown 包裹应抛出异常但未抛: {r}")
        all_pass = False
    except Exception:
        print("  ✅ Markdown 包裹正确抛出异常（strict模式）")

    # 非法：空字符串
    try:
        r = _parse_nav_result("")
        print(f"  ❌ 空字符串应抛出异常但未抛: {r}")
        all_pass = False
    except Exception:
        print("  ✅ 空字符串正确抛出异常")

    # 非法：返回数组
    try:
        r = _parse_nav_result('[{"status":"success"}]')
        print(f"  ❌ JSON 数组应抛出异常但未抛: {r}")
        all_pass = False
    except Exception:
        print("  ✅ JSON 数组正确抛出异常")

    return all_pass


def test_step4b_life_service_result_normalize():
    print("\n" + "="*60)
    print("STEP 4B: life_service 成功结果归一化为候选点")
    print("="*60)

    raw = '{"status":"success","origin_name":"武汉理工大学马房山校区东院","destination_name":null,"origin_location":"114.353823,30.518657","destination_location":null,"route_mode":"bicycling","waypoints":["萍姐炸串飞哥地摊牛骨火锅","菌相见·云南野生菌火锅(街道口店)"],"waypoint_locations":["114.353684,30.513633","114.352501,30.523793"]}'

    try:
        normalized = _validate_navigation_result_strict(raw)
        parsed = _parse_nav_result(normalized)
        ok = (
            parsed.get("status") == "need_selection"
            and parsed.get("origin_name") == "武汉理工大学马房山校区东院"
            and len(parsed.get("destination_candidates", [])) == 2
            and parsed.get("destination_candidates", [])[0].get("name") == "萍姐炸串飞哥地摊牛骨火锅"
        )
        print(f"  {'✅' if ok else '❌'} 归一化结果: {parsed}")
        return ok
    except Exception as e:
        print(f"  ❌ life_service 归一化抛出异常: {e}")
        return False


# ──────────────────────────────────────────────
# STEP 5：_ensure_map_fields 字段填充（异步）
# ──────────────────────────────────────────────
async def test_step5_ensure_map_fields():
    print("\n" + "="*60)
    print("STEP 5: _ensure_map_fields 字段填充与途径点模式守卫")
    print("="*60)
    all_pass = True

    # 驾车含途径点
    nav = {
        "status": "success",
        "origin_name": "武汉站",
        "destination_name": "光谷广场",
        "origin_location": "114.304569,30.593354",
        "destination_location": "114.410012,30.499524",
        "route_mode": "driving",
        "waypoints": ["武汉大学"],
        "waypoint_locations": ["114.366369,30.540562"],
    }
    slots = {}
    result = await _ensure_map_fields(nav, slots, fetch_polyline=False)
    ok = (
        result["route_mode"] == "driving"
        and result["waypoints"] == ["武汉大学"]
        and result["waypoint_locations"] == ["114.366369,30.540562"]
        and "polyline" not in result
        and "routes" not in result
    )
    status = "✅" if ok else "❌"
    if not ok: all_pass = False
    print(f"  {status} 驾车含途径点: mode={result['route_mode']} wps={result['waypoints']} locs={result['waypoint_locations']}")
    print(f"       polyline字段已清理={'polyline' not in result}  routes字段已清理={'routes' not in result}")

    # 骑行（riding别名） → waypoints 应清空
    nav2 = {
        "status": "success",
        "origin_location": "114.304569,30.593354",
        "destination_location": "114.410012,30.499524",
        "route_mode": "riding",
        "waypoints": ["武汉大学"],
        "waypoint_locations": ["114.366369,30.540562"],
    }
    result2 = await _ensure_map_fields(nav2, {}, fetch_polyline=False)
    ok2 = (
        result2["route_mode"] == "bicycling"
        and result2["waypoints"] == []
        and result2["waypoint_locations"] == []
    )
    status2 = "✅" if ok2 else "❌"
    if not ok2: all_pass = False
    print(f"  {status2} 骑行(riding别名)清除途径点: mode={result2['route_mode']} wps={result2['waypoints']}")

    # 步行
    nav3 = {
        "status": "success",
        "origin_location": "114.304569,30.593354",
        "destination_location": "114.410012,30.499524",
        "route_mode": "walking",
        "waypoints": ["武汉大学"],
        "waypoint_locations": ["114.366369,30.540562"],
    }
    result3 = await _ensure_map_fields(nav3, {}, fetch_polyline=False)
    ok3 = result3["route_mode"] == "walking" and result3["waypoints"] == []
    status3 = "✅" if ok3 else "❌"
    if not ok3: all_pass = False
    print(f"  {status3} 步行清除途径点: mode={result3['route_mode']} wps={result3['waypoints']}")

    # 公交
    nav4 = {
        "status": "success",
        "origin_location": "114.304569,30.593354",
        "destination_location": "114.410012,30.499524",
        "route_mode": "transit",
        "waypoints": ["武汉大学"],
        "waypoint_locations": ["114.366369,30.540562"],
    }
    result4 = await _ensure_map_fields(nav4, {}, fetch_polyline=False)
    ok4 = result4["route_mode"] == "transit" and result4["waypoints"] == []
    status4 = "✅" if ok4 else "❌"
    if not ok4: all_pass = False
    print(f"  {status4} 公交清除途径点: mode={result4['route_mode']} wps={result4['waypoints']}")

    # 驾车途径点上限16条
    nav5 = {
        "status": "success",
        "origin_location": "114.304569,30.593354",
        "destination_location": "114.410012,30.499524",
        "route_mode": "driving",
        "waypoints": [f"途经{i}" for i in range(20)],
        "waypoint_locations": [f"114.{300+i},30.5" for i in range(20)],
    }
    result5 = await _ensure_map_fields(nav5, {}, fetch_polyline=False)
    ok5 = len(result5["waypoints"]) == 16 and len(result5["waypoint_locations"]) == 16
    status5 = "✅" if ok5 else "❌"
    if not ok5: all_pass = False
    print(f"  {status5} 驾车途径点上限16: wps_count={len(result5['waypoints'])} locs_count={len(result5['waypoint_locations'])}")

    return all_pass


# ──────────────────────────────────────────────
# STEP 6：_try_direct_route_planning 快路径（异步，坐标齐全）
# ──────────────────────────────────────────────
async def test_step6_direct_route_planning():
    print("\n" + "="*60)
    print("STEP 6: _try_direct_route_planning 快路径（坐标已知时绕过 LLM）")
    print("="*60)
    all_pass = True

    modes_and_wps = [
        # (mode, waypoints, waypoint_locations, expect_wps)
        (TravelMode.DRIVING, ["武汉大学"], ["114.366369,30.540562"], True),
        ("walking",   ["武汉大学"], ["114.366369,30.540562"], False),
        ("bicycling", ["武汉大学"], ["114.366369,30.540562"], False),
        ("transit",   ["武汉大学"], ["114.366369,30.540562"], False),
        ("riding",    [],           [],                       False),  # 别名
    ]

    for mode, wps, wp_locs, expect_wps in modes_and_wps:
        slots = {
            "origin": "武汉站",
            "destination": "光谷广场",
            "origin_location": "114.304569,30.593354",
            "destination_location": "114.410012,30.499524",
            "travel_mode": mode,
            "waypoints": list(wps),
            "waypoint_locations": list(wp_locs),
        }
        result = await _try_direct_route_planning(slots)
        if result is None:
            print(f"  ❌ {mode}: 返回 None（坐标已知时不应为 None）")
            all_pass = False
            continue

        got_status = result.get("status")
        got_mode = result.get("route_mode")
        got_wps = result.get("waypoint_locations", [])
        has_wps = len(got_wps) > 0

        ok = (got_status == "success" and has_wps == expect_wps)
        status_mark = "✅" if ok else "❌"
        if not ok: all_pass = False
        print(f"  {status_mark} {mode}: status={got_status} route_mode={got_mode} waypoint_locations={got_wps} (expect_wps={expect_wps})")

    # 坐标不全时应返回 None
    slots_no_loc = {
        "origin": "武汉站",
        "destination": "光谷广场",
        "travel_mode": "driving",
    }
    result_none = await _try_direct_route_planning(slots_no_loc)
    ok_none = result_none is None
    status_none = "✅" if ok_none else "❌"
    if not ok_none: all_pass = False
    print(f"  {status_none} 坐标不全时返回 None: {result_none}")

    return all_pass


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
async def main():
    results = {}

    results["STEP1 模式归一化"] = test_step1_mode_normalize()
    results["STEP2 途径点模式守卫"] = test_step2_waypoint_mode_guard()
    results["STEP3 缺失槽位检测"] = test_step3_missing_slots()
    results["STEP3B 持续对话模式切换"] = test_step3b_mode_change_continuity()
    results["STEP4 JSON严格解析"] = test_step4_parse_nav_result()
    results["STEP4B life_service 归一化"] = test_step4b_life_service_result_normalize()
    results["STEP5 ensure_map_fields"] = await test_step5_ensure_map_fields()
    results["STEP6 direct_route_planning"] = await test_step6_direct_route_planning()

    print("\n" + "="*60)
    print("总结")
    print("="*60)
    all_ok = True
    for name, ok in results.items():
        mark = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {mark}  {name}")
        if not ok:
            all_ok = False
    print()
    if all_ok:
        print("🎉 所有后端逻辑验证通过！")
    else:
        print("⚠️  存在失败项，请查看上方详情。")
    return all_ok


if __name__ == "__main__":
    asyncio.run(main())
