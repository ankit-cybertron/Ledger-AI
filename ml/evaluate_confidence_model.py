"""
evaluate_confidence_model.py — Model Evaluation & Candidate Scoring (v2 extended) for Ledger AI v2.

Computes:
  - Best score, second-best score, margin, and candidate count per settlement (T4.3).
  - Brier score loss calibration check (T4.5).
  - Persists confidence_predictions.csv with candidate metrics and margin information.
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

ML_DIR = ROOT / "data" / "ml"
MODEL_DIR = ROOT / "models"

TRAINING_DATA = ML_DIR / "matching_training_data.csv"
MODEL_PATH = MODEL_DIR / "confidence_model.joblib"
SCALER_PATH = MODEL_DIR / "confidence_scaler.joblib"
OUTPUT_PATH = ML_DIR / "confidence_predictions.csv"

TARGET_COLUMN = "label"


def get_feature_columns(data: pd.DataFrame) -> list:
    ignore_cols = {"settlement_id", "bank_transaction_id", TARGET_COLUMN}
    return [col for col in data.columns if col not in ignore_cols]


def load_data():
    data = pd.read_csv(TRAINING_DATA)
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return data, model, scaler


def generate_predictions(data, model, scaler):
    feature_cols = get_feature_columns(data)
    X = data[feature_cols].copy()
    X = X.replace([float("inf"), float("-inf")], pd.NA).fillna(0)

    X_scaled = scaler.transform(X)
    probabilities = model.predict_proba(X_scaled)[:, 1]
    predictions = (probabilities >= 0.50).astype(int)

    result = data[["settlement_id", "bank_transaction_id", "label"]].copy()
    result["confidence"] = probabilities
    result["prediction"] = predictions
    result["correct"] = (result["label"] == result["prediction"])

    # T4.3 — Calculate best_score, second_best_score, margin, candidate_count per settlement_id
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


def print_confidence_bands(result):
    bands = pd.cut(
        result["confidence"],
        bins=[-0.01, 0.50, 0.70, 0.90, 1.01],
        labels=["< 0.50", "0.50 - 0.70", "0.70 - 0.90", ">= 0.90"]
    )
    print("\nConfidence distribution:")
    print(bands.value_counts(sort=False))


def print_calibration_metrics(result):
    brier = brier_score_loss(result["label"], result["confidence"])
    print("\n" + "=" * 60)
    print("PROBABILITY CALIBRATION (T4.5)")
    print("=" * 60)
    print(f"Brier Score Loss (lower is better): {brier:.6f}")
    
    pos_avg = result[result["label"] == 1]["confidence"].mean() if not result[result["label"] == 1].empty else 0.0
    neg_avg = result[result["label"] == 0]["confidence"].mean() if not result[result["label"] == 0].empty else 0.0
    print(f"Empirical Positive Match Avg Confidence: {pos_avg:.4f}")
    print(f"Empirical Negative Match Avg Confidence: {neg_avg:.4f}")


def print_hard_cases(result):
    print("\nLow-confidence true matches:")
    low_confidence_matches = result[(result["label"] == 1) & (result["confidence"] < 0.90)].sort_values("confidence").head(10)
    if low_confidence_matches.empty:
        print("  None")
    else:
        print(low_confidence_matches[["settlement_id", "bank_transaction_id", "confidence", "margin"]].to_string(index=False))

    print("\nHigh-confidence false matches:")
    high_confidence_false_matches = result[(result["label"] == 0) & (result["confidence"] >= 0.90)].sort_values("confidence", ascending=False).head(10)
    if high_confidence_false_matches.empty:
        print("  None")
    else:
        print(high_confidence_false_matches[["settlement_id", "bank_transaction_id", "confidence", "margin"]].to_string(index=False))


def main():
    data, model, scaler = load_data()
    result = generate_predictions(data, model, scaler)

    print("=" * 60)
    print("LEDGER - CONFIDENCE MODEL EVALUATION (v2 Extended)")
    print("=" * 60)
    print(f"Total candidates : {len(result)}")
    print(f"Correct          : {result['correct'].sum()}")
    print(f"Accuracy         : {result['correct'].mean():.4f}")

    print_calibration_metrics(result)
    print_confidence_bands(result)
    print_hard_cases(result)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()