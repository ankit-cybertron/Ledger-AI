"""
tolerance_matcher.py — Fuzzy Tolerance & Split Matching Engine (v2 extended) for Ledger AI v2.

Extends existing tolerance matching logic:
  - Multi-signal narration similarity (T3.7): max(SequenceMatcher ratio, Token-Jaccard similarity).
  - Ambiguous-tie routing (T3.8): routes tied candidates to Exception Ledger with exception_type='ambiguous_tie' carrying candidate IDs instead of silent drops.
  - Relative + fee-aware amount tolerance (T3.4): calculates effective_tolerance dynamically via MatchingConfig.
  - Settlement equation (T3.5): uses expected_net(tx_s) considering fees/taxes/refunds when available.
  - Business-day-aware date tolerance (T3.6): uses business_days_between() when config.business_day_aware = True.
  - Currency & Eligibility Gate (T3.3): calls candidates_compatible() before comparisons.
"""

import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, List, Any, Dict, Tuple
import dateutil.parser
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction
from matcher.eligibility_guards import candidates_compatible
from matcher.settlement_equation import expected_net
from matcher.date_utils import business_days_between

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
    bank = _safe_read_csv(
        GENERATED_DIR / "bank_statement.csv",
        ["bank_transaction_id", "date", "utr", "amount", "description"]
    )
    exact_matches = _safe_read_csv(
        RESULTS_DIR / "exact_matches.csv",
        ["settlement_id", "bank_transaction_id"]
    )
    return settlements, bank, exact_matches


def get_effective_tolerance(reference_amount: float, cfg: MatchingConfig) -> float:
    abs_tol = cfg.absolute_amount_tolerance if cfg.absolute_amount_tolerance is not None else 1.00
    pct_tol = (cfg.percentage_tolerance * abs(reference_amount)) if cfg.percentage_tolerance is not None else 0.0
    effective = max(abs_tol, pct_tol)
    if cfg.max_tolerance_cap is not None:
        effective = min(cfg.max_tolerance_cap, effective)
    return round(effective, 2)


def get_date_diff(d1: Optional[str], d2: Optional[str], cfg: MatchingConfig) -> int:
    if cfg.business_day_aware:
        return business_days_between(d1, d2)

    if not d1 or not d2:
        return 999
    try:
        dt1 = dateutil.parser.parse(str(d1))
        dt2 = dateutil.parser.parse(str(d2))
        return abs((dt1 - dt2).days)
    except Exception:
        return 999


def normalize_text(value):
    if pd.isna(value) or value is None:
        return ""
    return str(value).upper().strip().replace(" ", "")


def narration_similarity(left: Any, right: Any) -> float:
    """
    Multi-signal narration similarity (T3.7).
    Computes max(SequenceMatcher ratio, Token-Jaccard score).
    """
    s_left = str(left or "").strip()
    s_right = str(right or "").strip()

    if not s_left or not s_right:
        return 0.0

    # 1. Character-level SequenceMatcher
    norm_left = normalize_text(s_left)
    norm_right = normalize_text(s_right)
    seq_ratio = SequenceMatcher(None, norm_left, norm_right).ratio() if norm_left and norm_right else 0.0

    # 2. Word/Token-Jaccard similarity
    tokens_left = set(re.findall(r"\w+", s_left.lower()))
    tokens_right = set(re.findall(r"\w+", s_right.lower()))

    jaccard_score = 0.0
    if tokens_left and tokens_right:
        intersection = tokens_left.intersection(tokens_right)
        union = tokens_left.union(tokens_right)
        jaccard_score = len(intersection) / len(union) if union else 0.0

    return round(max(seq_ratio, jaccard_score), 4)


