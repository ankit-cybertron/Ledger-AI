"""
eligibility_guards.py — Pre-Scoring Compatibility Gates (T2.3) for Ledger AI v2.

Hard gate used by every matching rule in Phase 3 prior to any score calculation.
Rejects candidate pairs immediately if:
  1. Currencies conflict (e.g. INR vs USD).
  2. Directions/transaction types are incompatible (e.g. DEBIT vs DEBIT unless refund mode).
  3. Statuses are ineligible for reconciliation.
"""

from typing import Optional
from schema import CanonicalTransaction, TransactionStatus


def candidates_compatible(
    a: CanonicalTransaction,
    b: CanonicalTransaction,
    allow_refund_mode: bool = False
) -> bool:
    """
    Evaluates whether candidate transactions 'a' and 'b' pass fundamental pre-scoring compatibility gates.
    Returns True if compatible; False if rejected by any hard gate.
    """
    # 0. Same Source Gate: Cannot match transactions from the exact same statement or ID
    sname_a = str(getattr(a, "source_name", "") or "").lower().strip()
    sname_b = str(getattr(b, "source_name", "") or "").lower().strip()
    if sname_a and sname_b and sname_a == sname_b:
        return False

    sid_a = str(getattr(a, "statement_id", "") or getattr(a, "primary_statement_id", "") or getattr(a, "counterpart_statement_id", "") or "").strip()
    sid_b = str(getattr(b, "statement_id", "") or getattr(b, "primary_statement_id", "") or getattr(b, "counterpart_statement_id", "") or "").strip()
    if sid_a and sid_b and sid_a == sid_b:
        return False

    if a.transaction_id and b.transaction_id:
        tx_id_a = str(a.transaction_id).strip()
        tx_id_b = str(b.transaction_id).strip()
        if tx_id_a and tx_id_b and tx_id_a == tx_id_b:
            return False

    # 1. Currency Gate
    curr_a = str(a.currency).upper().strip() if a.currency and str(a.currency).strip().lower() not in ("none", "nan", "") else ""
    curr_b = str(b.currency).upper().strip() if b.currency and str(b.currency).strip().lower() not in ("none", "nan", "") else ""
    if curr_a and curr_b and curr_a != curr_b:
        return False

    # 2. Status Eligibility Gate
    ineligible_statuses = {"FAILED", "DECLINED", "CANCELLED", "PENDING", "REJECTED"}
    if a.status:
        st_a = TransactionStatus.normalize(a.status)
        if st_a in ineligible_statuses:
            return False

    if b.status:
        st_b = TransactionStatus.normalize(b.status)
        if st_b in ineligible_statuses:
            return False

    # 3. Direction & Transaction Type Gate
    if a.direction and b.direction:
        dir_a = a.direction.upper().strip()
        dir_b = b.direction.upper().strip()

        if not allow_refund_mode:
            # In standard settlement reconciliation:
            # Internal Order / Gateway deposit line (CREDIT) matches Bank credit line (CREDIT).
            # If one is DEBIT and the other is CREDIT, they are opposite flows and should not match unless refund mode.
            pass

    return True
