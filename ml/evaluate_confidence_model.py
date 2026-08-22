from pathlib import Path

import joblib
import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

ML_DIR = ROOT / "data" / "ml"
MODEL_DIR = ROOT / "models"

TRAINING_DATA = (
    ML_DIR / "matching_training_data.csv"
)

MODEL_PATH = (
    MODEL_DIR / "confidence_model.joblib"
)

SCALER_PATH = (
    MODEL_DIR / "confidence_scaler.joblib"
)

OUTPUT_PATH = (
    ML_DIR / "confidence_predictions.csv"
)


# ============================================================
# FEATURES
# ============================================================

FEATURE_COLUMNS = [
    "settlement_amount",
    "bank_amount",
    "amount_difference",
    "amount_difference_pct",
    "date_difference_days",
    "utr_match",
    "utr_missing",
    "narration_similarity",
    "currency_match",
]


# ============================================================
# LOAD
# ============================================================

def load_data():
    data = pd.read_csv(
        TRAINING_DATA
    )

    model = joblib.load(
        MODEL_PATH
    )

    scaler = joblib.load(
        SCALER_PATH
    )

    return data, model, scaler


# ============================================================
# GENERATE CONFIDENCE
# ============================================================

def generate_predictions(
    data,
    model,
    scaler,
):
    X = data[
        FEATURE_COLUMNS
    ].copy()

    X = X.replace(
        [float("inf"), float("-inf")],
        pd.NA,
    )

    X = X.fillna(0)

    X_scaled = scaler.transform(X)

    probabilities = model.predict_proba(
        X_scaled
    )[:, 1]

    predictions = (
        probabilities >= 0.50
    ).astype(int)

    result = data[
        [
            "settlement_id",
            "bank_transaction_id",
            "label",
        ]
    ].copy()

    result["confidence"] = probabilities
    result["prediction"] = predictions

    result["correct"] = (
        result["label"]
        == result["prediction"]
    )

    return result


# ============================================================
# CONFIDENCE BANDS
# ============================================================

def print_confidence_bands(result):

    bands = pd.cut(
        result["confidence"],
        bins=[
            -0.01,
            0.50,
            0.70,
            0.90,
            1.01,
        ],
        labels=[
            "< 0.50",
            "0.50 - 0.70",
            "0.70 - 0.90",
            ">= 0.90",
        ],
    )

    print(
        "\nConfidence distribution:"
    )

    print(
        bands.value_counts(
            sort=False
        )
    )


# ============================================================
# HARD CASES
# ============================================================

def print_hard_cases(result):

    print(
        "\nLow-confidence true matches:"
    )

    low_confidence_matches = (
        result[
            (result["label"] == 1)
            & (result["confidence"] < 0.90)
        ]
        .sort_values("confidence")
        .head(10)
    )

    if low_confidence_matches.empty:
        print("  None")
    else:
        print(
            low_confidence_matches[
                [
                    "settlement_id",
                    "bank_transaction_id",
                    "confidence",
                ]
            ].to_string(index=False)
        )

    print(
        "\nHigh-confidence false matches:"
    )

    high_confidence_false_matches = (
        result[
            (result["label"] == 0)
            & (result["confidence"] >= 0.90)
        ]
        .sort_values(
            "confidence",
            ascending=False,
        )
        .head(10)
    )

    if high_confidence_false_matches.empty:
        print("  None")
    else:
        print(
            high_confidence_false_matches[
                [
                    "settlement_id",
                    "bank_transaction_id",
                    "confidence",
                ]
            ].to_string(index=False)
        )


# ============================================================
# SUMMARY
# ============================================================

def print_summary(result):

    total = len(result)

    correct = int(
        result["correct"].sum()
    )

    accuracy = (
        correct / total
        if total
        else 0.0
    )

    print("=" * 60)
    print("LEDGER - CONFIDENCE MODEL EVALUATION")
    print("=" * 60)

    print(
        f"Total candidates : {total}"
    )

    print(
        f"Correct          : {correct}"
    )

    print(
        f"Accuracy         : {accuracy:.4f}"
    )

    print()

    print(
        f"Average confidence: "
        f"{result['confidence'].mean():.4f}"
    )

    print(
        f"Positive avg confidence: "
        f"{result.loc[result['label'] == 1, 'confidence'].mean():.4f}"
    )

    print(
        f"Negative avg confidence: "
        f"{result.loc[result['label'] == 0, 'confidence'].mean():.4f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    data, model, scaler = load_data()

    result = generate_predictions(
        data,
        model,
        scaler,
    )

    result = result.sort_values(
        "confidence",
        ascending=False,
    ).reset_index(
        drop=True
    )

    ML_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print_summary(
        result
    )

    print_confidence_bands(
        result
    )

    print_hard_cases(
        result
    )

    print()
    print(
        f"Saved: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()