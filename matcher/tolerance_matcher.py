"""
tolerance_matcher.py — Fuzzy Tolerance Matching Engine (T3.1-T3.5, T3B.3) for Ledger AI v2.

Extends tolerance matching logic for primary vs counterpart transaction sets:
  - Multi-signal narration similarity: max(SequenceMatcher ratio, Token-Jaccard similarity).
  - Ambiguous-tie routing: routes tied candidates to Exception Ledger with exception_type='ambiguous_tie'.
  - Relative + fee-aware amount tolerance: calculates effective_tolerance dynamically via MatchingConfig.
  - Business-day-aware date tolerance: uses business_days_between() when config.business_day_aware = True.
  - Dynamic evidence-weighted confidence scoring (T3B.3).
"""

import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, List, Any, Dict, Tuple, Union
import dateutil.parser
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction, row_to_canonical
from matcher.eligibility_guards import candidates_compatible
from matcher.settlement_equation import expected_net
from matcher.date_utils import business_days_between
from matcher.split_aggregate_matcher import split_aggregate_match
from matcher.scoring_engine import MatchEvidence, compute_confidence

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_data():
    primary = _safe_read_csv(GENERATED_DIR / "primary_records.csv")
    if primary.empty:
        primary = _safe_read_csv(GENERATED_DIR / "bank_statement.csv")

    counterpart = _safe_read_csv(GENERATED_DIR / "counterpart_records.csv")
    if counterpart.empty:
        s_df = _safe_read_csv(GENERATED_DIR / "razorpay_settlements.csv")
        o_df = _safe_read_csv(GENERATED_DIR / "internal_orders.csv")
        counterpart = pd.concat([s_df, o_df], ignore_index=True) if not (s_df.empty and o_df.empty) else pd.DataFrame()

    exact_matches = _safe_read_csv(RESULTS_DIR / "exact_matches.csv")
    return primary, counterpart, exact_matches


def get_effective_tolerance(reference_amount: float, cfg: MatchingConfig) -> float:
    abs_tol = cfg.absolute_amount_tolerance if cfg.absolute_amount_tolerance is not None else 1.00
    pct_tol = (cfg.percentage_tolerance * abs(reference_amount)) if cfg.percentage_tolerance is not None else 0.0
    effective = max(abs_tol, pct_tol)
    if cfg.max_tolerance_cap is not None:
        effective = min(cfg.max_tolerance_cap, effective)
    return round(effective, 2)


def get_date_diff(d1: Optional[str], d2: Optional[str], cfg: MatchingConfig) -> int:
    sentinel = getattr(cfg, "date_diff_error_sentinel", 999)
    if cfg.business_day_aware:
        return business_days_between(d1, d2, error_sentinel=sentinel)

    if not d1 or not d2:
        return sentinel
    try:
        dt1 = dateutil.parser.parse(str(d1))
        dt2 = dateutil.parser.parse(str(d2))
        return abs((dt1 - dt2).days)
    except Exception:
        return sentinel


def normalize_text(value: Any) -> str:
    if pd.isna(value) or value is None:
        return ""
    return str(value).upper().strip().replace(" ", "")


def narration_similarity(left: Any, right: Any) -> float:
    s_left = str(left or "").strip()
    s_right = str(right or "").strip()

    if not s_left or not s_right:
        return 0.0

    norm_left = normalize_text(s_left)
    norm_right = normalize_text(s_right)
    seq_ratio = SequenceMatcher(None, norm_left, norm_right).ratio() if norm_left and norm_right else 0.0

    tokens_left = set(re.findall(r"\w+", s_left.lower()))
    tokens_right = set(re.findall(r"\w+", s_right.lower()))

    jaccard_score = 0.0
    if tokens_left and tokens_right:
        intersection = tokens_left.intersection(tokens_right)
        union = tokens_left.union(tokens_right)
        jaccard_score = len(intersection) / len(union) if union else 0.0

    return round(max(seq_ratio, jaccard_score), 4)


def _to_canonical_list(items: Union[pd.DataFrame, List[Any]], fallback_prefix: str = "tx") -> List[CanonicalTransaction]:
    if items is None:
        return []
    if isinstance(items, pd.DataFrame):
        return [row_to_canonical(row, fallback_prefix) for _, row in items.iterrows()]
    return [row_to_canonical(item, fallback_prefix) for item in items]


