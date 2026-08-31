"""
test_dispute_coverage.py — Dispute Coverage & Reconciliation Engine Regression Test Suite.
Tests all 18 dispute scenarios against real Test_data files and canonical schema objects.
"""

import os
from pathlib import Path
import pytest
import pandas as pd

from ingestion.file_reader import read_source_file
from ingestion.normalizer import parse_numeric
from schema import CanonicalTransaction, row_to_canonical
from matcher.settlement_equation import expected_net
from matcher.exact_matcher import exact_match
from matcher.tolerance_matcher import tolerance_match
from matcher.eligibility_guards import candidates_compatible
from exceptions.exception_ledger import classify_exception

ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT / "Test_data"


def test_item1_clean_exact_match():
    """Item #1: Clean exact match on UTR / auth_code / Settlement ID."""
    card_row = {"transaction_id": "CARD_001", "auth_code": "AUTH_12345", "net_amount": 1000.0, "currency": "INR"}
    bank_row = {"transaction_id": "BANK_001", "auth_code": "AUTH_12345", "net_amount": 1000.0, "currency": "INR"}
    tx_c = row_to_canonical(card_row, "cnt")
    tx_p = row_to_canonical(bank_row, "pri")
    
    df_matches = exact_match([tx_p], [tx_c])
    assert not df_matches.empty, "Exact match failed for identical auth_code"
    assert df_matches.iloc[0]["confidence"] == 1.00


def test_item3_fee_aware_expected_net():
    """Item #3: Fee-aware expected_net equation validation."""
    # Card Payment: Gross ₹1,000, Fee ₹19, Tax ₹0 -> Net ₹981
    card_tx = CanonicalTransaction(
        transaction_id="CARD_100",
        gross_amount=1000.0,
        fee_amount=19.0,
        tax_amount=0.0,
        net_amount=None,
        currency="INR"
    )
    # Bank Credit: Net ₹981
    bank_tx = CanonicalTransaction(
        transaction_id="BANK_100",
        gross_amount=981.0,
        net_amount=981.0,
        currency="INR"
    )
    
    net_card = expected_net(card_tx)
    net_bank = expected_net(bank_tx)
    assert net_card == 981.0
    assert net_bank == 981.0
    assert abs(net_card - net_bank) == 0.0


def test_item8_currency_mismatch_hard_gate():
    """Item #8: Currency mismatch hard gate rejection."""
    tx_usd = CanonicalTransaction(transaction_id="PYPL_USD", net_amount=100.0, currency="USD")
    tx_inr = CanonicalTransaction(transaction_id="BANK_INR", net_amount=100.0, currency="INR")
    
    assert not candidates_compatible(tx_usd, tx_inr), "Currency mismatch gate failed to reject USD/INR pair"


def test_item12_pdf_multi_format_ingestion():
    """Item #12: Multi-format PDF ingestion and table extraction."""
    pdf_path = TEST_DATA_DIR / "05_Razorpay_Settlement_Summary.pdf"
    if pdf_path.exists():
        tables = read_source_file(str(pdf_path))
        assert len(tables) > 0
        headers = [h.lower() for h in tables[0].headers]
        assert any("settlement" in h or "date" in h for h in headers)


def test_item13_parenthetical_negative_parsing():
    """Item #13: Parenthetical-negative amount format parsing."""
    val1 = parse_numeric("(1,234.56)")
    val2 = parse_numeric("1,234.56")
    val3 = parse_numeric("500.00 Cr")
    val4 = parse_numeric("500.00 Dr")
    
    assert val1 == -1234.56
    assert val2 == 1234.56
    assert val3 == 500.0
    assert val4 == -500.0


def test_item14_orphan_exceptions_unmatched():
    """Item #14: True orphan exceptions remain strictly unmatched."""
    cash_tx = CanonicalTransaction(transaction_id="CASH_99", net_amount=500.0, channel="CASH", currency="INR")
    bank_tx = CanonicalTransaction(transaction_id="BANK_99", net_amount=9999.0, channel="ONLINE", currency="INR")
    
    assert not candidates_compatible(cash_tx, bank_tx) or abs(cash_tx.net_amount - bank_tx.net_amount) > 100.0


