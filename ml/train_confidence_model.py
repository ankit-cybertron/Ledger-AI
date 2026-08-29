"""
train_confidence_model.py — ML Confidence Model Trainer (v2 extended) for Ledger AI v2.

Trains a StandardScaler + RandomForestClassifier model using the single canonical
FEATURE_COLUMNS schema from ml.feature_schema (T4.1, T4.2).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
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

from ml.feature_schema import FEATURE_COLUMNS

ML_DIR = ROOT / "data" / "ml"
MODEL_DIR = ROOT / "models"

TRAINING_DATA = ML_DIR / "matching_training_data.csv"
MODEL_PATH = MODEL_DIR / "confidence_model.joblib"
SCALER_PATH = MODEL_DIR / "confidence_scaler.joblib"

RANDOM_STATE = 42
TEST_SIZE = 0.20
TARGET_COLUMN = "label"


def load_training_data():
    if not TRAINING_DATA.exists():
        raise FileNotFoundError(f"Training dataset not found at {TRAINING_DATA}")
    df = pd.read_csv(TRAINING_DATA)
    if df.empty:
        raise ValueError(f"Training dataset is empty at {TRAINING_DATA}")
    return df


def prepare_features_and_labels(df: pd.DataFrame):
    missing_cols = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Training data is missing expected feature columns: {missing_cols}")

    X = df[FEATURE_COLUMNS].copy()
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0)

    if TARGET_COLUMN not in df.columns:
        raise ValueError(f"Target column '{TARGET_COLUMN}' missing from training dataset.")

    y = df[TARGET_COLUMN].astype(int)
    return X, y


def train_model(X_train, y_train):
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        random_state=RANDOM_STATE,
        class_weight="balanced_subsample"
    )
    model.fit(X_train_scaled, y_train)

    return model, scaler


def evaluate_model(model, scaler, X_test, y_test):
    X_test_scaled = scaler.transform(X_test)
    y_pred = model.predict(X_test_scaled)

    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1_score": f1_score(y_test, y_pred, zero_division=0),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": classification_report(y_test, y_pred, zero_division=0),
    }

    return metrics


def save_artifacts(model, scaler):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)


def main():
    df = load_training_data()
    X, y = prepare_features_and_labels(df)

    if len(df) < 5 or len(y.unique()) < 2:
        X_train, X_test, y_train, y_test = X, X, y, y
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
        )

    model, scaler = train_model(X_train, y_train)
    metrics = evaluate_model(model, scaler, X_test, y_test)
    save_artifacts(model, scaler)

    print("=" * 60)
    print("LEDGER - ML CONFIDENCE MODEL TRAINER (Canonical Schema)")
    print("=" * 60)
    print(f"Training samples : {len(X_train)}")
    print(f"Testing samples  : {len(X_test)}")
    print(f"Accuracy         : {metrics['accuracy']:.4f}")
    print(f"Precision        : {metrics['precision']:.4f}")
    print(f"Recall           : {metrics['recall']:.4f}")
    print(f"F1 Score         : {metrics['f1_score']:.4f}")
    print("\nSaved artifacts:")
    print(f"  Model  : {MODEL_PATH}")
    print(f"  Scaler : {SCALER_PATH}")


if __name__ == "__main__":
    main()