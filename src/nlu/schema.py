from typing import Dict, List, Tuple

NAVIGATION_SCHEMA: Dict[str, object] = {
    "required_fields": ["query", "intents", "slots", "json_valid", "errors"],
    "allowed_slot_fields": {
        "origin",
        "destination",
        "waypoint",
        "time",
        "route_preference",
        "transport_mode",
    },
}


def validate_result_dict(result: Dict[str, object]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    for field in NAVIGATION_SCHEMA["required_fields"]:
        if field not in result:
            errors.append(f"Missing required field: {field}")

    intents = result.get("intents")
    if intents is not None and not isinstance(intents, list):
        errors.append("Field intents must be a list")

    slots = result.get("slots")
    if slots is not None:
        if not isinstance(slots, dict):
            errors.append("Field slots must be an object")
        else:
            for slot_name in slots.keys():
                if slot_name not in NAVIGATION_SCHEMA["allowed_slot_fields"]:
                    errors.append(f"Unknown slot field: {slot_name}")

    return len(errors) == 0, errors


def repair_result_dict(result: Dict[str, object]) -> Dict[str, object]:
    repaired = dict(result)
    repaired.setdefault("query", "")
    repaired.setdefault("intents", [])
    repaired.setdefault("slots", {})
    repaired.setdefault("json_valid", False)
    repaired.setdefault("errors", [])

    allowed_fields = NAVIGATION_SCHEMA["allowed_slot_fields"]
    slots = repaired.get("slots", {})
    if isinstance(slots, dict):
        repaired["slots"] = {k: v for k, v in slots.items() if k in allowed_fields}
    else:
        repaired["slots"] = {}

    if not isinstance(repaired["intents"], list):
        repaired["intents"] = []

    if not isinstance(repaired["errors"], list):
        repaired["errors"] = []

    return repaired
