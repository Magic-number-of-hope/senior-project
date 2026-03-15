from collections import Counter
from typing import Dict, List


def intent_accuracy(gold_intents: List[str], pred_intents: List[str]) -> float:
    if not gold_intents:
        return 0.0
    pred = pred_intents[: len(gold_intents)] + [""] * max(0, len(gold_intents) - len(pred_intents))
    correct = sum(1 for g, p in zip(gold_intents, pred) if g == p)
    return correct / len(gold_intents)


def multi_intent_decomposition_accuracy(gold_chunks: List[List[str]], pred_chunks: List[List[str]]) -> float:
    """Compute exact-match accuracy for multi-intent decomposition segments."""
    if not gold_chunks:
        return 0.0

    total = len(gold_chunks)
    correct = 0
    for gold, pred in zip(gold_chunks, pred_chunks):
        gold_norm = [item.strip().lower() for item in gold]
        pred_norm = [item.strip().lower() for item in pred]
        if gold_norm == pred_norm:
            correct += 1

    return correct / total


def slot_precision_recall_f1(gold_slots: List[Dict[str, object]], pred_slots: List[Dict[str, object]]) -> Dict[str, float]:
    gold_items = Counter()
    pred_items = Counter()

    for sample in gold_slots:
        for key, value in sample.items():
            gold_items[(key, str(value))] += 1

    for sample in pred_slots:
        for key, value in sample.items():
            pred_items[(key, str(value))] += 1

    tp = sum((gold_items & pred_items).values())
    fp = sum((pred_items - gold_items).values())
    fn = sum((gold_items - pred_items).values())

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def json_valid_rate(results: List[Dict[str, object]]) -> float:
    if not results:
        return 0.0
    valid_count = sum(1 for item in results if bool(item.get("json_valid")))
    return valid_count / len(results)


def slot_consistency_score(gold_slots: List[Dict[str, object]], pred_slots: List[Dict[str, object]]) -> float:
    if not gold_slots:
        return 0.0
    matches = 0
    for gold, pred in zip(gold_slots, pred_slots):
        matches += int(gold == pred)
    return matches / len(gold_slots)
