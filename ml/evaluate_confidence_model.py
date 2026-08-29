"""
evaluate_confidence_model.py — Model Evaluation & Candidate Scoring (v2 extended) for Ledger AI v2.

Computes:
  - Strict feature schema validation against ml.feature_schema.FEATURE_COLUMNS (T4.3).
    Raises ValueError with missing/extra column details if schema drifts (no silent zero-filling).
  - Configurable threshold sweep from MatchingConfig.evaluation_threshold_sweep (T4.4).
  - Candidate metrics, Brier score loss calibration, and confidence_predictions.csv generation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import pandas as pd
import numpy as np
from sklearn.metrics import brier_score_loss

from config import MatchingConfig
from ml.feature_schema import FEATURE_COLUMNS

ML_DIR = ROOT / "data" / "ml"
MODEL_DIR = ROOT / "models"

TRAINING_DATA = ML_DIR / "matching_training_data.csv"
MODEL_PATH = MODEL_DIR / "confidence_model.joblib"
SCALER_PATH = MODEL_DIR / "confidence_scaler.joblib"
OUTPUT_PATH = ML_DIR / "confidence_predictions.csv"

TARGET_COLUMN = "label"
METADATA_COLUMNS = {"settlement_id", "bank_transaction_id", TARGET_COLUMN, "confidence", "prediction", "correct", "margin"}


def validate_feature_schema(data_columns: list) -> list:
    """
    Validates that input data columns match FEATURE_COLUMNS exactly (T4.3).
    Raises a ValueError naming missing or extra columns if feature drift occurs.
    """
    actual_features = [col for col in data_columns if col not in METADATA_COLUMNS]
    expected_set = set(FEATURE_COLUMNS)
    actual_set = set(actual_features)

    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)

    if missing or extra:
        err_parts = ["ML Feature Schema Mismatch Detected (T4.3)!"]
        if missing:
            err_parts.append(f"  Missing required feature columns: {missing}")
        if extra:
            err_parts.append(f"  Unexpected extra feature columns: {extra}")
        raise ValueError("\n".join(err_parts))

    return FEATURE_COLUMNS


def load_data():
    data = pd.read_csv(TRAINING_DATA)
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return data, model, scaler


def generate_predictions(data, model, scaler, cfg: MatchingConfig = None):
    if cfg is None:
        cfg = MatchingConfig()

    feature_cols = validate_feature_schema(list(data.columns))
    if data.empty:
        empty_res = data.copy()
        for col in ["confidence", "prediction", "correct", "best_score", "second_best_score", "margin", "candidate_count"]:
            if col not in empty_res.columns:
                empty_res[col] = []
        return empty_res

    X = data[feature_cols].copy()
    X = X.replace([float("inf"), float("-inf")], pd.NA).fillna(0)

    X_scaled = scaler.transform(X)
    probabilities = model.predict_proba(X_scaled)[:, 1]
    predictions = (probabilities >= 0.50).astype(int)

    result = data[["settlement_id", "bank_transaction_id", "label"]].copy()
    result["confidence"] = probabilities
    result["prediction"] = predictions
    result["correct"] = (result["label"] == result["prediction"])

    res_grouped = []
    for sid, group in result.groupby("settlement_id", sort=False):
        group_conf = sorted(group["confidence"].tolist(), reverse=True)
        best_score = group_conf[0]
        second_best_score = group_conf[1] if len(group_conf) > 1 else 0.0
        margin = round(best_score - second_best_score, 4)
        cand_count = len(group_conf)

        g_copy = group.copy()
        g_copy["best_score"] = round(best_score, 4)
        g_copy["second_best_score"] = round(second_best_score, 4)
        g_copy["margin"] = margin
        g_copy["candidate_count"] = cand_count
        res_grouped.append(g_copy)

    final_df = pd.concat(res_grouped, ignore_index=True) if res_grouped else result
    return final_df


def print_confidence_bands(result, cfg: MatchingConfig = None):
    if cfg is None:
        cfg = MatchingConfig()
    thresholds = getattr(cfg, "evaluation_threshold_sweep", (0.50, 0.70, 0.80, 0.90, 0.95))
    bins = [-0.01] + sorted(list(set(thresholds))) + [1.01]
    labels = [f"<{bins[1]}"] + [f"{bins[i]} - {bins[i+1]}" for i in range(1, len(bins)-2)] + [f">={bins[-2]}"]

    bands = pd.cut(result["confidence"], bins=bins, labels=labels)
    print("\nConfidence distribution (Config Sweep):")
    print(bands.value_counts(sort=False))


def print_calibration_metrics(result):
    if result.empty or "label" not in result.columns or "confidence" not in result.columns:
        print("\nPROBABILITY CALIBRATION: No prediction samples available.")
        return

    brier = brier_score_loss(result["label"], result["confidence"])
    print("\n" + "=" * 60)
    print("PROBABILITY CALIBRATION")
    print("=" * 60)
    print(f"Brier Score Loss (lower is better): {brier:.6f}")

    pos_avg = result[result["label"] == 1]["confidence"].mean() if not result[result["label"] == 1].empty else 0.0
    neg_avg = result[result["label"] == 0]["confidence"].mean() if not result[result["label"] == 0].empty else 0.0
    print(f"Empirical Positive Match Avg Confidence: {pos_avg:.4f}")
    print(f"Empirical Negative Match Avg Confidence: {neg_avg:.4f}")


def print_hard_cases(result):
    if result.empty:
        return
    cols_to_print = [c for c in ["primary_id", "counterpart_id", "settlement_id", "bank_transaction_id", "confidence", "margin"] if c in result.columns]
    print("\nLow-confidence true matches:")
    low_confidence_matches = result[(result["label"] == 1) & (result["confidence"] < 0.90)].sort_values("confidence").head(10)
    if low_confidence_matches.empty:
        print("  None")
    else:
        print(low_confidence_matches[cols_to_print].to_string(index=False))

    print("\nHigh-confidence false matches:")
    high_confidence_false_matches = result[(result["label"] == 0) & (result["confidence"] >= 0.90)].sort_values("confidence", ascending=False).head(10)
    if high_confidence_false_matches.empty:
        print("  None")
    else:
        print(high_confidence_false_matches[cols_to_print].to_string(index=False))



def main():
    cfg = MatchingConfig.load_with_env_overrides()
    data, model, scaler = load_data()
    result = generate_predictions(data, model, scaler, cfg)

    print("=" * 60)
    print("LEDGER - CONFIDENCE MODEL EVALUATION (Strict Feature Schema T4.3)")
    print("=" * 60)
    print(f"Total candidates : {len(result)}")
    if not result.empty and "correct" in result.columns:
        print(f"Correct          : {result['correct'].sum()}")
        print(f"Accuracy         : {result['correct'].mean():.4f}")
    else:
        print("Correct          : 0")
        print("Accuracy         : 0.0000")

    print_calibration_metrics(result)
    if not result.empty:
        print_confidence_bands(result, cfg)
        print_hard_cases(result)
    print_hard_cases(result)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()