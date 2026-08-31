"""
row_adapter.py — Unified transaction row to CanonicalTransaction adapter (T3.1).

Single source of truth for converting DataFrames, dicts, or existing CanonicalTransaction objects
into validated CanonicalTransaction instances for matcher engines.
"""

from typing import Any, Optional
import pandas as pd
from schema.canonical_transaction import CanonicalTransaction


def _clean_str(val: Any) -> str:
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", "undefined", "—", ""]:
        return ""
    return s


def _extract_field(d: dict, candidates: list) -> str:
    """Case-insensitive dictionary lookup across candidate keys."""
    d_clean = {str(k).lower().replace(" ", "").replace("_", ""): v for k, v in d.items()}
    for cand in candidates:
        cand_clean = cand.lower().replace(" ", "").replace("_", "")
        if cand_clean in d_clean:
            val = _clean_str(d_clean[cand_clean])
            if val:
                return val
    return ""


def row_to_canonical(row: Any, fallback_id_key: str = "tx_id") -> CanonicalTransaction:
    """
    Consolidated _row_to_canonical() implementation per T3.1.
    Converts any row representation (dict, pd.Series, CanonicalTransaction) to CanonicalTransaction.
    """
    if isinstance(row, CanonicalTransaction):
        return row

    d = row.to_dict() if hasattr(row, "to_dict") else dict(row)

    tx_id = (
        _extract_field(d, ["primary_transaction_id", "counterpart_transaction_id", "transaction_id", "bank_transaction_id", "settlement_id", "order_id", fallback_id_key])
        or "tx_unk"
    )
    stmt_id = _extract_field(d, ["primary_statement_id", "counterpart_statement_id", "statement_id", "serial_code"]) or None
    source_name = _extract_field(d, ["source_name", "source_type_label", "source_label", "name"]) or None
    d_order = _extract_field(d, ["order_id", "order_no", "ord_id"])
    d_settlement = _extract_field(d, ["settlement_id", "setl_id"])
    d_utr = _extract_field(d, ["utr", "rrn", "bank_ref"])
    d_date = _extract_field(d, ["transaction_date", "date", "order_date", "txn_date", "value_date", "created_at"])
    d_desc = _extract_field(d, ["description", "narration", "particulars", "customer_name"])
    d_pay = _extract_field(d, ["payment_id", "auth_code", "gateway_reference"])

    raw_amt = d.get("amount") if d.get("amount") is not None else (d.get("net_amount") if d.get("net_amount") is not None else d.get("credit"))
    net_amt = round(float(pd.to_numeric(raw_amt, errors="coerce") or 0.0), 2) if raw_amt is not None else None
    gross_amt = round(float(pd.to_numeric(d.get("gross_amount"), errors="coerce") or 0.0), 2) if d.get("gross_amount") is not None else None
    fee_amt = round(float(pd.to_numeric(d.get("fee_amount") or d.get("fee"), errors="coerce") or 0.0), 2) if (d.get("fee_amount") is not None or d.get("fee") is not None) else None
    tax_amt = round(float(pd.to_numeric(d.get("tax_amount") or d.get("tax"), errors="coerce") or 0.0), 2) if (d.get("tax_amount") is not None or d.get("tax") is not None) else None
    ref_amt = round(float(pd.to_numeric(d.get("refund_amount"), errors="coerce") or 0.0), 2) if d.get("refund_amount") is not None else None
    adj_amt = round(float(pd.to_numeric(d.get("adjustment_amount"), errors="coerce") or 0.0), 2) if d.get("adjustment_amount") is not None else None

    is_pri = bool(d.get("is_primary", False))
    curr = _clean_str(d.get("currency")) or None
    status = _extract_field(d, ["status", "order_status", "txn_status"]) or None

    return CanonicalTransaction(
        transaction_id=tx_id,
        is_primary=is_pri,
        transaction_date=d_date or None,
        gross_amount=gross_amt,
        fee_amount=fee_amt,
        tax_amount=tax_amt,
        refund_amount=ref_amt,
        adjustment_amount=adj_amt,
        net_amount=net_amt,
        currency=curr,
        utr=d_utr or None,
        gateway_reference=d_pay or None,
        auth_code=d_pay or None,
        order_id=d_order or None,
        settlement_id=d_settlement or None,
        description=d_desc or None,
        status=status,
        statement_id=stmt_id,
        source_name=source_name,
        primary_statement_id=stmt_id if is_pri else None,
        counterpart_statement_id=stmt_id if not is_pri else None
    )
