"""
exact_matcher.py — Deterministic Exact Matching Engine (T3.1-T3.5, T3B.3) for Ledger AI v2.

Matches primary transactions (is_primary=True) against counterpart transactions (is_primary=False).
1. Case-insensitive, prefix-stripped UTR / Order ID / Reference matching
2. Single-candidate Amount + Date window fallback
3. Config-driven thresholds and dynamic evidence-weighted confidence scoring (no hardcoded literals).
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import dateutil.parser
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction, row_to_canonical
from matcher.eligibility_guards import candidates_compatible
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

    return primary, counterpart


def _norm_str(text: Any, prefix_list: Optional[tuple] = None) -> str:
    if pd.isna(text) or text is None:
        return ""
    s = str(text).upper().strip()
    prefixes = prefix_list or ("NEFTCR-", "NEFTCR", "NEFT-", "NEFT", "UPI-", "UPI", "UTR-", "UTR", "GPAY-", "GPAY", "REF:")
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s[len(prefix):]
    return "".join(c for c in s if c.isalnum())


def _date_diff_days(d1: Optional[str], d2: Optional[str]) -> Optional[int]:
    if not d1 or not d2:
        return None
    try:
        dt1 = dateutil.parser.parse(d1)
        dt2 = dateutil.parser.parse(d2)
        return abs((dt1 - dt2).days)
    except Exception:
        return None


def _to_canonical_list(items: Union[pd.DataFrame, List[Any]], fallback_prefix: str = "tx") -> List[CanonicalTransaction]:
    if items is None:
        return []
    if isinstance(items, pd.DataFrame):
        return [row_to_canonical(row, fallback_prefix) for _, row in items.iterrows()]
    return [row_to_canonical(item, fallback_prefix) for item in items]


def exact_match(
    primary: Union[pd.DataFrame, List[Any]],
    counterpart: Union[pd.DataFrame, List[Any]],
    cfg: Optional[MatchingConfig] = None
) -> pd.DataFrame:
    """
    Executes deterministic exact matching across primary and counterpart transaction pools.
    Uses dynamic evidence scoring for confidence values (T3B.3).
    """
    if cfg is None:
        cfg = MatchingConfig()

    primary_txs = _to_canonical_list(primary, "pri_id")
    counterpart_txs = _to_canonical_list(counterpart, "cnt_id")

    empty_df = pd.DataFrame(columns=[
        "primary_transaction_id", "primary_statement_id",
        "counterpart_transaction_id", "counterpart_statement_id",
        "amount", "date", "match_type", "is_match", "confidence"
    ])

    if not primary_txs or not counterpart_txs:
        return empty_df

    matches = []
    matched_cnt_ids = set()

    min_len = getattr(cfg, "minimum_identifier_length", 5)
    prefixes = getattr(cfg, "utr_prefix_strip_list", None)

    for tx_p in primary_txs:
        if not tx_p.transaction_id or tx_p.transaction_id == "tx_unk" or (tx_p.net_amount or 0.0) <= 0:
            continue

        available_cnt = [tx for tx in counterpart_txs if tx.transaction_id not in matched_cnt_ids]
        if not available_cnt:
            break

        p_order_norm = _norm_str(tx_p.order_id or tx_p.transaction_id, prefixes)
        p_utr_norm = _norm_str(tx_p.utr or tx_p.transaction_id, prefixes)

        matched_cnt_target = None

        # Priority 1: Identifier Cross-Matching
        for tx_c in available_cnt:
            if not candidates_compatible(tx_p, tx_c):
                continue

            c_desc_norm = _norm_str(tx_c.description, prefixes)
            c_utr_norm = _norm_str(tx_c.utr or tx_c.transaction_id, prefixes)
            c_order_norm = _norm_str(tx_c.order_id or tx_c.transaction_id, prefixes)

            # Check UTR match
            if p_utr_norm and len(p_utr_norm) >= min_len and (p_utr_norm == c_utr_norm or p_utr_norm in c_desc_norm):
                ddiff = _date_diff_days(tx_p.transaction_date, tx_c.transaction_date) or 0
                ev = MatchEvidence(identifier_match_type="exact_utr", amount_diff=0.0, date_diff_days=ddiff, narration_similarity=1.0)
                conf = compute_confidence(ev, cfg)
                matched_cnt_target = (tx_c, "exact_utr_match", conf)
                break
            # Check Order ID match
            elif p_order_norm and len(p_order_norm) >= min_len and (p_order_norm == c_order_norm or p_order_norm in c_desc_norm):
                ddiff = _date_diff_days(tx_p.transaction_date, tx_c.transaction_date) or 0
                ev = MatchEvidence(identifier_match_type="exact_order_id", amount_diff=0.0, date_diff_days=ddiff, narration_similarity=1.0)
                conf = compute_confidence(ev, cfg)
                matched_cnt_target = (tx_c, "exact_order_id_match", conf)
                break

        if matched_cnt_target:
            tx_c, m_type, conf = matched_cnt_target
            matched_cnt_ids.add(tx_c.transaction_id)
            matches.append({
                "primary_transaction_id": tx_p.transaction_id,
                "primary_statement_id": tx_p.primary_statement_id or "",
                "counterpart_transaction_id": tx_c.transaction_id,
                "counterpart_statement_id": tx_c.counterpart_statement_id or "",
                "amount": tx_p.net_amount,
                "date": tx_p.transaction_date,
                "match_type": m_type,
                "is_match": True,
                "confidence": conf,
            })
            continue

        # Priority 2: Single Unambiguous Amount + Date Window Match
        amt_candidates = []
        for tx_c in available_cnt:
            if not candidates_compatible(tx_p, tx_c):
                continue

            if tx_p.net_amount == tx_c.net_amount:
                ddiff = _date_diff_days(tx_p.transaction_date, tx_c.transaction_date)
                if ddiff is None or ddiff <= cfg.date_tolerance_days:
                    amt_candidates.append((tx_c, ddiff or 0))

        if len(amt_candidates) == 1:
            tx_c, ddiff = amt_candidates[0]
            matched_cnt_ids.add(tx_c.transaction_id)
            ev = MatchEvidence(identifier_match_type="none", amount_diff=0.0, date_diff_days=ddiff, narration_similarity=0.0)
            conf = compute_confidence(ev, cfg)
            matches.append({
                "primary_transaction_id": tx_p.transaction_id,
                "primary_statement_id": tx_p.primary_statement_id or "",
                "counterpart_transaction_id": tx_c.transaction_id,
                "counterpart_statement_id": tx_c.counterpart_statement_id or "",
                "amount": tx_p.net_amount,
                "date": tx_p.transaction_date,
                "match_type": "exact_amount_single",
                "is_match": True,
                "confidence": conf,
            })

    if not matches:
        return empty_df

    return pd.DataFrame(matches)


def main():
    primary, counterpart = load_data()
    matches = exact_match(primary, counterpart)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "exact_matches.csv"
    matches.to_csv(output_path, index=False)

    print("=" * 60)
    print("LEDGER - EXACT MATCHING ENGINE (Primary/Counterpart Architecture)")
    print("=" * 60)
    print(f"Primary records loaded: {len(primary)}")
    print(f"Counterpart records loaded: {len(counterpart)}")
    print(f"Exact matches produced: {len(matches)}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()