def _row_to_canonical(row: Any, fallback_id_key: str = "tx_id") -> CanonicalTransaction:
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
    gross_amt = round(float(pd.to_numeric(d.get("gross_amount"), errors="coerce") or 0.0), 2) if d.get("gross_amount") is not None else None
    fee_amt = round(float(pd.to_numeric(d.get("fee_amount") or d.get("fee"), errors="coerce") or 0.0), 2) if (d.get("fee_amount") is not None or d.get("fee") is not None) else None
    tax_amt = round(float(pd.to_numeric(d.get("tax_amount") or d.get("tax"), errors="coerce") or 0.0), 2) if (d.get("tax_amount") is not None or d.get("tax") is not None) else None
    ref_amt = round(float(pd.to_numeric(d.get("refund_amount"), errors="coerce") or 0.0), 2) if d.get("refund_amount") is not None else None
    adj_amt = round(float(pd.to_numeric(d.get("adjustment_amount"), errors="coerce") or 0.0), 2) if d.get("adjustment_amount") is not None else None

    return CanonicalTransaction(
        transaction_id=tx_id,
        source_type=str(d.get("source_type")).upper() if d.get("source_type") else None,
        transaction_date=str(d.get("date") or d.get("created_at") or d.get("transaction_date") or "").strip() or None,
        gross_amount=gross_amt,
        fee_amount=fee_amt,
        tax_amount=tax_amt,
        refund_amount=ref_amt,
        adjustment_amount=adj_amt,
        net_amount=net_amt,
        currency=str(d.get("currency")).strip() if d.get("currency") else None,
        utr=str(d.get("utr")).strip() if d.get("utr") else None,
        rrn=str(d.get("rrn")).strip() if d.get("rrn") else None,
        order_id=str(d.get("order_id")).strip() if d.get("order_id") else None,
        settlement_id=str(d.get("settlement_id")).strip() if d.get("settlement_id") else None,
        description=str(d.get("description") or d.get("Particulars") or d.get("Customer Name") or "").strip() or None,
        status=str(d.get("status")).strip() if d.get("status") else None
    )


def split_settlement_match(settlements, bank, exact_matches, cfg: Optional[MatchingConfig] = None):
    if cfg is None:
        cfg = MatchingConfig()

    exact_settlements = set(exact_matches["settlement_id"]) if not exact_matches.empty else set()
    exact_bank = set(exact_matches["bank_transaction_id"]) if not exact_matches.empty else set()

    unresolved = settlements[~settlements["settlement_id"].isin(exact_settlements)] if not settlements.empty else pd.DataFrame()
    available_bank = bank[~bank["bank_transaction_id"].isin(exact_bank)] if not bank.empty else pd.DataFrame()

    if unresolved.empty or available_bank.empty:
        return pd.DataFrame()

    matches = []

    for _, s_row in unresolved.iterrows():
        tx_s = _row_to_canonical(s_row, "settlement_id")
        utr = tx_s.utr

        if not utr or utr.lower() == "nan":
            continue

        raw_cands = available_bank[
            available_bank["utr"].fillna("").astype(str).str.strip() == utr
        ].copy()

        if len(raw_cands) < 2:
            continue

        valid = []
        for _, b_row in raw_cands.iterrows():
            tx_b = _row_to_canonical(b_row, "bank_transaction_id")

            if not candidates_compatible(tx_s, tx_b):
                continue

            s_date = tx_s.transaction_date or s_row.get("created_at") or s_row.get("settlement_date")
            b_date = tx_b.transaction_date or b_row.get("transaction_date") or b_row.get("date")

            ddiff = get_date_diff(s_date, b_date, cfg)
            if ddiff <= cfg.date_tolerance_days:
                valid.append(b_row)

        if len(valid) < 2:
            continue

        valid_df = pd.DataFrame(valid)
        total_credit = round(float(pd.to_numeric(valid_df.get("credit", valid_df.get("amount")), errors="coerce").sum()), 2)
        target_amt = expected_net(tx_s)
        amt_diff = round(abs(target_amt - total_credit), 2)
        eff_tol = get_effective_tolerance(target_amt, cfg)

        if amt_diff > eff_tol:
            continue

        bank_ids = sorted(valid_df["bank_transaction_id"].astype(str).tolist())
        matches.append({
            "settlement_id": tx_s.transaction_id,
            "bank_transaction_id": "|".join(bank_ids),
            "match_type": "split_settlement",
            "amount_difference": amt_diff,
            "date_difference_days": max(get_date_diff(tx_s.transaction_date, r.get("transaction_date") or r.get("date"), cfg) for _, r in valid_df.iterrows()),
            "narration_similarity": 1.0,
            "is_match": True,
            "confidence": 0.95
        })

    return pd.DataFrame(matches)


