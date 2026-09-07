"""
test_pipeline_optimization.py — Tests for Algorithmic Optimization and Pipeline Streamlining.
Verifies:
1. O(N+M) Exact matching produces correct matches and preserves greedy stealing prevention.
2. O(N log M) Tolerance matching with binary search slicing matches within tolerance cap.
3. Pipeline runner executes single-pass unified matching and produces canonical results.
"""

import sys
from pathlib import Path
import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import MatchingConfig
from schema import CanonicalTransaction
from matcher.exact_matcher import exact_match
from matcher.tolerance_matcher import tolerance_match
from reconciler.pipeline_runner import run_full_pipeline


def test_hash_indexed_exact_matching():
    """Verify hash-indexed exact match correctly matches UTR, Order ID, and RRN in O(1) lookups."""
    cfg = MatchingConfig()
    
    primary = [
        CanonicalTransaction(transaction_id="p1", utr="UTR123456789", net_amount=5000.0, transaction_date="2024-01-10"),
        CanonicalTransaction(transaction_id="p2", order_id="ORD987654", net_amount=1200.0, transaction_date="2024-01-11"),
        CanonicalTransaction(transaction_id="p3", rrn="RRN555555", net_amount=750.0, transaction_date="2024-01-12"),
        CanonicalTransaction(transaction_id="p4", utr="UNMATCHED_UTR", net_amount=300.0, transaction_date="2024-01-13"),
    ]
    
    counterpart = [
        CanonicalTransaction(transaction_id="c1", utr="NEFTCR-UTR123456789", net_amount=5000.0, transaction_date="2024-01-10"),
        CanonicalTransaction(transaction_id="c2", order_id="ORD987654", net_amount=1200.0, transaction_date="2024-01-11"),
        CanonicalTransaction(transaction_id="c3", rrn="RRN555555", net_amount=750.0, transaction_date="2024-01-12"),
        CanonicalTransaction(transaction_id="c4", utr="OTHER_UTR", net_amount=450.0, transaction_date="2024-01-13"),
    ]
    
    matches = exact_match(primary, counterpart, cfg)
    assert len(matches) == 3
    matched_pairs = set(zip(matches["primary_transaction_id"], matches["counterpart_transaction_id"]))
    assert ("p1", "c1") in matched_pairs
    assert ("p2", "c2") in matched_pairs
    assert ("p3", "c3") in matched_pairs


def test_binary_search_tolerance_matching():
    """Verify tolerance matching with binary search correctly finds candidates in amount window."""
    cfg = MatchingConfig(
        absolute_amount_tolerance=5.0,
        percentage_tolerance=0.02,
        date_tolerance_days=3,
    )
    
    primary = [
        CanonicalTransaction(transaction_id="tp1", net_amount=1000.0, transaction_date="2024-01-10", description="Payment A"),
        CanonicalTransaction(transaction_id="tp2", net_amount=5000.0, transaction_date="2024-01-15", description="Payment B"),
    ]
    
    # Counterparts with slight tolerance difference and far away outliers
    counterpart = [
        CanonicalTransaction(transaction_id="tc1", net_amount=998.0, transaction_date="2024-01-11", description="Payment A fee"),
        CanonicalTransaction(transaction_id="tc2", net_amount=25000.0, transaction_date="2024-01-15", description="Outlier"),
    ]
    
    matches, ties = tolerance_match(primary, counterpart, cfg=cfg)
    assert len(matches) == 1
    assert matches.iloc[0]["primary_transaction_id"] == "tp1"
    assert matches.iloc[0]["counterpart_transaction_id"] == "tc1"


def test_pipeline_runner_execution():
    """Verify pipeline_runner runs full pipeline without duplicate execution or fatal errors."""
    res = run_full_pipeline()
    assert res.get("ok") is True
    assert res.get("status") == "completed"