def tolerance_match(
    primary: Union[pd.DataFrame, List[Any]],
    counterpart: Union[pd.DataFrame, List[Any]],
    exact_matches: Optional[pd.DataFrame] = None,
    split_matches: Optional[pd.DataFrame] = None,
    cfg: Optional[MatchingConfig] = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    One-to-one fuzzy tolerance matching.
    Returns (matches_dataframe, ambiguous_tie_exceptions_dataframe).
    """
    if cfg is None:
        cfg = MatchingConfig()

    primary_txs = _to_canonical_list(primary, "pri_id")
    counterpart_txs = _to_canonical_list(counterpart, "cnt_id")

    resolved_pri = set()
    resolved_cnt = set()

    if exact_matches is not None and not exact_matches.empty:
        p_col = "primary_transaction_id" if "primary_transaction_id" in exact_matches.columns else "settlement_id"
        c_col = "counterpart_transaction_id" if "counterpart_transaction_id" in exact_matches.columns else "bank_transaction_id"
        if p_col in exact_matches.columns:
            for v in exact_matches[p_col]:
                resolved_pri.update(str(v).split("|"))
        if c_col in exact_matches.columns:
            for v in exact_matches[c_col]:
                resolved_cnt.update(str(v).split("|"))

    if split_matches is not None and not split_matches.empty:
        p_col = "primary_transaction_id" if "primary_transaction_id" in split_matches.columns else "settlement_id"
        c_col = "counterpart_transaction_id" if "counterpart_transaction_id" in split_matches.columns else "bank_transaction_id"
        if p_col in split_matches.columns:
            for v in split_matches[p_col]:
                resolved_pri.update(str(v).split("|"))
        if c_col in split_matches.columns:
            for v in split_matches[c_col]:
                resolved_cnt.update(str(v).split("|"))

    unresolved_pri = [tx for tx in primary_txs if tx.transaction_id not in resolved_pri]
    unresolved_cnt = [tx for tx in counterpart_txs if tx.transaction_id not in resolved_cnt]

    empty_matches = pd.DataFrame(columns=[
        "primary_transaction_id", "primary_statement_id",
        "counterpart_transaction_id", "counterpart_statement_id",
        "match_type", "amount_difference", "date_difference_days",
        "narration_similarity", "is_match", "confidence"
    ])
    empty_ties = pd.DataFrame(columns=[
        "primary_transaction_id", "candidate_ids", "exception_type",
        "stage", "decision", "confidence", "reason"
    ])

    if not unresolved_pri or not unresolved_cnt:
        return empty_matches, empty_ties

    matches = []
    tie_exceptions = []

    for tx_p in unresolved_pri:
        p_amt = expected_net(tx_p)
        eff_tol = get_effective_tolerance(p_amt, cfg)

        candidates = []
        for tx_c in unresolved_cnt:
            if not candidates_compatible(tx_p, tx_c):
                continue

            c_amt = float(tx_c.net_amount or 0.0)
            amt_diff = abs(p_amt - c_amt)
            if amt_diff > eff_tol:
                continue

            ddiff = get_date_diff(tx_p.transaction_date, tx_c.transaction_date, cfg)
            if ddiff > cfg.date_tolerance_days:
                continue

            sim = narration_similarity(tx_p.utr or tx_p.description, tx_c.description or tx_c.utr)

            candidates.append({
                "primary_transaction_id": tx_p.transaction_id,
                "primary_statement_id": tx_p.primary_statement_id or "",
                "counterpart_transaction_id": tx_c.transaction_id,
                "counterpart_statement_id": tx_c.counterpart_statement_id or "",
                "amount_difference": round(amt_diff, 2),
                "date_difference_days": ddiff,
                "narration_similarity": round(sim, 4)
            })

        if not candidates:
            continue

        candidates.sort(key=lambda x: (x["amount_difference"], x["date_difference_days"], -x["narration_similarity"]))
        best = candidates[0]

        if tx_p.utr and tx_p.utr.lower() != "nan":
            if best["narration_similarity"] < cfg.narration_similarity_threshold:
                continue

        # Ambiguous Tie Check
        if len(candidates) > 1:
            second = candidates[1]
            same_amount = (best["amount_difference"] == second["amount_difference"])
            same_date = (best["date_difference_days"] == second["date_difference_days"])

            if same_amount and same_date:
                cand_ids = f"{best['counterpart_transaction_id']}|{second['counterpart_transaction_id']}"
                tie_exceptions.append({
                    "primary_transaction_id": tx_p.transaction_id,
                    "candidate_ids": cand_ids,
                    "counterpart_transaction_id": cand_ids,
                    "exception_type": "ambiguous_tie",
                    "stage": "tolerance_matcher",
                    "decision": "review",
                    "confidence": cfg.ambiguous_tie_confidence,
                    "reason": f"Ambiguous tie between candidate '{best['counterpart_transaction_id']}' and candidate '{second['counterpart_transaction_id']}' (same amount & date gap)."
                })
                continue

        ev = MatchEvidence(
            identifier_match_type="partial" if best["narration_similarity"] >= cfg.narration_similarity_threshold else "none",
            amount_diff=best["amount_difference"],
            date_diff_days=best["date_difference_days"],
            narration_similarity=best["narration_similarity"]
        )
        conf = compute_confidence(ev, cfg)

        matches.append({
            "primary_transaction_id": best["primary_transaction_id"],
            "primary_statement_id": best["primary_statement_id"],
            "counterpart_transaction_id": best["counterpart_transaction_id"],
            "counterpart_statement_id": best["counterpart_statement_id"],
            "match_type": "tolerance",
            "amount_difference": best["amount_difference"],
            "date_difference_days": best["date_difference_days"],
            "narration_similarity": best["narration_similarity"],
            "is_match": True,
            "confidence": conf
        })

    m_df = pd.DataFrame(matches) if matches else empty_matches
    t_df = pd.DataFrame(tie_exceptions) if tie_exceptions else empty_ties
    return m_df, t_df


def main():
    primary, counterpart, exact_matches = load_data()
    split_matches = split_aggregate_match(primary, counterpart, exact_matches)
    matches, ties = tolerance_match(primary, counterpart, exact_matches, split_matches)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "tolerance_matches.csv"
    matches.to_csv(output_path, index=False)

    print("=" * 60)
    print("LEDGER - TOLERANCE MATCHING (Primary/Counterpart Architecture)")
    print("=" * 60)
    print(f"Tolerance matches: {len(matches)}")
    print(f"Ambiguous ties routed to exception ledger: {len(ties)}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()