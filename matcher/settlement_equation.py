"""
settlement_equation.py — Expected Net Settlement Equation (T3.5) for Ledger AI v2.

Computes expected net settlement amount from canonical fields:
  expected_net = gross_amount - fee_amount - tax_amount - refund_amount + adjustment_amount

Falls back cleanly to net_amount or raw amount if explicit fee breakdown is unpopulated.
"""

from typing import Optional, Any
from schema import CanonicalTransaction


def expected_net(tx: CanonicalTransaction, cfg: Optional[Any] = None) -> float:
    """
    Computes expected net settlement value considering fees, taxes, refunds, adjustments,
    and channel-specific MDR fee rates (T22.1).
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

    # Fallback: return net_amount if present
    if tx.net_amount is not None:
        return round(float(tx.net_amount), 2)

    # If gross_amount is present, compute expected net via channel fee rate if available (T22.1)
    if tx.gross_amount is not None:
        gross = float(tx.gross_amount)
        if cfg is not None:
            source_hint = f"{tx.source_file or ''} {tx.channel or ''} {tx.description or ''}".lower()
            if "razorpay" in source_hint:
                rzp_fee = gross * getattr(cfg, "razorpay_fee_rate", 0.018)
                rzp_tax = rzp_fee * getattr(cfg, "razorpay_gst_rate", 0.18)
                return round(gross - rzp_fee - rzp_tax, 2)
            elif "paypal" in source_hint:
                pypl_fee = gross * getattr(cfg, "paypal_fee_rate", 0.034)
                return round(gross - pypl_fee, 2)
            elif "card" in source_hint:
                card_fee = gross * getattr(cfg, "card_fee_rate", 0.019)
                return round(gross - card_fee, 2)

        return round(gross, 2)

    return 0.0
