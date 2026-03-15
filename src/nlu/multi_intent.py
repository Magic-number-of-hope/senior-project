import re
from typing import Dict, List

from .ontology import IntentType


INTENT_KEYWORDS: Dict[str, List[str]] = {
    IntentType.ROUTE_PLANNING.value: [
        "go to",
        "route",
        "navigate",
        "from",
        "to",
        "how to get",
        "去",
        "导航到",
        "从",
        "到",
        "怎么走",
        "路线",
    ],
    IntentType.TRAFFIC_QUERY.value: [
        "traffic",
        "jam",
        "road condition",
        "congestion",
        "路况",
        "堵车",
        "拥堵",
        "交通情况",
    ],
    IntentType.POI_SEARCH.value: [
        "find",
        "search",
        "nearby",
        "restaurant",
        "hotel",
        "gas station",
        "找",
        "附近",
        "餐厅",
        "酒店",
        "加油站",
    ],
    IntentType.NAVIGATION_CONTROL.value: [
        "start navigation",
        "stop navigation",
        "mute",
        "zoom in",
        "zoom out",
        "开始导航",
        "结束导航",
        "停止导航",
        "静音",
        "放大",
        "缩小",
    ],
}


_SPLIT_PATTERN = re.compile(
    r"\s*(?:,|;|，|。| and then | then | after that | meanwhile | also | 然后 | 接着 | 另外 | 并且 | 同时 | 顺便 )\s*",
    re.IGNORECASE,
)


def split_multi_intent_query(query: str) -> List[str]:
    """Split one query into potential sub-intent segments."""
    segments = [segment.strip() for segment in _SPLIT_PATTERN.split(query) if segment.strip()]
    return segments or [query.strip()]


def classify_intent(text: str) -> str:
    lowered = text.lower()
    matched = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            matched.append(intent)
    if not matched:
        return IntentType.UNKNOWN.value
    if len(matched) > 1:
        return IntentType.MULTI_INTENT.value
    return matched[0]
