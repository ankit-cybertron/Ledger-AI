"""
feature_schema.py — Canonical ML Feature Column Schema (T4.1) for Ledger AI v2.

Defines the single source of truth for all feature column names used across
training, prediction, evaluation, and feedback loop ML pipelines.
"""

from typing import List

FEATURE_COLUMNS: List[str] = [
    "settlement_amount",
    "bank_amount",
    "amount_difference",
    "amount_difference_pct",
    "relative_amount_difference",
    "date_difference_days",
    "utr_match",
    "utr_missing",
    "utr_similarity",
    "rrn_exact",
    "rrn_similarity",
    "order_id_exact",
    "settlement_id_exact",
    "gateway_ref_exact",
    "auth_code_exact",
    "customer_name_similarity",
    "vpa_similarity",
    "narration_similarity",
    "currency_match",
    "same_direction",
    "status_compatible",
    "candidate_count",
    "split_candidate",
    "fee_adjusted_difference",
    "expected_settlement_date_gap",
    "duplicate_risk",
    "is_digit_transposition",
]
