from enum import Enum
from typing import Dict, List


class IntentType(str, Enum):
    ROUTE_PLANNING = "route_planning"
    TRAFFIC_QUERY = "traffic_query"
    POI_SEARCH = "poi_search"
    NAVIGATION_CONTROL = "navigation_control"
    MULTI_INTENT = "multi_intent"
    UNKNOWN = "unknown"


SUPPORTED_INTENTS: List[str] = [intent.value for intent in IntentType]


SLOT_DEFINITION: Dict[str, str] = {
    "origin": "Starting location",
    "destination": "Destination location",
    "waypoint": "Intermediate stop list",
    "time": "Departure or arrival time expression",
    "route_preference": "Route preference, such as avoid tolls",
    "transport_mode": "Driving, walking, biking, transit",
}


ROUTE_PREFERENCES = {
    "fastest": ["fastest", "quickest", "shortest time", "最快", "最快到", "尽快"],
    "shortest": ["shortest", "least distance", "最短", "距离最短", "路程最短"],
    "avoid_tolls": ["avoid toll", "no toll", "without toll", "避免收费", "不走收费", "避开收费"],
    "avoid_highway": ["avoid highway", "no highway", "不走高速", "避免高速", "避开高速"],
    "avoid_congestion": ["avoid traffic", "least traffic", "避开拥堵", "不堵", "躲开堵车"],
}


TRANSPORT_MODES = {
    "driving": ["drive", "driving", "car", "开车", "自驾", "驾车"],
    "walking": ["walk", "walking", "on foot", "步行", "走路"],
    "bicycling": ["bike", "bicycle", "cycling", "骑行", "骑车", "单车"],
    "transit": ["bus", "subway", "metro", "transit", "public transport", "公交", "地铁", "公共交通"],
}
