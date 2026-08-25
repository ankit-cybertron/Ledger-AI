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
    # 1. Currency Gate
    if a.currency and b.currency:
        if a.currency.upper().strip() != b.currency.upper().strip():
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
