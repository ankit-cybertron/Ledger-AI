"""
exact_matcher.py — Deterministic Exact Matching Engine (v2 extended) for Ledger AI v2.

Extends existing exact matching logic:
  - Reference-hierarchy matching (T3.1): checks identifiers in priority order (utr -> rrn -> gateway_reference -> auth_code -> order_id/settlement_id -> description).
  - Tightens amount-only match (T3.2): enforces date_difference_days <= config.date_tolerance_days and drops confidence to amount_only_confidence (0.90).
  - Currency & Eligibility Gate (T3.3): calls candidates_compatible() before any comparison.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import dateutil.parser
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction
from matcher.eligibility_guards import candidates_compatible

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"


def _safe_read_csv(path, default_cols=None):
    if not Path(path).exists():
        return pd.DataFrame(columns=default_cols or [])
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=default_cols or [])


def load_data():
    settlements = _safe_read_csv(
        GENERATED_DIR / "razorpay_settlements.csv",
        ["settlement_id", "order_id", "payment_id", "utr", "amount", "status", "created_at"]
    )
    orders = _safe_read_csv(
        GENERATED_DIR / "internal_orders.csv",
        ["order_id", "payment_id", "amount", "status", "created_at"]
    )
    bank = _safe_read_csv(
        GENERATED_DIR / "bank_statement.csv",
        ["bank_transaction_id", "date", "utr", "amount", "description"]
    )
    return settlements, bank, orders


def _norm_str(text):
    if pd.isna(text) or text is None:
        return ""
    return str(text).upper().replace(" ", "").replace("-", "").replace("_", "").replace("NEFTCR", "").strip()


def _row_to_canonical(row: Any, fallback_id_key: str = "tx_id") -> CanonicalTransaction:
    """
    Helper converting pandas Series, Dict, or CanonicalTransaction into a CanonicalTransaction.
    """
    if isinstance(row, CanonicalTransaction):
        return row

    d = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    tx_id = str(
        d.get("settlement_id")
        or d.get("bank_transaction_id")
        or d.get("order_id")
        or d.get("transaction_id")
        or d.get(fallback_id_key)
        or "tx_unk"
    ).strip()

    raw_amt = d.get("amount") if d.get("amount") is not None else (d.get("net_amount") if d.get("net_amount") is not None else d.get("credit"))
    net_amt = round(float(pd.to_numeric(raw_amt, errors="coerce") or 0.0), 2) if raw_amt is not None else None

    return CanonicalTransaction(
        transaction_id=tx_id,
        source_type=str(d.get("source_type")).upper() if d.get("source_type") else None,
        transaction_date=str(d.get("date") or d.get("created_at") or d.get("transaction_date") or "").strip() or None,
        net_amount=net_amt,
        currency=str(d.get("currency")).strip() if d.get("currency") else None,
        utr=str(d.get("utr")).strip() if d.get("utr") else None,
        rrn=str(d.get("rrn")).strip() if d.get("rrn") else None,
        gateway_reference=str(d.get("gateway_reference") or d.get("Gateway Ref")).strip() if (d.get("gateway_reference") or d.get("Gateway Ref")) else None,
        auth_code=str(d.get("auth_code")).strip() if d.get("auth_code") else None,
        order_id=str(d.get("order_id")).strip() if d.get("order_id") else None,
        settlement_id=str(d.get("settlement_id")).strip() if d.get("settlement_id") else None,
        description=str(d.get("description") or d.get("Particulars") or d.get("Customer Name") or "").strip() or None,
        status=str(d.get("status")).strip() if d.get("status") else None
    )


def _date_diff_days(d1: Optional[str], d2: Optional[str]) -> Optional[int]:
    if not d1 or not d2:
        return None
    try:
        dt1 = dateutil.parser.parse(d1)
        dt2 = dateutil.parser.parse(d2)
        return abs((dt1 - dt2).days)
    except Exception:
        return None


def exact_match(settlements, bank, orders=None, cfg: Optional[MatchingConfig] = None):
    """
    Match settlement, order, and bank records using multi-source rules with hierarchy matching,
    date tolerance guards, and currency eligibility checks.
    """
    if cfg is None:
        cfg = MatchingConfig()

    matches = []
    matched_bank_ids = set()
    matched_settlement_indices = set()
    matched_order_ids = set()

    # Reference priority hierarchy list (T3.1)
    ref_hierarchy = ["utr", "rrn", "gateway_reference", "auth_code", "order_id", "settlement_id", "description"]

    # --- 1. Match Internal Orders against UPI / Card / Cash Sub-Ledger statements ---
    if orders is not None and not orders.empty and not settlements.empty:
        for _, o_row in orders.iterrows():
            tx_o = _row_to_canonical(o_row, "order_id")
            if not tx_o.transaction_id or tx_o.net_amount == 0.0:
                continue

            available_s = settlements[~settlements.index.isin(matched_settlement_indices)].copy()
            if available_s.empty:
                break

            for s_idx, s_row in available_s.iterrows():
                tx_s = _row_to_canonical(s_row, "settlement_id")

                # T3.3 Currency & Eligibility Gate
                if not candidates_compatible(tx_o, tx_s):
                    continue

                if tx_o.net_amount == tx_s.net_amount:
                    # Priority reference match check
                    matched_ref_type = None

                    for ref_key in ref_hierarchy:
                        val_o = getattr(tx_o, ref_key, None)
                        val_s = getattr(tx_s, ref_key, None)

                        if val_o and val_s and _norm_str(val_o) == _norm_str(val_s):
                            matched_ref_type = f"exact_{ref_key}_amount"
                            break

                        # Check if order ref exists in description
                        if val_o and tx_s.description and _norm_str(val_o) in _norm_str(tx_s.description):
                            matched_ref_type = f"exact_{ref_key}_in_description"
                            break

                    # Date match fallback
                    if not matched_ref_type and tx_o.transaction_date and tx_o.transaction_date == tx_s.transaction_date:
                        matched_ref_type = "order_subledger_date_match"

                    if matched_ref_type:
                        matched_order_ids.add(tx_o.transaction_id)
                        matched_settlement_indices.add(s_idx)
                        matches.append({
                            "settlement_id": tx_o.transaction_id,
                            "bank_transaction_id": tx_s.transaction_id,
                            "amount": tx_o.net_amount,
                            "date": tx_o.transaction_date,
                            "match_type": matched_ref_type,
                            "is_match": True,
                            "confidence": 1.0,
                        })
                        break

    # --- 2. Match Direct Bank Transfers & Settlements to Bank Statements ---
    combined_sources = settlements if settlements is not None else pd.DataFrame()
    if orders is not None and not orders.empty:
        unmatched_orders = orders[~orders["order_id"].astype(str).isin(matched_order_ids)].copy()
        if not unmatched_orders.empty:
            if "settlement_id" not in unmatched_orders.columns and "order_id" in unmatched_orders.columns:
                unmatched_orders["settlement_id"] = unmatched_orders["order_id"]
            combined_sources = pd.concat([combined_sources, unmatched_orders], ignore_index=True).drop_duplicates(subset=["settlement_id"], keep="first")

    if not combined_sources.empty and bank is not None and not bank.empty:
        for _, s_row in combined_sources.iterrows():
            tx_s = _row_to_canonical(s_row, "settlement_id")
            if not tx_s.transaction_id or tx_s.net_amount == 0.0:
                continue

            available_bank = bank[~bank["bank_transaction_id"].isin(matched_bank_ids)].copy()
            if available_bank.empty:
                break

            matched_candidate = None

            # Priority Hierarchy Search (T3.1)
            for _, b_row in available_bank.iterrows():
                tx_b = _row_to_canonical(b_row, "bank_transaction_id")

                # T3.3 Currency & Eligibility Gate
                if not candidates_compatible(tx_s, tx_b):
                    continue

                if tx_s.net_amount == tx_b.net_amount:
                    # Check reference hierarchy
                    for ref_key in ref_hierarchy:
                        val_s = getattr(tx_s, ref_key, None)
                        val_b = getattr(tx_b, ref_key, None)

                        if val_s and val_b and _norm_str(val_s) == _norm_str(val_b):
                            matched_candidate = (tx_b.transaction_id, f"exact_{ref_key}_amount", 1.0)
                            break

                        if val_s and tx_b.description and _norm_str(val_s) in _norm_str(tx_b.description):
                            matched_candidate = (tx_b.transaction_id, f"exact_{ref_key}_in_description", 1.0)
                            break

                    if matched_candidate:
                        break

            if matched_candidate:
                b_id, m_type, conf = matched_candidate
                matched_bank_ids.add(b_id)
                matches.append({
                    "settlement_id": tx_s.transaction_id,
                    "bank_transaction_id": b_id,
                    "amount": tx_s.net_amount,
                    "date": tx_s.transaction_date,
                    "match_type": m_type,
                    "is_match": True,
                    "confidence": conf,
                })
                continue

            # T3.2 Single Unambiguous Amount & Date Tolerance Match
            amt_candidates = []
            for _, b_row in available_bank.iterrows():
                tx_b = _row_to_canonical(b_row, "bank_transaction_id")

                if not candidates_compatible(tx_s, tx_b):
                    continue

                if tx_s.net_amount == tx_b.net_amount:
                    ddiff = _date_diff_days(tx_s.transaction_date, tx_b.transaction_date)
                    # Enforce date tolerance constraint (T3.2)
                    if ddiff is None or ddiff <= cfg.date_tolerance_days:
                        amt_candidates.append((tx_b.transaction_id, ddiff))

            if len(amt_candidates) == 1:
                b_id, _ = amt_candidates[0]
                matched_bank_ids.add(b_id)
                matches.append({
                    "settlement_id": tx_s.transaction_id,
                    "bank_transaction_id": b_id,
                    "amount": tx_s.net_amount,
                    "date": tx_s.transaction_date,
                    "match_type": "exact_amount_single",
                    "is_match": True,
                    "confidence": getattr(cfg, "amount_only_confidence", 0.90),
                })

    if not matches:
        return pd.DataFrame(columns=["settlement_id", "bank_transaction_id", "amount", "date", "match_type", "is_match", "confidence"])

    return pd.DataFrame(matches)


def main():
    settlements, bank, orders = load_data()
    matches = exact_match(settlements, bank, orders)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "exact_matches.csv"
    matches.to_csv(output_path, index=False)

    print("=" * 60)
    print("LEDGER - EXACT MATCHING (v2 Extended)")
    print("=" * 60)
    print(f"Settlements: {len(settlements)}")
    print(f"Bank records: {len(bank)}")
    print(f"Exact matches: {len(matches)}")
    print(f"Unmatched settlements: {len(settlements) - len(matches)}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()