"""
settlement_equation.py — Expected Net Settlement Equation (T3.5) for Ledger AI v2.

Computes expected net settlement amount from canonical fields:
  expected_net = gross_amount - fee_amount - tax_amount - refund_amount + adjustment_amount

Falls back cleanly to net_amount or raw amount if explicit fee breakdown is unpopulated.
"""

from typing import Optional
from schema import CanonicalTransaction


def expected_net(tx: CanonicalTransaction) -> float:
    """
    Computes expected net settlement value considering fees, taxes, refunds, and adjustments.
    """
    if tx is None:
        return 0.0

    # If explicit fee/tax/refund/adjustment evidence is present, compute breakdown equation
    has_breakdown = any(
        val is not None and val != 0.0
        for val in [tx.fee_amount, tx.tax_amount, tx.refund_amount, tx.adjustment_amount]
    )

    if has_breakdown:
        gross = tx.gross_amount if tx.gross_amount is not None else (tx.net_amount if tx.net_amount is not None else 0.0)
        fee = tx.fee_amount or 0.0
        tax = tx.tax_amount or 0.0
        refund = tx.refund_amount or 0.0
        adj = tx.adjustment_amount or 0.0

        return round(gross - fee - tax - refund + adj, 2)

    # Fallback: return net_amount or gross_amount
    if tx.net_amount is not None:
        return round(float(tx.net_amount), 2)
    if tx.gross_amount is not None:
        return round(float(tx.gross_amount), 2)

    return 0.0
