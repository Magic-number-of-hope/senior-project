import argparse
import json
from typing import Any, Dict

from nlu.pipeline import NavigationNLUPipeline
from nlu.poi_retriever import AMapPOIResolver, build_amap_resolver_from_env


INTENT_FORMAT_MAP = {
    "route_planning": "Route_Planning",
    "traffic_query": "Traffic_Query",
    "poi_search": "POI_Search",
    "navigation_control": "Navigation_Control",
    "unknown": "Unknown",
}


def _convert_to_train_style(parsed: Dict[str, Any]) -> Dict[str, Any]:
    intents = parsed.get("intents", [])
    if len(intents) != 1:
        return parsed

    raw_intent = str(intents[0].get("intent", "unknown"))
    if raw_intent == "multi_intent":
        return parsed

    slots = parsed.get("slots", {})
    train_slots: Dict[str, Any] = {}

    if "origin" in slots:
        train_slots["start_loc"] = slots["origin"]
    if "destination" in slots:
        train_slots["end_loc"] = slots["destination"]
    if "waypoint" in slots:
        waypoint = slots["waypoint"]
        if isinstance(waypoint, list) and len(waypoint) == 1:
            train_slots["via_loc"] = waypoint[0]
        else:
            train_slots["via_loc"] = waypoint
    if "time" in slots:
        train_slots["depart_time"] = slots["time"]

    route_pref = slots.get("route_preference")
    if route_pref == "avoid_tolls":
        train_slots["avoid_toll"] = True
    elif route_pref == "avoid_highway":
        train_slots["avoid_highway"] = True
    elif route_pref == "fastest":
        train_slots["prefer_fastest"] = True
    elif route_pref == "shortest":
        train_slots["prefer_shortest"] = True
    elif route_pref == "avoid_congestion":
        train_slots["avoid_congestion"] = True

    if "transport_mode" in slots:
        train_slots["transport_mode"] = slots["transport_mode"]

    return {
        "intent": INTENT_FORMAT_MAP.get(raw_intent, raw_intent),
        "slots": train_slots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Navigation intent and slot parser baseline")
    parser.add_argument("--query", type=str, required=True, help="User query text")
    parser.add_argument("--amap-key", type=str, default="", help="Optional AMap Web API key")
    parser.add_argument("--amap-city", type=str, default="", help="Optional city for AMap POI search")
    parser.add_argument("--debug-amap", action="store_true", help="Print AMap request stats")
    args = parser.parse_args()

    amap_key = args.amap_key.strip()
    amap_city = args.amap_city.strip()
    if amap_key:
        amap_resolver = AMapPOIResolver(amap_key, city=amap_city)
    else:
        amap_resolver = build_amap_resolver_from_env(default_city=amap_city)
        if amap_resolver is not None and not amap_city:
            amap_city = amap_resolver.city

    pipeline = NavigationNLUPipeline(amap_resolver=amap_resolver, amap_city=amap_city)
    result = pipeline.parse(args.query)
    parsed = result.to_dict()
    formatted = _convert_to_train_style(parsed)
    print(json.dumps(formatted, ensure_ascii=False, indent=2))

    if args.debug_amap:
        debug_info = {
            "amap_enabled": amap_resolver is not None,
            "amap_city": amap_city,
            "request_count": getattr(amap_resolver, "request_count", 0) if amap_resolver else 0,
            "success_count": getattr(amap_resolver, "success_count", 0) if amap_resolver else 0,
            "cache_hit_count": getattr(amap_resolver, "cache_hit_count", 0) if amap_resolver else 0,
            "score_threshold": getattr(amap_resolver, "score_threshold", None) if amap_resolver else None,
            "strict_city": getattr(amap_resolver, "strict_city", None) if amap_resolver else None,
            "last_status": getattr(amap_resolver, "last_status", "not_enabled") if amap_resolver else "not_enabled",
        }
        print("[AMAP_DEBUG] " + json.dumps(debug_info, ensure_ascii=False))


if __name__ == "__main__":
    main()
