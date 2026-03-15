from typing import List, Optional

from .multi_intent import classify_intent, split_multi_intent_query
from .poi_retriever import (
    AMapPOIResolver,
    POIIndex,
    build_amap_resolver_from_env,
    build_default_index,
    calibrate_location_slot_with_amap,
)
from .schema import repair_result_dict, validate_result_dict
from .slot_extractor import extract_slots
from .types import IntentUnit, ParseResult


class NavigationNLUPipeline:
    """Baseline pipeline for intent recognition and slot filling."""

    CITY_HINTS = [
        "武汉",
        "北京",
        "上海",
        "广州",
        "深圳",
        "杭州",
        "南京",
        "成都",
        "重庆",
        "西安",
        "襄阳",
        "宜昌",
        "荆州",
        "十堰",
        "恩施",
        "咸宁",
        "黄石",
        "荆门",
        "随州",
        "孝感",
        "鄂州",
        "黄冈",
        "枣阳",
    ]

    def __init__(
        self,
        poi_index: Optional[POIIndex] = None,
        amap_resolver: Optional[AMapPOIResolver] = None,
        amap_city: str = "",
    ):
        self.poi_index = poi_index or build_default_index()
        self.amap_resolver = amap_resolver if amap_resolver is not None else build_amap_resolver_from_env(amap_city)
        self.amap_city = amap_city

    def parse(self, query: str) -> ParseResult:
        sub_queries = split_multi_intent_query(query)
        intents: List[IntentUnit] = []

        for piece in sub_queries:
            intents.append(IntentUnit(intent=classify_intent(piece), confidence=0.5, text_span=piece))

        merged_slots = extract_slots(query)
        merged_slots = self._calibrate_slots(merged_slots)

        result = ParseResult(query=query, intents=intents, slots=merged_slots)
        as_dict = repair_result_dict(result.to_dict())
        valid, errors = validate_result_dict(as_dict)

        result.json_valid = valid
        result.errors = errors
        return result

    def _calibrate_slots(self, slots: dict) -> dict:
        calibrated = dict(slots)
        city_hint = self._resolve_city_hint(calibrated)

        for key in ["origin", "destination"]:
            value = calibrated.get(key)
            if isinstance(value, str) and value:
                calibrated[key] = calibrate_location_slot_with_amap(
                    value=value,
                    index=self.poi_index,
                    resolver=self.amap_resolver,
                    city=city_hint,
                )

        waypoints = calibrated.get("waypoint")
        if isinstance(waypoints, list):
            calibrated["waypoint"] = [
                calibrate_location_slot_with_amap(
                    value=item,
                    index=self.poi_index,
                    resolver=self.amap_resolver,
                    city=city_hint,
                )
                if isinstance(item, str)
                else item
                for item in waypoints
            ]

        return calibrated

    def _resolve_city_hint(self, slots: dict) -> str:
        for key in ["origin", "destination"]:
            value = slots.get(key)
            if not isinstance(value, str):
                continue
            for city in self.CITY_HINTS:
                if city in value:
                    return city

        return self.amap_city
