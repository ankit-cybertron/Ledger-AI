from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


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


# ============================================================
# CONFIGURATION
# ============================================================

RANDOM_STATE = 42

TEST_SIZE = 0.20

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

TARGET_COLUMN = "label"


# ============================================================
# LOAD DATA
# ============================================================

def load_training_data():
    if not TRAINING_DATA.exists():
        raise FileNotFoundError(
            f"Training data not found: {TRAINING_DATA}"
        )

    data = pd.read_csv(
        TRAINING_DATA
    )

    required_columns = (
        FEATURE_COLUMNS
        + [TARGET_COLUMN]
    )

    missing_columns = [
        column
        for column in required_columns
        if column not in data.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing_columns)
        )

    return data


# ============================================================
# PREPARE DATA
# ============================================================

def prepare_data(data):

    X = data[
        FEATURE_COLUMNS
    ].copy()

    y = data[
        TARGET_COLUMN
    ].astype(int)

    # Replace any accidental infinite values.
    X = X.replace(
        [float("inf"), float("-inf")],
        pd.NA,
    )

    # Fill missing feature values.
    X = X.fillna(0)

    return X, y


# ============================================================
# TRAIN MODEL
# ============================================================

def train_model(X_train, y_train):

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    model.fit(
        X_train,
        y_train,
    )

    return model


# ============================================================
# EVALUATION
# ============================================================

def evaluate_model(
    model,
    X_test,
    y_test,
):

    predictions = model.predict(
        X_test
    )

    probabilities = model.predict_proba(
        X_test
    )[:, 1]

    accuracy = accuracy_score(
        y_test,
        predictions,
    )

    precision = precision_score(
        y_test,
        predictions,
        zero_division=0,
    )

    recall = recall_score(
        y_test,
        predictions,
        zero_division=0,
    )

    f1 = f1_score(
        y_test,
        predictions,
        zero_division=0,
    )

    print("=" * 60)
    print("LEDGER - ML CONFIDENCE MODEL")
    print("=" * 60)

    print(
        f"Test examples : {len(y_test)}"
    )

    print()

    print(
        f"Accuracy  : {accuracy:.4f}"
    )

    print(
        f"Precision : {precision:.4f}"
    )

    print(
        f"Recall    : {recall:.4f}"
    )

    print(
        f"F1 Score  : {f1:.4f}"
    )

    print()

    print("Classification Report:")
    print(
        classification_report(
            y_test,
            predictions,
            target_names=[
                "non-match",
                "match",
            ],
            zero_division=0,
        )
    )

    print("Confusion Matrix:")

    print(
        confusion_matrix(
            y_test,
            predictions,
        )
    )

    return predictions, probabilities


# ============================================================
# MISCLASSIFIED CASES
# ============================================================

def print_misclassified_cases(
    data,
    X_test,
    y_test,
    predictions,
    probabilities,
):
    """
    Surfaces the exact test-set rows the model got wrong,
    by settlement_id / bank_transaction_id, so they can be
    inspected against the original source records. A false
    positive here means the model called a non-match a match
    with reasonable confidence -- in a finance context that
    is the expensive error, so it gets top billing.
    """

    results = pd.DataFrame(
        {
            "settlement_id": data.loc[
                X_test.index, "settlement_id"
            ].values,
            "bank_transaction_id": data.loc[
                X_test.index, "bank_transaction_id"
            ].values,
            "actual": y_test.values,
            "predicted": predictions,
            "confidence": probabilities,
        }
    )

    false_positives = results[
        (results["actual"] == 0)
        & (results["predicted"] == 1)
    ].sort_values(
        "confidence",
        ascending=False,
    )

    false_negatives = results[
        (results["actual"] == 1)
        & (results["predicted"] == 0)
    ].sort_values(
        "confidence",
    )

    print()
    print("=" * 60)
    print("FALSE POSITIVE TEST CASE(S)")
    print("=" * 60)

    if false_positives.empty:
        print("  None")
    else:
        for _, row in false_positives.iterrows():
            print(
                f"  settlement_id        : {row['settlement_id']}"
            )
            print(
                f"  bank_transaction_id  : {row['bank_transaction_id']}"
            )
            print(
                f"  confidence           : {row['confidence']:.4f}"
            )
            print()

    print("=" * 60)
    print("FALSE NEGATIVE TEST CASE(S)")
    print("=" * 60)

    if false_negatives.empty:
        print("  None")
    else:
        for _, row in false_negatives.iterrows():
            print(
                f"  settlement_id        : {row['settlement_id']}"
            )
            print(
                f"  bank_transaction_id  : {row['bank_transaction_id']}"
            )
            print(
                f"  confidence           : {row['confidence']:.4f}"
            )
            print()

    return false_positives, false_negatives


# ============================================================
# FEATURE IMPORTANCE
# ============================================================

def show_feature_importance(model):

    importance = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "importance": model.feature_importances_,
        }
    ).sort_values(
        "importance",
        ascending=False,
    )

    print(
        "\nFeature Importance:"
    )

    for _, row in importance.iterrows():

        print(
            f"  {row['feature']:<25} "
            f"{row['importance']:.4f}"
        )


# ============================================================
# SAVE MODEL
# ============================================================

def save_model(
    model,
    scaler,
):

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        model,
        MODEL_PATH,
    )

    joblib.dump(
        scaler,
        SCALER_PATH,
    )

    print()
    print(
        f"Model saved  : {MODEL_PATH}"
    )

    print(
        f"Scaler saved : {SCALER_PATH}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    data = load_training_data()

    print("=" * 60)
    print("LEDGER - TRAINING CONFIDENCE MODEL")
    print("=" * 60)

    print(
        f"Training data: {TRAINING_DATA}"
    )

    print(
        f"Examples: {len(data)}"
    )

    print()

    print("Class distribution:")

    print(
        data[TARGET_COLUMN]
        .value_counts()
        .sort_index()
    )

    X, y = prepare_data(
        data
    )

    # Stratified split keeps the positive/negative
    # ratio similar in train and test sets.
    (
        X_train,
        X_test,
        y_train,
        y_test,
    ) = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    print()
    print(
        f"Training examples: {len(X_train)}"
    )

    print(
        f"Test examples:     {len(X_test)}"
    )

    # --------------------------------------------------------
    # Scaling
    # --------------------------------------------------------
    #
    # Random Forest does not require feature scaling.
    # We still create and save a scaler because the eventual
    # inference pipeline can use the same preprocessing
    # contract if we compare this model with other classifiers.
    #
    scaler = StandardScaler()

    X_train_scaled = scaler.fit_transform(
        X_train
    )

    X_test_scaled = scaler.transform(
        X_test
    )

    # --------------------------------------------------------
    # Train
    # --------------------------------------------------------

    model = train_model(
        X_train_scaled,
        y_train,
    )

    # --------------------------------------------------------
    # Evaluate
    # --------------------------------------------------------

    predictions, probabilities = evaluate_model(
        model,
        X_test_scaled,
        y_test,
    )

    # --------------------------------------------------------
    # Misclassified cases
    # --------------------------------------------------------

    print_misclassified_cases(
        data,
        X_test,
        y_test,
        predictions,
        probabilities,
    )

    # --------------------------------------------------------
    # Feature importance
    # --------------------------------------------------------

    show_feature_importance(
        model
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_model(
        model,
        scaler,
    )

    print()
    print("=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()