import re
from typing import Dict, List

from .ontology import ROUTE_PREFERENCES, TRANSPORT_MODES


FROM_TO_PATTERN = re.compile(r"from\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+?)(?:$|\s+(?:at|by|with|via))", re.IGNORECASE)
VIA_PATTERN = re.compile(r"via\s+([^,;]+)", re.IGNORECASE)
TIME_PATTERN = re.compile(r"\b(?:at|by|before|after)\s+([0-2]?\d(?::[0-5]\d)?(?:\s?[ap]m)?)", re.IGNORECASE)
CN_FROM_TO_PATTERN = re.compile(r"从\s*(?P<origin>.+?)\s*(?:到|去|前往)\s*(?P<destination>.+?)(?:$|，|。|\s*(?:在|于|经过|途经|避开|开车|步行|骑行))")
CN_PLAIN_FROM_TO_PATTERN = re.compile(r"(?P<origin>[^，。；;\s]+?)\s*到\s*(?P<destination>[^，。；;]+?)(?:怎么走|怎么去|怎么到|如何走|如何去|路线|$|，|。)")
CN_DESTINATION_PATTERN = re.compile(r"(?:去|到|前往|导航到)\s*(?P<destination>[^，。；;]+)")
CN_VIA_PATTERN = re.compile(r"(?:经过|途经)\s*([^，。；;]+)")
CN_TIME_PATTERN = re.compile(r"(?:今天|明天|后天)?\s*(?:上午|中午|下午|晚上|凌晨)?\s*([0-2]?\d(?::[0-5]\d)?\s*(?:点|分|:)?\s*(?:前|后)?)")


def _clean_location_text(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"(怎么走|怎么去|怎么到|如何走|如何去|路线.*)$", "", cleaned)
    return cleaned.strip()


def _match_vocab(query: str, vocab: Dict[str, List[str]]) -> str:
    lowered = query.lower()
    for normalized, aliases in vocab.items():
        if any(alias in lowered for alias in aliases):
            return normalized
    return ""


def extract_slots(query: str) -> Dict[str, object]:
    """Rule-based slot extraction baseline for navigation text."""
    slots: Dict[str, object] = {}

    from_to = FROM_TO_PATTERN.search(query)
    if from_to:
        slots["origin"] = _clean_location_text(from_to.group("origin"))
        slots["destination"] = _clean_location_text(from_to.group("destination"))
    else:
        cn_from_to = CN_FROM_TO_PATTERN.search(query)
        if cn_from_to:
            slots["origin"] = _clean_location_text(cn_from_to.group("origin"))
            slots["destination"] = _clean_location_text(cn_from_to.group("destination"))
        else:
            cn_plain_from_to = CN_PLAIN_FROM_TO_PATTERN.search(query)
            if cn_plain_from_to:
                slots["origin"] = _clean_location_text(cn_plain_from_to.group("origin"))
                slots["destination"] = _clean_location_text(cn_plain_from_to.group("destination"))
            else:
                cn_destination = CN_DESTINATION_PATTERN.search(query)
                if cn_destination:
                    slots["destination"] = _clean_location_text(cn_destination.group("destination"))

    via_matches = [match.strip() for match in VIA_PATTERN.findall(query) if match.strip()]
    if not via_matches:
        via_matches = [match.strip() for match in CN_VIA_PATTERN.findall(query) if match.strip()]
    if via_matches:
        slots["waypoint"] = via_matches

    time_match = TIME_PATTERN.search(query)
    if time_match:
        slots["time"] = time_match.group(1).strip()
    else:
        cn_time_match = CN_TIME_PATTERN.search(query)
        if cn_time_match:
            slots["time"] = cn_time_match.group(1).strip()

    preference = _match_vocab(query, ROUTE_PREFERENCES)
    if preference:
        slots["route_preference"] = preference

    mode = _match_vocab(query, TRANSPORT_MODES)
    if mode:
        slots["transport_mode"] = mode

    return slots
