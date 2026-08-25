"""
split_aggregate_matcher.py — N-Directional Split & Aggregate Matcher (T3.9) for Ledger AI v2.

Supports multi-directional transaction reconciliation:
  1. 1 <-> N (1 settlement -> N bank rows)
  2. N <-> 1 (N settlements -> 1 bank row)
  3. N <-> N (N settlements -> M bank rows, strictly constrained by shared reference/UTR cluster).

Rule: Never performs unconstrained combinatorial brute-forcing across unrelated records.
Uses candidates_compatible() for currency/status gates, expected_net() for fee calculation,
and get_effective_tolerance() for dynamic tolerance thresholds.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction
from matcher.eligibility_guards import candidates_compatible
from matcher.settlement_equation import expected_net
from matcher.tolerance_matcher import _row_to_canonical, get_effective_tolerance, get_date_diff

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"


def split_aggregate_match(
    settlements: pd.DataFrame,
    bank: pd.DataFrame,
    exact_matches: Optional[pd.DataFrame] = None,
    cfg: Optional[MatchingConfig] = None
) -> pd.DataFrame:
    """
    Executes N-directional split and aggregate matching between settlements and bank rows.
    """
    if cfg is None:
        cfg = MatchingConfig()

    resolved_settlements = set(exact_matches["settlement_id"]) if exact_matches is not None and not exact_matches.empty else set()
    resolved_bank = set(exact_matches["bank_transaction_id"]) if exact_matches is not None and not exact_matches.empty else set()

    unresolved_s = settlements[~settlements["settlement_id"].isin(resolved_settlements)] if not settlements.empty else pd.DataFrame()
    available_b = bank[~bank["bank_transaction_id"].isin(resolved_bank)] if not bank.empty else pd.DataFrame()

    empty_res = pd.DataFrame(columns=["settlement_id", "bank_transaction_id", "match_type", "amount_difference", "date_difference_days", "confidence", "topology"])

    if unresolved_s.empty or available_b.empty:
        return empty_res

    # Pre-cluster by normalized reference (UTR / order_id / gateway_ref)
    s_by_ref: Dict[str, List[CanonicalTransaction]] = {}
    for _, s_row in unresolved_s.iterrows():
        tx_s = _row_to_canonical(s_row, "settlement_id")
        ref_key = tx_s.utr or tx_s.order_id or tx_s.gateway_reference
        if ref_key and str(ref_key).strip().lower() != "nan":
            norm_k = str(ref_key).strip().upper()
            s_by_ref.setdefault(norm_k, []).append(tx_s)

    b_by_ref: Dict[str, List[CanonicalTransaction]] = {}
    for _, b_row in available_b.iterrows():
        tx_b = _row_to_canonical(b_row, "bank_transaction_id")
        ref_key = tx_b.utr or tx_b.order_id or tx_b.gateway_reference
        if ref_key and str(ref_key).strip().lower() != "nan":
            norm_k = str(ref_key).strip().upper()
            b_by_ref.setdefault(norm_k, []).append(tx_b)

    matches: List[Dict[str, Any]] = []
    used_s_ids = set()
    used_b_ids = set()

    # Iterate over shared reference clusters
    common_refs = set(s_by_ref.keys()).intersection(set(b_by_ref.keys()))

    for ref_k in common_refs:
        s_cluster = [tx for tx in s_by_ref[ref_k] if tx.transaction_id not in used_s_ids]
        b_cluster = [tx for tx in b_by_ref[ref_k] if tx.transaction_id not in used_b_ids]

        if not s_cluster or not b_cluster:
            continue

        n_s = len(s_cluster)
        n_b = len(b_cluster)

        # 1. 1 <-> N topology (1 settlement -> N bank rows)
        if n_s == 1 and n_b > 1:
            tx_s = s_cluster[0]
            valid_b = [tx_b for tx_b in b_cluster if candidates_compatible(tx_s, tx_b)]
            if len(valid_b) >= 2:
                sum_b = round(sum(tx_b.net_amount or 0.0 for tx_b in valid_b), 2)
                exp_s = expected_net(tx_s)
                diff = round(abs(exp_s - sum_b), 2)
                eff_tol = get_effective_tolerance(exp_s, cfg)

                if diff <= eff_tol:
                    b_ids = "|".join(sorted(tx_b.transaction_id for tx_b in valid_b))
                    max_ddiff = max(get_date_diff(tx_s.transaction_date, tx_b.transaction_date, cfg) for tx_b in valid_b)
                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "settlement_id": tx_s.transaction_id,
                            "bank_transaction_id": b_ids,
                            "match_type": "split_settlement_1toN",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "confidence": 0.95,
                            "topology": "1_to_N"
                        })
                        used_s_ids.add(tx_s.transaction_id)
                        used_b_ids.update(tx_b.transaction_id for tx_b in valid_b)

        # 2. N <-> 1 topology (N settlements -> 1 bank row)
        elif n_s > 1 and n_b == 1:
            tx_b = b_cluster[0]
            valid_s = [tx_s for tx_s in s_cluster if candidates_compatible(tx_s, tx_b)]
            if len(valid_s) >= 2:
                sum_s = round(sum(expected_net(tx_s) for tx_s in valid_s), 2)
                b_amt = tx_b.net_amount or 0.0
                diff = round(abs(sum_s - b_amt), 2)
                eff_tol = get_effective_tolerance(b_amt, cfg)

                if diff <= eff_tol:
                    s_ids = "|".join(sorted(tx_s.transaction_id for tx_s in valid_s))
                    max_ddiff = max(get_date_diff(tx_s.transaction_date, tx_b.transaction_date, cfg) for tx_s in valid_s)
                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "settlement_id": s_ids,
                            "bank_transaction_id": tx_b.transaction_id,
                            "match_type": "aggregate_settlement_Nto1",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "confidence": 0.95,
                            "topology": "N_to_1"
                        })
                        used_s_ids.update(tx_s.transaction_id for tx_s in valid_s)
                        used_b_ids.add(tx_b.transaction_id)

        # 3. N <-> N topology (N settlements -> M bank rows on shared cluster)
        elif n_s > 1 and n_b > 1:
            # Compatible matrix filter
            valid_pairs = [(tx_s, tx_b) for tx_s in s_cluster for tx_b in b_cluster if candidates_compatible(tx_s, tx_b)]
            if valid_pairs:
                valid_s_list = list({tx_s for tx_s, _ in valid_pairs})
                valid_b_list = list({tx_b for _, tx_b in valid_pairs})

                sum_s = round(sum(expected_net(tx_s) for tx_s in valid_s_list), 2)
                sum_b = round(sum(tx_b.net_amount or 0.0 for tx_b in valid_b_list), 2)
                diff = round(abs(sum_s - sum_b), 2)
                eff_tol = get_effective_tolerance(sum_s, cfg)

                if diff <= eff_tol:
                    s_ids = "|".join(sorted(tx_s.transaction_id for tx_s in valid_s_list))
                    b_ids = "|".join(sorted(tx_b.transaction_id for tx_b in valid_b_list))
                    max_ddiff = max(get_date_diff(tx_s.transaction_date, tx_b.transaction_date, cfg) for tx_s in valid_s_list for tx_b in valid_b_list)

                    if max_ddiff <= cfg.date_tolerance_days:
                        matches.append({
                            "settlement_id": s_ids,
                            "bank_transaction_id": b_ids,
                            "match_type": "cluster_settlement_NtoN",
                            "amount_difference": diff,
                            "date_difference_days": max_ddiff,
                            "confidence": 0.90,
                            "topology": "N_to_N"
                        })
                        used_s_ids.update(tx_s.transaction_id for tx_s in valid_s_list)
                        used_b_ids.update(tx_b.transaction_id for tx_b in valid_b_list)

    return pd.DataFrame(matches) if matches else empty_res
