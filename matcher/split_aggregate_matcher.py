"""
split_aggregate_matcher.py — N-Directional Split & Aggregate Matcher (T3.4, T3.9) for Ledger AI v2.

Supports multi-directional transaction reconciliation between primary and counterpart transactions:
  1. 1 <-> N (1 primary transaction -> N counterpart transactions)
  2. N <-> 1 (N primary transactions -> 1 counterpart transaction)
  3. N <-> N (N primary transactions -> M counterpart transactions, strictly constrained by shared reference/UTR cluster).

Rule: Never performs unconstrained combinatorial brute-forcing across unrelated records.
Uses candidates_compatible() for currency/status gates, expected_net() for fee calculation,
and get_effective_tolerance() for dynamic tolerance thresholds.
All confidence thresholds and error sentinels are read directly from MatchingConfig (T3.5).
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction, row_to_canonical
from matcher.eligibility_guards import candidates_compatible
from matcher.settlement_equation import expected_net
from matcher.date_utils import business_days_between

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"


def get_effective_tolerance(reference_amount: float, cfg: MatchingConfig) -> float:
    """Computes effective monetary tolerance threshold applying percentage scaling and max cap."""
    abs_tol = cfg.absolute_amount_tolerance if cfg.absolute_amount_tolerance is not None else 1.00
    pct_tol = (cfg.percentage_tolerance * abs(reference_amount)) if cfg.percentage_tolerance is not None else 0.0
    effective = max(abs_tol, pct_tol)
    if cfg.max_tolerance_cap is not None:
        effective = min(cfg.max_tolerance_cap, effective)
    return round(effective, 2)


def get_date_diff(d1: Optional[str], d2: Optional[str], cfg: MatchingConfig) -> int:
    """Computes calendar or business day difference between two ISO date strings."""
    sentinel = getattr(cfg, "date_diff_error_sentinel", 999)
    if cfg.business_day_aware:
        return business_days_between(d1, d2, error_sentinel=sentinel)

    if not d1 or not d2:
        return sentinel
    try:
        import dateutil.parser
        dt1 = dateutil.parser.parse(str(d1))
        dt2 = dateutil.parser.parse(str(d2))
        return abs((dt1 - dt2).days)
    except Exception:
        return sentinel


def _to_canonical_list(items: Union[pd.DataFrame, List[Any]], fallback_prefix: str = "tx") -> List[CanonicalTransaction]:
    if items is None:
        return []
    if isinstance(items, pd.DataFrame):
        return [row_to_canonical(row, fallback_prefix) for _, row in items.iterrows()]
    return [row_to_canonical(item, fallback_prefix) for item in items]


def split_aggregate_match(
    primary: Union[pd.DataFrame, List[Any]],
    counterpart: Union[pd.DataFrame, List[Any]],
    exact_matches: Optional[pd.DataFrame] = None,
    cfg: Optional[MatchingConfig] = None
) -> pd.DataFrame:
    """
    Executes N-directional split and aggregate matching between primary and counterpart transaction sets.
    """
    if cfg is None:
        cfg = MatchingConfig()

    pri_list = _to_canonical_list(primary, "pri_id")
    cnt_list = _to_canonical_list(counterpart, "cnt_id")

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

    unresolved_pri = [tx for tx in pri_list if tx.transaction_id not in resolved_pri]
    unresolved_cnt = [tx for tx in cnt_list if tx.transaction_id not in resolved_cnt]

    empty_res = pd.DataFrame(columns=[
        "primary_transaction_id", "primary_statement_id",
        "counterpart_transaction_id", "counterpart_statement_id",
        "match_type", "amount_difference", "date_difference_days",
        "is_match", "confidence", "topology"
    ])

    if not unresolved_pri or not unresolved_cnt:
        return empty_res

    # Pre-cluster by normalized reference (UTR / order_id / gateway_ref)
    pri_by_ref: Dict[str, List[CanonicalTransaction]] = {}
    for tx_p in unresolved_pri:
        ref_key = tx_p.utr or tx_p.order_id or tx_p.gateway_reference
        if ref_key and str(ref_key).strip().lower() != "nan":
            norm_k = str(ref_key).strip().upper()
            pri_by_ref.setdefault(norm_k, []).append(tx_p)

    cnt_by_ref: Dict[str, List[CanonicalTransaction]] = {}
    for tx_c in unresolved_cnt:
        ref_key = tx_c.utr or tx_c.order_id or tx_c.gateway_reference
        if ref_key and str(ref_key).strip().lower() != "nan":
            norm_k = str(ref_key).strip().upper()
            cnt_by_ref.setdefault(norm_k, []).append(tx_c)

    matches: List[Dict[str, Any]] = []
    used_pri_ids = set()
    used_cnt_ids = set()

    # Iterate over shared reference clusters
    common_refs = set(pri_by_ref.keys()).intersection(set(cnt_by_ref.keys()))

    for ref_k in common_refs:
        p_cluster = [tx for tx in pri_by_ref[ref_k] if tx.transaction_id not in used_pri_ids]
        c_cluster = [tx for tx in cnt_by_ref[ref_k] if tx.transaction_id not in used_cnt_ids]

        if not p_cluster or not c_cluster:
            continue

        n_p = len(p_cluster)
        n_c = len(c_cluster)

        # 1. 1 <-> N topology (1 primary -> N counterpart rows)
        if n_p == 1 and n_c > 1:
            tx_p = p_cluster[0]
            valid_c = [tx_c for tx_c in c_cluster if candidates_compatible(tx_p, tx_c)]
            if len(valid_c) >= 2:
                sum_c = round(sum(tx_c.net_amount or 0.0 for tx_c in valid_c), 2)
                exp_p = expected_net(tx_p)
                diff = round(abs(exp_p - sum_c), 2)
                eff_tol = get_effective_tolerance(exp_p, cfg)

                if diff <= eff_tol:
                    c_ids = "|".join(sorted(tx_c.transaction_id for tx_c in valid_c))
                    c_stmts = "|".join(sorted(set(tx_c.counterpart_statement_id or "" for tx_c in valid_c if tx_c.counterpart_statement_id)))
                    max_ddiff = max(get_date_diff(tx_p.transaction_date, tx_c.transaction_date, cfg) for tx_c in valid_c)
                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "primary_transaction_id": tx_p.transaction_id,
                            "primary_statement_id": tx_p.primary_statement_id or "",
                            "counterpart_transaction_id": c_ids,
                            "counterpart_statement_id": c_stmts,
                            "match_type": "split_settlement_1toN",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "is_match": True,
                            "confidence": cfg.split_match_confidence,
                            "topology": "1_to_N"
                        })
                        used_pri_ids.add(tx_p.transaction_id)
                        used_cnt_ids.update(tx_c.transaction_id for tx_c in valid_c)

        # 2. N <-> 1 topology (N primary -> 1 counterpart row)
        elif n_p > 1 and n_c == 1:
            tx_c = c_cluster[0]
            valid_p = [tx_p for tx_p in p_cluster if candidates_compatible(tx_p, tx_c)]
            if len(valid_p) >= 2:
                sum_p = round(sum(expected_net(tx_p) for tx_p in valid_p), 2)
                c_amt = tx_c.net_amount or 0.0
                diff = round(abs(sum_p - c_amt), 2)
                eff_tol = get_effective_tolerance(c_amt, cfg)

                if diff <= eff_tol:
                    p_ids = "|".join(sorted(tx_p.transaction_id for tx_p in valid_p))
                    p_stmts = "|".join(sorted(set(tx_p.primary_statement_id or "" for tx_p in valid_p if tx_p.primary_statement_id)))
                    max_ddiff = max(get_date_diff(tx_p.transaction_date, tx_c.transaction_date, cfg) for tx_p in valid_p)
                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "primary_transaction_id": p_ids,
                            "primary_statement_id": p_stmts,
                            "counterpart_transaction_id": tx_c.transaction_id,
                            "counterpart_statement_id": tx_c.counterpart_statement_id or "",
                            "match_type": "aggregate_settlement_Nto1",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "is_match": True,
                            "confidence": cfg.n_to_1_confidence,
                            "topology": "N_to_1"
                        })
                        used_pri_ids.update(tx_p.transaction_id for tx_p in valid_p)
                        used_cnt_ids.add(tx_c.transaction_id)

        # 3. N <-> N topology (N primary -> M counterpart on shared cluster)
        elif n_p > 1 and n_c > 1:
            valid_pairs = [(tx_p, tx_c) for tx_p in p_cluster for tx_c in c_cluster if candidates_compatible(tx_p, tx_c)]
            if valid_pairs:
                valid_p_list = list({tx_p for tx_p, _ in valid_pairs})
                valid_c_list = list({tx_c for _, tx_c in valid_pairs})

                sum_p = round(sum(expected_net(tx_p) for tx_p in valid_p_list), 2)
                sum_c = round(sum(tx_c.net_amount or 0.0 for tx_c in valid_c_list), 2)
                diff = round(abs(sum_p - sum_c), 2)
                eff_tol = get_effective_tolerance(sum_p, cfg)

                if diff <= eff_tol:
                    p_ids = "|".join(sorted(tx_p.transaction_id for tx_p in valid_p_list))
                    c_ids = "|".join(sorted(tx_c.transaction_id for tx_c in valid_c_list))
                    p_stmts = "|".join(sorted(set(tx_p.primary_statement_id or "" for tx_p in valid_p_list if tx_p.primary_statement_id)))
                    c_stmts = "|".join(sorted(set(tx_c.counterpart_statement_id or "" for tx_c in valid_c_list if tx_c.counterpart_statement_id)))
                    max_ddiff = max(get_date_diff(tx_p.transaction_date, tx_c.transaction_date, cfg) for tx_p in valid_p_list for tx_c in valid_c_list)

                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "primary_transaction_id": p_ids,
                            "primary_statement_id": p_stmts,
                            "counterpart_transaction_id": c_ids,
                            "counterpart_statement_id": c_stmts,
                            "match_type": "cluster_settlement_NtoN",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "is_match": True,
                            "confidence": cfg.n_to_n_confidence,
                            "topology": "N_to_N"
                        })
                        used_pri_ids.update(tx_p.transaction_id for tx_p in valid_p_list)
                        used_cnt_ids.update(tx_c.transaction_id for tx_c in valid_c_list)

    return pd.DataFrame(matches) if matches else empty_res
