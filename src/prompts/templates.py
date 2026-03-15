from typing import Iterable


def build_zero_shot_prompt(query: str) -> str:
    return (
        "You are a navigation NLU parser. Extract intents and slots from the user query.\n"
        "Return strict JSON with fields: query, intents, slots, json_valid, errors.\n"
        "Supported slots: origin, destination, waypoint, time, route_preference, transport_mode.\n"
        f"User query: {query}\n"
    )


def build_few_shot_prompt(query: str, examples: Iterable[str]) -> str:
    example_block = "\n".join(f"Example: {line}" for line in examples)
    return (
        "You are a navigation NLU parser. Learn from examples and then parse the query.\n"
        f"{example_block}\n"
        "Return strict JSON only.\n"
        f"User query: {query}\n"
    )


def build_cot_prompt(query: str) -> str:
    return (
        "You are a navigation NLU parser.\n"
        "Step 1: Identify all possible intents.\n"
        "Step 2: Split multi-intent query into sub-intents if needed.\n"
        "Step 3: Extract slots for each sub-intent.\n"
        "Step 4: Merge slots and output strict JSON.\n"
        f"User query: {query}\n"
    )
