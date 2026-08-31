"""
tests/test_feature_flags.py — Feature Flags & Transaction Type Taxonomy Tests.
"""

from frontend.api.routes import compute_transaction_feature_flags


def test_international_txn_flag():
    txn = {"currency": "USD", "description": "Software Subscription", "amount": 100.0}
    flags, primary_type = compute_transaction_feature_flags(txn)
    assert "International Txn" in flags
    assert primary_type == "International Txn"


def test_internal_transfer_flag():
    txn = {
        "currency": "INR",
        "description": "SELF TRANSFER TO ICICI BANK",
        "source_name": "SBI Bank",
        "source_type": "bank",
        "amount": 50000.0,
        "is_primary": True
    }
    counterpart = {
        "source_name": "ICICI Bank",
        "source_type": "bank",
        "is_primary": True
    }
    flags, primary_type = compute_transaction_feature_flags(txn, counterpart)
    assert "Internal Transfer" in flags
    assert primary_type == "Internal Transfer"


def test_manual_override_flag():
    txn = {
        "currency": "INR",
        "description": "Vendor Payment",
        "status": "manual",
        "evidence": {"rule": "Manual reviewer approval"},
        "amount": 1200.0
    }
    flags, primary_type = compute_transaction_feature_flags(txn)
    assert "Manual Override" in flags
    assert primary_type == "Manual Override"


def test_exact_utr_match_flag():
    txn = {
        "currency": "INR",
        "description": "Customer Payment",
        "utr": "UTR99887766",
        "status": "settled",
        "evidence": {"rule": "Exact UTR Match (Pass 1)"},
        "amount": 4500.0
    }
    flags, primary_type = compute_transaction_feature_flags(txn)
    assert "Exact UTR Match" in flags


def test_unmatched_utr_flag():
    txn = {
        "currency": "INR",
        "description": "Unknown Deposit",
        "utr": None,
        "status": "unmatched",
        "amount": 300.0
    }
    flags, primary_type = compute_transaction_feature_flags(txn)
    assert "Unmatched UTR" in flags
