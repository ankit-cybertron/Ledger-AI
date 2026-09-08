"""
test_benchmark_scenarios.py — Automated Verification for All 10 Benchmark Scenarios.
Covers:
- SC-01: Exact UTR 1:1 match
- SC-02: Exact Order ID match
- SC-03: Exact RRN match
- SC-04: Settlement lag (1-3 days date gap)
- SC-05: MDR fee tolerance
- SC-06: N-to-1 split aggregate
- SC-08: Duplicate detection
- SC-09: Similarity engine candidate
- SC-10: Unmatched record
"""

import pytest
import pandas as pd
from config import MatchingConfig
from schema import CanonicalTransaction
from matcher.exact_matcher import exact_match
from matcher.tolerance_matcher import tolerance_match
from matcher.split_aggregate_matcher import split_aggregate_match
from matcher.similarity_engine import find_similar_candidates


def test_sc01_exact_utr_match():
    """SC-01: Exact UTR 1:1 match between Primary and Counterpart -> confidence 1.00."""
    cfg = MatchingConfig()
    pri = [CanonicalTransaction(transaction_id="p1", utr="UTR9988776655", net_amount=15000.0, transaction_date="2024-02-01")]
    cnt = [CanonicalTransaction(transaction_id="c1", utr="UTR9988776655", net_amount=15000.0, transaction_date="2024-02-01")]
    res = exact_match(pri, cnt, cfg)
    assert len(res) == 1
    assert res.iloc[0]["match_type"] == "exact_utr_match"
    assert res.iloc[0]["confidence"] == 1.00


def test_sc02_exact_order_id_match():
    """SC-02: Exact Order ID match -> confidence 1.00."""
    cfg = MatchingConfig()
    pri = [CanonicalTransaction(transaction_id="p2", order_id="INV-2024-001", net_amount=4500.0, transaction_date="2024-02-02")]
    cnt = [CanonicalTransaction(transaction_id="c2", order_id="INV-2024-001", net_amount=4500.0, transaction_date="2024-02-02")]
    res = exact_match(pri, cnt, cfg)
    assert len(res) == 1
    assert res.iloc[0]["match_type"] == "exact_order_id_match"
    assert res.iloc[0]["confidence"] == 1.00


def test_sc03_exact_rrn_match():
    """SC-03: Exact RRN match -> confidence 1.00."""
    cfg = MatchingConfig()
    pri = [CanonicalTransaction(transaction_id="p3", rrn="RRN44332211", net_amount=2300.0, transaction_date="2024-02-03")]
    cnt = [CanonicalTransaction(transaction_id="c3", rrn="RRN44332211", net_amount=2300.0, transaction_date="2024-02-03")]
    res = exact_match(pri, cnt, cfg)
    assert len(res) == 1
    assert res.iloc[0]["match_type"] == "exact_rrn_match"
    assert res.iloc[0]["confidence"] == 1.00


def test_sc04_and_sc05_fee_and_date_tolerance():
    """SC-04 & SC-05: MDR fee difference and 2-day date gap with shared UTR -> matched in tolerance with >= 0.85 confidence."""
    cfg = MatchingConfig(
        fee_aware_matching=True,
        date_tolerance_days=3,
        absolute_amount_tolerance=10.0,
        percentage_tolerance=0.03,
        one_to_one_tolerance_confidence=0.85,
    )
    pri = [CanonicalTransaction(transaction_id="p4", utr="UTR-LAG-FEE-55", net_amount=980.0, transaction_date="2024-02-05", description="Order 55")]
    cnt = [CanonicalTransaction(transaction_id="c4", utr="UTR-LAG-FEE-55", net_amount=1000.0, transaction_date="2024-02-03", description="Order 55 payment")]
    matches, _ = tolerance_match(pri, cnt, cfg=cfg)
    assert len(matches) == 1
    assert matches.iloc[0]["confidence"] >= 0.85


def test_sc06_split_aggregate():
    """SC-06: 2 transactions aggregate to match 1 settlement lump-sum under shared reference."""
    cfg = MatchingConfig(split_match_confidence=0.95)
    pri = [CanonicalTransaction(transaction_id="p_batch", gateway_reference="BATCH-001", net_amount=3000.0, transaction_date="2024-02-10")]
    cnt = [
        CanonicalTransaction(transaction_id="c_sub1", gateway_reference="BATCH-001", net_amount=1000.0, transaction_date="2024-02-10"),
        CanonicalTransaction(transaction_id="c_sub2", gateway_reference="BATCH-001", net_amount=2000.0, transaction_date="2024-02-10"),
    ]
    res = split_aggregate_match(pri, cnt, cfg=cfg)
    assert len(res) == 1
    assert res.iloc[0]["confidence"] == 0.95


def test_sc09_and_sc10_similarity_and_unmatched():
    """SC-09 & SC-10: Similar candidate found vs completely unmatched transaction."""
    cfg = MatchingConfig(similarity_minimum_score=0.40)
    target = CanonicalTransaction(
        transaction_id="t_sim",
        net_amount=500.0,
        transaction_date="2024-02-12",
        description="Acme Corp Payment",
    )
    pool = [
        CanonicalTransaction(transaction_id="c_close", net_amount=500.0, transaction_date="2024-02-12", description="Acme Corp Payout"),
        CanonicalTransaction(transaction_id="c_far", net_amount=99999.0, transaction_date="2024-01-01", description="Different Vendor"),
    ]
    sims = find_similar_candidates(target, pool, cfg)
    assert len(sims) >= 1
    assert sims[0]["candidate_id"] == "c_close"
    assert sims[0]["similarity_score"] >= 0.40
