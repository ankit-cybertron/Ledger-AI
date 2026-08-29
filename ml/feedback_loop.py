"""
feedback_loop.py — Human-Correction Feedback Loop for Ledger AI v2 ML Pipeline (T4.6).

Reads resolved exceptions from Exception Ledger (resolution_status != 'open'), converts
each into a high-fidelity feature vector via create_features(), and appends the labeled
rows to matching_training_data.csv.

This allows the ML confidence model to continuously adapt to live deployment data and
human feedback without hardcoded re-labeling.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from ml.build_training_data import create_features, load_data as load_ml_source_data

RESULTS_DIR = ROOT / "data" / "results"
ML_DIR = ROOT / "data" / "ml"

EXCEPTION_LEDGER_PATH = RESULTS_DIR / "exception_ledger.csv"
TRAINING_DATA_PATH = ML_DIR / "matching_training_data.csv"


def load_exception_ledger(path=None):
    p = Path(path) if path else EXCEPTION_LEDGER_PATH
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


def determine_label(row):
    """
    Determines 1 (match) or 0 (non-match) from resolution_status and resolved_outcome fields.
    """
    res_status = str(row.get("resolution_status") or "").strip().lower()
    res_outcome = str(row.get("resolved_outcome") or row.get("human_decision") or "").strip().lower()

    if res_outcome in ("match", "approved", "true", "1", "matched", "confirmed"):
        return 1
    if res_outcome in ("non_match", "rejected", "false", "0", "unmatched"):
        return 0

    if res_status in ("resolved", "matched", "approved", "confirmed"):
        return 1
    if res_status in ("rejected", "false_match", "non_match"):
        return 0

    return 1


def append_resolved_exceptions_to_training_data(
    exception_ledger_path=None,
    training_data_path=None,
):
    exc_path = Path(exception_ledger_path) if exception_ledger_path else EXCEPTION_LEDGER_PATH
    train_path = Path(training_data_path) if training_data_path else TRAINING_DATA_PATH

    exceptions = load_exception_ledger(exc_path)
    if exceptions.empty:
        print("No exception ledger found or ledger is empty.")
        return 0

    if "resolution_status" not in exceptions.columns:
        print("Exception ledger has no 'resolution_status' column.")
        return 0

    resolved_df = exceptions[
        (exceptions["resolution_status"].astype(str).str.strip().str.lower() != "open")
        & (exceptions["resolution_status"].notna())
    ].copy()

    if resolved_df.empty:
        print("No resolved exceptions found (all resolution_status == 'open').")
        return 0

    settlements, bank, _ = load_ml_source_data()

    settlement_lookup = settlements.set_index("settlement_id") if "settlement_id" in settlements.columns else pd.DataFrame()
    bank_lookup = bank.set_index("bank_transaction_id") if "bank_transaction_id" in bank.columns else pd.DataFrame()

    new_examples = []

    for _, row in resolved_df.iterrows():
        sid = str(row.get("settlement_id") or "").strip()
        bid = str(row.get("resolved_bank_id") or row.get("bank_transaction_id") or "").strip()
        label = determine_label(row)

        s_dict = {}
        if not settlement_lookup.empty and sid in settlement_lookup.index:
            s_row = settlement_lookup.loc[sid]
            if isinstance(s_row, pd.DataFrame): s_row = s_row.iloc[0]
            s_dict = s_row.to_dict()
        s_dict["settlement_id"] = sid
        s_dict["amount"] = s_dict.get("amount") or row.get("amount") or 0.0
        s_dict["description"] = s_dict.get("description") or row.get("description") or ""

        b_dict = {}
        if not bank_lookup.empty and bid in bank_lookup.index:
            b_row = bank_lookup.loc[bid]
            if isinstance(b_row, pd.DataFrame): b_row = b_row.iloc[0]
            b_dict = b_row.to_dict()
        b_dict["bank_transaction_id"] = bid
        b_dict["credit"] = b_dict.get("credit") or b_dict.get("amount") or row.get("amount") or 0.0
        b_dict["description"] = b_dict.get("description") or row.get("description") or ""

        feature_dict = create_features(s_dict, b_dict, label=label)
        new_examples.append(feature_dict)

    if not new_examples:
        print("No feature vectors generated from resolved exceptions.")
        return 0

    from ml.feature_schema import FEATURE_COLUMNS

    new_df = pd.DataFrame(new_examples)
    ordered_cols = ["settlement_id", "bank_transaction_id"] + FEATURE_COLUMNS + ["label"]


    if train_path.exists():
        existing_df = pd.read_csv(train_path)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        # Drop duplicates on key IDs keeping the latest human-resolved entry
        if "settlement_id" in combined_df.columns and "bank_transaction_id" in combined_df.columns:
            combined_df = combined_df.drop_duplicates(subset=["settlement_id", "bank_transaction_id"], keep="last")
    else:
        combined_df = new_df

    for col in ordered_cols:
        if col not in combined_df.columns:
            combined_df[col] = 0
    combined_df = combined_df[ordered_cols].fillna(0)


    train_path.parent.mkdir(parents=True, exist_ok=True)
    combined_df.to_csv(train_path, index=False)

    appended_count = len(new_examples)
    print("=" * 60)
    print("LEDGER - HUMAN FEEDBACK LOOP (T4.6)")
    print("=" * 60)
    print(f"Resolved Exceptions Processed : {len(resolved_df)}")
    print(f"New Feature Vectors Appended   : {appended_count}")
    print(f"Total Dataset Rows            : {len(combined_df)}")
    print(f"Training Dataset Saved        : {train_path}")

    return appended_count


def log_human_feedback(settlement_id, bank_transaction_id=None, human_decision="match", confidence=1.0, reason=""):
    """
    Direct endpoint hook (called by routes.py) to record human reviewer feedback.
    Appends a new entry to the Exception Ledger with resolution status and triggers feedback loop.
    """
    exc_path = EXCEPTION_LEDGER_PATH
    exceptions = load_exception_ledger(exc_path)
    
    bid = bank_transaction_id or settlement_id
    res_status = "resolved" if human_decision in ("match", "approved", "confirmed") else "rejected"
    res_outcome = "confirmed_match" if human_decision in ("match", "approved", "confirmed") else "confirmed_non_match"
    
    new_row = {
        "exception_id": f"EXC-{len(exceptions) + 1:04d}",
        "created_at": pd.Timestamp.now().isoformat(),
        "settlement_id": str(settlement_id),
        "bank_transaction_id": str(bid),
        "description": reason or "Human Reviewer Override",
        "amount": 0.0,
        "source": "reviewer",
        "stage": "override",
        "decision": "match" if res_status == "resolved" else "non_match",
        "confidence": float(confidence),
        "exception_type": "manual_review",
        "priority": "low",
        "reason": str(reason),
        "resolution_status": res_status,
        "resolved_outcome": res_outcome,
        "resolved_by": "reviewer"
    }
    
    if not exceptions.empty:
        # Check if already present, update or append
        mask = (exceptions["settlement_id"].astype(str) == str(settlement_id)) & (exceptions["bank_transaction_id"].astype(str) == str(bid))
        if mask.any():
            exceptions.loc[mask, "resolution_status"] = res_status
            exceptions.loc[mask, "resolved_outcome"] = res_outcome
            exceptions.loc[mask, "resolved_by"] = "reviewer"
            updated_df = exceptions
        else:
            updated_df = pd.concat([exceptions, pd.DataFrame([new_row])], ignore_index=True)
    else:
        updated_df = pd.DataFrame([new_row])
        
    exc_path.parent.mkdir(parents=True, exist_ok=True)
    updated_df.to_csv(exc_path, index=False)
    
    return append_resolved_exceptions_to_training_data(exc_path)


if __name__ == "__main__":
    append_resolved_exceptions_to_training_data()

