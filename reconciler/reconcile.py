"""
reconcile.py — Reconciliation Pipeline Orchestrator (v2 extended) for Ledger AI v2.

Orchestrates multi-stage reconciliation:
  Stage 1: Deterministic Exact Matches
  Stage 2: Dynamic Tolerance Matches (1:1 and 1:N split settlements)
  Stage 3: ML Confidence Matching with Margin-Aware Decision Gate (T4.4)
  Stage 4: LLM Review / Exception Handling

Persists reconciliation_config.json on every run for reproducibility.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from datetime import datetime
import json
from typing import Optional, List, Dict, Any

import pandas as pd
from dotenv import load_dotenv

from config import MatchingConfig

load_dotenv(ROOT / ".env")

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"
ML_DIR = ROOT / "data" / "ml"

SETTLEMENTS_PATH = GENERATED_DIR / "razorpay_settlements.csv"
EXACT_RESULTS_PATH = RESULTS_DIR / "exact_matches.csv"
TOLERANCE_RESULTS_PATH = RESULTS_DIR / "tolerance_matches.csv"
CONFIDENCE_RESULTS_PATH = ML_DIR / "confidence_predictions.csv"
LLM_RESULTS_PATH = RESULTS_DIR / "llm_matches.csv"
OUTPUT_PATH = RESULTS_DIR / "reconciliation_results.csv"
CONFIG_OUTPUT_PATH = RESULTS_DIR / "reconciliation_config.json"


def normalize_bank_ids(value):
    if pd.isna(value):
        return []
    return [x.strip() for x in str(value).split("|") if x.strip()]


def load_csv(path):
    if not Path(path).exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_exact_matches():
    exact = load_csv(EXACT_RESULTS_PATH)
    if exact.empty:
        return []

    required = {"settlement_id", "bank_transaction_id"}
    missing = required - set(exact.columns)
    if missing:
        raise ValueError(f"exact_matches.csv is missing columns: {sorted(missing)}")

    results = []
    for _, row in exact.iterrows():
        bank_ids = normalize_bank_ids(row["bank_transaction_id"])
        for bank_id in bank_ids:
            res_dict = {
                "settlement_id": str(row["settlement_id"]),
                "bank_transaction_id": bank_id,
                "stage": "exact",
                "decision": "match",
                "confidence": 1.0,
                "reason": "Exact deterministic match.",
                "status": "matched",
            }
            if "amount" in row and pd.notna(row["amount"]):
                res_dict["amount"] = row["amount"]
            if "date" in row and pd.notna(row["date"]):
                res_dict["date"] = row["date"]
            results.append(res_dict)

    return results


def load_tolerance_matches(already_matched):
    tolerance = load_csv(TOLERANCE_RESULTS_PATH)
    if tolerance.empty:
        return []

    required = {"settlement_id", "bank_transaction_id"}
    missing = required - set(tolerance.columns)
    if missing:
        raise ValueError(f"tolerance_matches.csv is missing columns: {sorted(missing)}")

    results = []
    for _, row in tolerance.iterrows():
        settlement_id = str(row["settlement_id"])
        if settlement_id in already_matched:
            continue

        bank_ids = normalize_bank_ids(row["bank_transaction_id"])
        for bank_id in bank_ids:
            results.append({
                "settlement_id": settlement_id,
                "bank_transaction_id": bank_id,
                "stage": "tolerance",
                "decision": "match",
                "confidence": 1.0,
                "reason": "Tolerance-stage match.",
                "status": "matched",
            })
        already_matched.add(settlement_id)

    return results


def load_ml_candidates(already_matched):
    predictions = load_csv(CONFIDENCE_RESULTS_PATH)
    if predictions.empty:
        return []

    required = {"settlement_id", "bank_transaction_id", "confidence"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"confidence_predictions.csv is missing columns: {sorted(missing)}")

    active_settlements = load_csv(SETTLEMENTS_PATH)
    if not active_settlements.empty and "settlement_id" in active_settlements.columns:
        valid_ids = set(active_settlements["settlement_id"].astype(str))
        predictions = predictions[predictions["settlement_id"].astype(str).isin(valid_ids)]

    candidates = []
    for _, row in predictions.iterrows():
        settlement_id = str(row["settlement_id"])
        if settlement_id in already_matched:
            continue

        confidence = float(row["confidence"])
        margin = float(row.get("margin", 1.0)) if pd.notna(row.get("margin")) else 1.0

        candidates.append({
            "settlement_id": settlement_id,
            "bank_transaction_id": str(row["bank_transaction_id"]),
            "confidence": confidence,
            "margin": margin,
        })

    return candidates


def load_llm_results():
    if not LLM_RESULTS_PATH.exists():
        return pd.DataFrame(columns=[
            "settlement_id", "bank_transaction_id", "ml_confidence",
            "llm_decision", "llm_confidence", "reason", "fallback_triggered"
        ])
    return load_csv(LLM_RESULTS_PATH)


def build_llm_lookup(llm_results):
    lookup = {}
    for _, row in llm_results.iterrows():
        key = (str(row["settlement_id"]), str(row["bank_transaction_id"]))
        lookup[key] = row
    return lookup


def reconcile(cfg: Optional[MatchingConfig] = None):
    if cfg is None:
        cfg = MatchingConfig.load_with_env_overrides()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg.save(CONFIG_OUTPUT_PATH)

    final_results = []
    matched_settlements = set()

    # STAGE 1 — EXACT
    exact_results = load_exact_matches()
    final_results.extend(exact_results)
    for result in exact_results:
        matched_settlements.add(result["settlement_id"])

    # STAGE 2 — TOLERANCE
    tolerance_results = load_tolerance_matches(matched_settlements)
    final_results.extend(tolerance_results)

    # STAGE 3 — ML & MARGIN GATE (T4.4)
    ml_candidates = load_ml_candidates(matched_settlements)
    llm_results = load_llm_results()
    llm_lookup = build_llm_lookup(llm_results)

    for candidate in ml_candidates:
        settlement_id = candidate["settlement_id"]
        bank_id = candidate["bank_transaction_id"]
        ml_confidence = candidate["confidence"]
        margin = candidate["margin"]

        if settlement_id in matched_settlements:
            continue

        # Margin-Aware Decision Gate (T4.4)
        has_high_confidence = (ml_confidence >= cfg.ml_match_threshold)
        has_sufficient_margin = (margin >= cfg.minimum_score_margin)

        if has_high_confidence and has_sufficient_margin:
            final_results.append({
                "settlement_id": settlement_id,
                "bank_transaction_id": bank_id,
                "stage": "ml",
                "decision": "match",
                "confidence": ml_confidence,
                "reason": "High-confidence ML match with sufficient score margin.",
                "status": "matched",
            })
            matched_settlements.add(settlement_id)
            continue

        # Low-margin or lower confidence -> Route to LLM review
        if ml_confidence >= cfg.ml_review_threshold:
            key = (settlement_id, bank_id)
            llm = llm_lookup.get(key)

            reason_str = (
                f"Candidate cleared score threshold ({ml_confidence:.2f} >= {cfg.ml_match_threshold}) but failed margin check ({margin:.4f} < {cfg.minimum_score_margin})."
                if has_high_confidence and not has_sufficient_margin
                else "Candidate falls inside LLM review band."
            )

            if llm is None:
                final_results.append({
                    "settlement_id": settlement_id,
                    "bank_transaction_id": bank_id,
                    "stage": "llm",
                    "decision": "review",
                    "confidence": ml_confidence,
                    "reason": reason_str,
                    "status": "manual_review",
                })
                continue

            llm_decision = str(llm.get("llm_decision", "review"))
            llm_confidence = float(llm.get("llm_confidence", 0.50))
            llm_reason = str(llm.get("reason", "LLM evaluation."))

            if llm_decision == "match" and llm_confidence >= cfg.llm_match_threshold:
                final_results.append({
                    "settlement_id": settlement_id,
                    "bank_transaction_id": bank_id,
                    "stage": "llm",
                    "decision": "match",
                    "confidence": llm_confidence,
                    "reason": f"LLM confirmed match: {llm_reason}",
                    "status": "matched",
                })
                matched_settlements.add(settlement_id)
            else:
                final_results.append({
                    "settlement_id": settlement_id,
                    "bank_transaction_id": bank_id,
                    "stage": "llm",
                    "decision": "review",
                    "confidence": llm_confidence,
                    "reason": f"LLM review required: {llm_reason}",
                    "status": "manual_review",
                })

    # STAGE 4 — UNMATCHED ORDERS SCAN (Track 100% of primary order book)
    orders_path = GENERATED_DIR / "internal_orders.csv"
    if orders_path.exists():
        try:
            orders_df = pd.read_csv(orders_path)
            if "order_id" in orders_df.columns:
                for _, orow in orders_df.iterrows():
                    oid = str(orow["order_id"]).strip()
                    if oid and oid not in matched_settlements:
                        final_results.append({
                            "settlement_id": oid,
                            "bank_transaction_id": "UNMATCHED",
                            "stage": "unmatched",
                            "decision": "unmatched",
                            "confidence": 0.0,
                            "reason": "Unreconciled order — missing from bank statement.",
                            "status": "unmatched",
                        })
                        matched_settlements.add(oid)
        except Exception:
            pass

    res_df = pd.DataFrame(final_results) if final_results else pd.DataFrame(columns=[
        "settlement_id", "bank_transaction_id", "stage", "decision", "confidence", "reason", "status"
    ])
    res_df.to_csv(OUTPUT_PATH, index=False)

    print("=" * 60)
    print("LEDGER - RECONCILIATION COMPLETE (v2 Extended)")
    print("=" * 60)
    print(f"Total results: {len(res_df)}")
    print(f"Config saved : {CONFIG_OUTPUT_PATH}")
    print(f"Results saved: {OUTPUT_PATH}")
    return res_df


if __name__ == "__main__":
    reconcile()