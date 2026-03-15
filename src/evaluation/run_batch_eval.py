import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nlu.multi_intent import split_multi_intent_query
from nlu.pipeline import NavigationNLUPipeline

from evaluation.metrics import (
    intent_accuracy,
    json_valid_rate,
    multi_intent_decomposition_accuracy,
    slot_consistency_score,
    slot_precision_recall_f1,
)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def _extract_primary_intent(item: Dict[str, Any]) -> str:
    intents = item.get("intents", [])
    if not intents:
        return "unknown"
    first = intents[0]
    if isinstance(first, dict):
        return str(first.get("intent", "unknown"))
    return str(first)


def evaluate(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    pipeline = NavigationNLUPipeline()

    gold_intents: List[str] = []
    pred_intents: List[str] = []
    gold_slots: List[Dict[str, Any]] = []
    pred_slots: List[Dict[str, Any]] = []
    parsed_results: List[Dict[str, Any]] = []
    gold_chunks: List[List[str]] = []
    pred_chunks: List[List[str]] = []

    for item in samples:
        query = str(item.get("query", "")).strip()
        if not query:
            continue

        parsed = pipeline.parse(query).to_dict()
        parsed_results.append(parsed)

        gold_intents.append(_extract_primary_intent(item))
        pred_intents.append(_extract_primary_intent(parsed))

        gold_slots.append(dict(item.get("slots", {})))
        pred_slots.append(dict(parsed.get("slots", {})))

        gold_segments = item.get("sub_queries")
        if isinstance(gold_segments, list):
            gold_chunks.append([str(segment) for segment in gold_segments])
            pred_chunks.append(split_multi_intent_query(query))

    metrics: Dict[str, Any] = {
        "sample_count": len(parsed_results),
        "intent_accuracy": intent_accuracy(gold_intents, pred_intents),
        "slot_precision_recall_f1": slot_precision_recall_f1(gold_slots, pred_slots),
        "json_valid_rate": json_valid_rate(parsed_results),
        "slot_consistency_score": slot_consistency_score(gold_slots, pred_slots),
    }

    if gold_chunks:
        metrics["multi_intent_decomposition_accuracy"] = multi_intent_decomposition_accuracy(gold_chunks, pred_chunks)

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch evaluation for navigation NLU baseline")
    parser.add_argument("--data", required=True, help="Path to JSONL test file")
    parser.add_argument("--output", default="", help="Optional path to write metrics JSON")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {data_path}")

    samples = _load_jsonl(data_path)
    metrics = evaluate(samples)

    result_text = json.dumps(metrics, ensure_ascii=False, indent=2)
    print(result_text)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
