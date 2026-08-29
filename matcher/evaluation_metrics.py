"""
evaluation_metrics.py — Consolidated precision/recall/F1 calculation (T3.6).

Single shared implementation of precision, recall, and F1 metrics for evaluation scripts.
"""

from typing import Dict, Any, Set, Tuple
import pandas as pd


def extract_pairs(df: pd.DataFrame) -> Set[Tuple[str, str]]:

    """
    Extracts (primary_id, counterpart_id) relationship pairs from a DataFrame (T8.5).
    Handles both canonical and legacy column names as well as multi-id pipe-separated strings.
    """
    if df is None or df.empty:
        return set()
    p_col = "primary_transaction_id" if "primary_transaction_id" in df.columns else "settlement_id"
    c_col = "counterpart_transaction_id" if "counterpart_transaction_id" in df.columns else "bank_transaction_id"

    pairs = set()
    for _, row in df.iterrows():
        p_val = row.get(p_col)
        c_val = row.get(c_col)
        if pd.isna(p_val) or pd.isna(c_val):
            continue
        p_ids = str(p_val).split("|")
        c_ids = str(c_val).split("|")
        for p in p_ids:
            for c in c_ids:
                pairs.add((p.strip(), c.strip()))
    return pairs


def compute_precision_recall_f1(predicted_pairs: Set[Tuple[Any, Any]], true_pairs: Set[Tuple[Any, Any]]) -> Dict[str, Any]:

    """
    Computes precision, recall, and F1 score between predicted and ground-truth relationship pairs.
    """
    true_positives = len(predicted_pairs & true_pairs)
    false_positives = len(predicted_pairs - true_pairs)
    false_negatives = len(true_pairs - predicted_pairs)

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )

    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )

    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "ground_truth_count": len(true_pairs),
        "predicted_count": len(predicted_pairs),
    }