def tolerance_match(settlements, bank, exact_matches, split_matches, cfg: Optional[MatchingConfig] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    One-to-one fuzzy tolerance matching.
    Returns (matches_dataframe, ambiguous_tie_exceptions_dataframe).
    """
    if cfg is None:
        cfg = MatchingConfig()

    exact_settlements = set(exact_matches["settlement_id"]) if not exact_matches.empty else set()
    exact_bank = set(exact_matches["bank_transaction_id"]) if not exact_matches.empty else set()

    split_settlements = set()
    split_bank = set()
    if split_matches is not None and not split_matches.empty:
        split_settlements = set(split_matches["settlement_id"])
        for val in split_matches["bank_transaction_id"]:
            split_bank.update(str(val).split("|"))

    resolved_settlements = exact_settlements | split_settlements
    resolved_bank = exact_bank | split_bank

    unresolved = settlements[~settlements["settlement_id"].isin(resolved_settlements)] if not settlements.empty else pd.DataFrame()
    available_bank = bank[~bank["bank_transaction_id"].isin(resolved_bank)] if not bank.empty else pd.DataFrame()

    empty_matches = pd.DataFrame(columns=["settlement_id", "bank_transaction_id", "match_type", "amount_difference", "date_difference_days", "narration_similarity", "is_match", "confidence"])
    empty_ties = pd.DataFrame(columns=["settlement_id", "candidate_ids", "exception_type", "stage", "decision", "confidence", "reason"])

    if unresolved.empty or available_bank.empty:
        return empty_matches, empty_ties

    matches = []
    tie_exceptions = []

    for _, s_row in unresolved.iterrows():
        tx_s = _row_to_canonical(s_row, "settlement_id")
        s_amt = expected_net(tx_s)
        eff_tol = get_effective_tolerance(s_amt, cfg)

        candidates = []
        for _, b_row in available_bank.iterrows():
            tx_b = _row_to_canonical(b_row, "bank_transaction_id")

            if not candidates_compatible(tx_s, tx_b):
                continue

            b_amt = float(tx_b.net_amount or b_row.get("credit") or b_row.get("amount") or 0.0)
            amt_diff = abs(s_amt - b_amt)
            if amt_diff > eff_tol:
                continue

            s_date = tx_s.transaction_date or s_row.get("settlement_date") or s_row.get("created_at")
            b_date = tx_b.transaction_date or b_row.get("transaction_date") or b_row.get("date")

            ddiff = get_date_diff(s_date, b_date, cfg)
            if ddiff > cfg.date_tolerance_days:
                continue

            sim = narration_similarity(tx_s.utr or tx_s.description, tx_b.description)

            candidates.append({
                "settlement_id": tx_s.transaction_id,
                "bank_transaction_id": tx_b.transaction_id,
                "amount_difference": round(amt_diff, 2),
                "date_difference_days": ddiff,
                "narration_similarity": round(sim, 4)
            })

        if not candidates:
            continue

        candidates.sort(key=lambda x: (x["amount_difference"], x["date_difference_days"], -x["narration_similarity"]))
        best = candidates[0]

        if tx_s.utr and tx_s.utr.lower() != "nan":
            if best["narration_similarity"] < cfg.narration_similarity_threshold:
                continue

        # Ambiguous Tie Check (T3.8)
        if len(candidates) > 1:
            second = candidates[1]
            same_amount = (best["amount_difference"] == second["amount_difference"])
            same_date = (best["date_difference_days"] == second["date_difference_days"])

            if same_amount and same_date:
                cand_ids = f"{best['bank_transaction_id']}|{second['bank_transaction_id']}"
                tie_exceptions.append({
                    "settlement_id": tx_s.transaction_id,
                    "candidate_ids": cand_ids,
                    "bank_transaction_id": cand_ids,
                    "exception_type": "ambiguous_tie",
                    "stage": "tolerance_matcher",
                    "decision": "review",
                    "confidence": 0.50,
                    "reason": f"Ambiguous tie between candidate '{best['bank_transaction_id']}' and candidate '{second['bank_transaction_id']}' (same amount & date gap)."
                })
                continue

        matches.append({
            "settlement_id": best["settlement_id"],
            "bank_transaction_id": best["bank_transaction_id"],
            "match_type": "tolerance",
            "amount_difference": best["amount_difference"],
            "date_difference_days": best["date_difference_days"],
            "narration_similarity": best["narration_similarity"],
            "is_match": True,
            "confidence": 0.85
        })

    m_df = pd.DataFrame(matches) if matches else empty_matches
    t_df = pd.DataFrame(tie_exceptions) if tie_exceptions else empty_ties
    return m_df, t_df


def main():
    settlements, bank, exact_matches = load_data()
    split_matches = split_settlement_match(settlements, bank, exact_matches)
    matches, ties = tolerance_match(settlements, bank, exact_matches, split_matches)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "tolerance_matches.csv"
    matches.to_csv(output_path, index=False)

    print("=" * 60)
    print("LEDGER - TOLERANCE MATCHING (v2 Extended)")
    print("=" * 60)
    print(f"Tolerance matches: {len(matches)}")
    print(f"Ambiguous ties routed to exception ledger: {len(ties)}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()