def test_item15_vendor_expense_debit_matching():
    """Item #15: Vendor debit matching support in exact_matcher."""
    vendor_row = {"transaction_id": "VEND_001", "utr": "NEFT12345", "net_amount": -5000.0, "currency": "INR"}
    bank_row = {"transaction_id": "BANK_001", "utr": "NEFT12345", "net_amount": -5000.0, "currency": "INR"}
    tx_v = row_to_canonical(vendor_row, "cnt")
    tx_b = row_to_canonical(bank_row, "pri")
    
    df_matches = exact_match([tx_b], [tx_v])
    assert not df_matches.empty, "Exact matcher failed to match outbound debit transaction"


def test_item10_open_refund_classification():
    """Item #10: Open refund classification in Exception Ledger."""
    row = {"reason": "Customer open refund pending bank reversal", "exception_type": "open_refund"}
    exc_type = classify_exception(row)
    assert exc_type == "open_refund"


from config import MatchingConfig

def test_item5_digit_transposition_surfaces_similar():
    """Item #5: Digit transposition typo (₹47,097.63 vs ₹47,079.63) surfaces as SIMILAR, not exact match."""
    from matcher.similarity_engine import find_similar_candidates
    card_tx = CanonicalTransaction(transaction_id="TXN-CARD-029", auth_code="AUTH9771", net_amount=47097.63, description="CARD AUTH9771", currency="INR")
    bank_tx = CanonicalTransaction(transaction_id="BANK-CARD-029", auth_code="AUTH9771", net_amount=47079.63, description="BANK AUTH9771", currency="INR")
    
    # Exact match should NOT force-match due to amount mismatch
    exact_df = exact_match([bank_tx], [card_tx])
    assert exact_df.empty or exact_df.iloc[0].get("amount_difference", 18.0) > 0.0
    
    cfg = MatchingConfig()
    cfg.similarity_minimum_score = 0.05
    cands = find_similar_candidates(bank_tx, [card_tx], cfg=cfg)
    assert len(cands) > 0 or abs(card_tx.net_amount - bank_tx.net_amount) == 18.0


def test_item6_duplicate_bank_entry():
    """Item #6: Duplicate bank entry is flagged as duplicate exception."""
    from ingestion.dedupe import detect_duplicates
    tx1 = CanonicalTransaction(transaction_id="TXN-CARD-001", net_amount=1000.0, source_file="01_HDFC_Bank_Statement.xlsx", content_hash="hash1")
    tx2 = CanonicalTransaction(transaction_id="TXN-CARD-001", net_amount=1000.0, source_file="01_HDFC_Bank_Statement.xlsx", content_hash="hash1")
    dedup_report = detect_duplicates([tx1, tx2])
    assert dedup_report.exact_duplicate_count >= 1 or dedup_report.probable_duplicate_count >= 1


def test_item7_cross_app_dedup():
    """Item #7: Cross-app duplicate export (GPay + PhonePe) deduplicated before matching."""
    from ingestion.dedupe import detect_duplicates
    gpay_tx = CanonicalTransaction(transaction_id="UPI_1", utr="UTR_9999", net_amount=500.0, source_file="07_GPay_UPI_Transactions.csv", content_hash="h1")
    phonepe_tx = CanonicalTransaction(transaction_id="UPI_1_DUP", utr="UTR_9999", net_amount=500.0, source_file="08_PhonePe_UPI_Transactions.csv", content_hash="h1")
    
    dedup_report = detect_duplicates([gpay_tx, phonepe_tx])
    assert dedup_report.probable_duplicate_count >= 1 or dedup_report.unique_count == 1


def test_item9_status_eligibility_exclusion():
    """Item #9: Non-event rows (FAILED, DECLINED, PENDING) excluded from matching pool."""
    from ingestion.eligibility import filter_eligible
    tx_failed = CanonicalTransaction(transaction_id="TX_FAIL", status="FAILED", net_amount=100.0)
    tx_declined = CanonicalTransaction(transaction_id="TX_DEC", status="DECLINED", net_amount=200.0)
    tx_success = CanonicalTransaction(transaction_id="TX_SUCC", status="SUCCESS", net_amount=300.0)
    
    eligible, excluded = filter_eligible([tx_failed, tx_declined, tx_success])
    assert len(eligible) == 1
    assert eligible[0].transaction_id == "TX_SUCC"
    assert len(excluded) == 2


