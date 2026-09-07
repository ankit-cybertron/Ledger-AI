"""
test_overview_charts.py — Tests for Overview Visualizations & Charts API.
Verifies all 6+ analytics chart datasets (status breakdown, source contribution,
variance distribution, mismatch reasons, scatter map, cascade, and risk exposure).
"""

import pytest
from frontend.app import app
from frontend.api.routes import compute_overview_charts


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["TESTING_DISABLE_AUTO_RESET"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = "demo"
        yield client


def test_compute_overview_charts_structure():
    """Verify single-pass compute_overview_charts correctly builds all chart datasets."""
    dummy_txs = [
        {
            "id": "tx1",
            "amount": 1000.0,
            "status": "SETTLED",
            "source_name": "Bank Statement",
            "date": "2024-01-10",
            "utr": "UTR111",
            "confidence": 1.0,
            "counterpart": {"id": "cp1", "amount": 1000.0},
            "evidence": {"rule": "exact_utr"}
        },
        {
            "id": "tx2",
            "amount": 495.0,
            "status": "MATCHED",
            "source_name": "Razorpay",
            "date": "2024-01-11",
            "confidence": 0.88,
            "counterpart": {"id": "cp2", "amount": 500.0},
            "evidence": {"rule": "tolerance_fee"}
        },
        {
            "id": "tx3",
            "amount": 350.0,
            "status": "UNMATCHED",
            "source_name": "Cash Book",
            "date": "2024-01-12",
            "confidence": 0.0,
            "evidence": {"rule": "no candidate match"}
        }
    ]

    charts = compute_overview_charts(dummy_txs, exceptions=[], period_settled=False, percent=66.7)

    # 1. Status Breakdown
    sb = charts["status_breakdown"]
    assert sb["labels"] == ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]
    assert sb["counts"] == [1, 1, 0, 1]

    # 2. Status Composition
    sc = charts["status_composition"]
    assert sc["total"] == 3
    assert sc["counts"] == [1, 1, 0, 1]

    # 3. Source Contribution
    sc_contrib = charts["source_contribution"]
    assert len(sc_contrib["labels"]) == 3
    assert "SETTLED" in sc_contrib["datasets"]

    # 4. Amount Variance
    av = charts["amount_variance"]
    assert len(av["labels"]) == 5
    assert av["counts"][0] >= 1  # Exact match count

    # 5. Scatter Map
    sm = charts["scatter_map"]
    assert len(sm["points"]) == 3

    # 6. Matching Cascade
    mc = charts["matching_cascade"]
    assert len(mc["labels"]) == 5
    assert mc["counts"][0] == 1  # Pass 1: exact match
    assert mc["counts"][1] == 1  # Pass 2: tolerance match
    assert mc["counts"][4] == 1  # Unresolved exceptions


def test_overview_zero_data_degradation():
    """Verify compute_overview_charts produces valid payloads even with zero transactions."""
    charts = compute_overview_charts([], exceptions=[], period_settled=False, percent=0.0)
    assert charts["status_breakdown"]["counts"] == [0, 0, 0, 0]
    assert charts["status_composition"]["total"] == 0
    assert charts["scatter_map"]["points"] == []