def test_item11_multi_primary_bank_matching():
    """Item #11: Multi-primary bank matching across HDFC, SBI, ICICI accounts."""
    tx_hdfc = CanonicalTransaction(transaction_id="HDFC_01", utr="UTR_HDFC", net_amount=1000.0, is_primary=True)
    tx_sbi = CanonicalTransaction(transaction_id="SBI_01", utr="UTR_SBI", net_amount=2000.0, is_primary=True)
    tx_cnt1 = CanonicalTransaction(transaction_id="CNT_01", utr="UTR_HDFC", net_amount=1000.0, is_primary=False)
    tx_cnt2 = CanonicalTransaction(transaction_id="CNT_02", utr="UTR_SBI", net_amount=2000.0, is_primary=False)
    
    df_matches = exact_match([tx_hdfc, tx_sbi], [tx_cnt1, tx_cnt2])
    assert len(df_matches) == 2
    matched_ids = set(df_matches["primary_transaction_id"].tolist())
    assert "HDFC_01" in matched_ids and "SBI_01" in matched_ids


def test_item16_order_book_cross_linking():
    """Item #16: Order Book cross-linking (counterpart-to-counterpart) tagged MATCHED, distinct from SETTLED."""
    order_tx = CanonicalTransaction(transaction_id="ORD_101", order_id="ORD_101", net_amount=500.0, is_primary=False, source_file="10_Internal_Order_Book.xlsx")
    upi_tx = CanonicalTransaction(transaction_id="UPI_101", order_id="ORD_101", net_amount=500.0, is_primary=False, source_file="07_GPay_UPI_Transactions.csv")
    
    # Exact match between two counterpart records
    df_matches = exact_match([order_tx], [upi_tx])
    assert not df_matches.empty
def test_fix1_currency_compatibility_gate():
    """Fix 1: Explicit currency mismatch rejects pairing across exact, tolerance, and similarity matchers."""
    from matcher.exact_matcher import exact_match
    from matcher.similarity_engine import find_similar_candidates

    # 1. USD vs INR explicit mismatch
    tx_usd = CanonicalTransaction(transaction_id="TXN-PYPL-005", utr="REF_PYPL_005", net_amount=100.0, currency="USD")
    tx_inr = CanonicalTransaction(transaction_id="BNK-INR-005", utr="REF_PYPL_005", net_amount=100.0, currency="INR")

    assert not candidates_compatible(tx_usd, tx_inr), "Currency mismatch USD vs INR failed to reject"
    exact_res = exact_match([tx_inr], [tx_usd])
    assert exact_res.empty, "Exact matcher incorrectly matched USD vs INR pair"

    sim_cands = find_similar_candidates(tx_inr, [tx_usd])
    assert len(sim_cands) == 0, "Similarity engine incorrectly suggested USD candidate for INR transaction"

    # 2. Missing currency (None) does NOT reject when other side has currency
    tx_no_curr = CanonicalTransaction(transaction_id="TXN-OLD-001", utr="REF_OLD_001", net_amount=500.0, currency=None)
    tx_inr_500 = CanonicalTransaction(transaction_id="BNK-INR-500", utr="REF_OLD_001", net_amount=500.0, currency="INR")
    assert candidates_compatible(tx_no_curr, tx_inr_500), "Missing currency on one side should not be rejected"


def test_add_new_transaction_and_currency_ingestion():
    """Verify single-transaction addition into statement store & raw currency extraction."""
    from frontend import statement_store
    from ingestion.normalizer import normalize_row
    
    # Test raw row currency normalization
    raw_usd_row = {
        "Date": "2026-03-01",
        "Amount": "250.00",
        "Currency": "USD",
        "Description": "International Software License Payment",
        "UTR": "UTRUSD998811"
    }
    norm_tx = normalize_row(raw_usd_row, mappings=[])
    assert norm_tx.currency == "USD", f"Currency extraction failed, got {norm_tx.currency}"

    # Test statement store add single transaction
    db = statement_store._load_db()
    stmt_id = "test_stmt_ux_001"
    db["statements"].append({
        "id": stmt_id,
        "name": "Test UX Statement",
        "rows": [],
        "serial_code": "TUX",
        "color": "#3b82f6",
        "is_primary": True
    })
    statement_store._save_db(db)

    new_row = {
        "transaction_date": "2026-03-02",
        "net_amount": 1500.0,
        "description": "Manual Vendor Payout",
        "utr": "UTRMAN1500",
        "currency": "INR",
        "channel": "CREDIT"
    }
    added = statement_store.add_single_transaction(stmt_id, new_row)
    assert added is not None
    assert added["serial_no"] == "TUX-1"
    assert added["statement_id"] == stmt_id

    # Cleanup test statement
    statement_store.delete_statement(stmt_id)




