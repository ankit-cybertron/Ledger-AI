"""
similarity_engine.py — Candidate Similarity & Fuzzy Distance Engine (T3B.2) for Ledger AI v2.

Generates candidate similarity scores and feature breakdown for SIMILAR-status transactions.
Used directly by reconciler/reconcile.py and GET /api/similar-payments endpoint.
"""

from typing import Optional, List, Dict, Any, Union
import pandas as pd

from config import MatchingConfig
from schema import CanonicalTransaction, row_to_canonical
from matcher.tolerance_matcher import narration_similarity, get_date_diff
from matcher.eligibility_guards import candidates_compatible
from matcher.scoring_engine import MatchEvidence, compute_confidence


def find_similar_candidates(
    target: Union[CanonicalTransaction, Dict[str, Any]],
    candidate_pool: Union[List[Any], pd.DataFrame],
    cfg: Optional[MatchingConfig] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates a target transaction against a pool of candidate transactions.
    Returns sorted candidates with similarity scores and matching features per T3B.2.
    """
    if cfg is None:
        cfg = MatchingConfig()

    tx_target = row_to_canonical(target, "target_tx")

    if candidate_pool is None:
        cands = []
    elif isinstance(candidate_pool, pd.DataFrame):
        cands = [row_to_canonical(row, "cand_tx") for _, row in candidate_pool.iterrows()]
    else:
        cands = [row_to_canonical(item, "cand_tx") for item in candidate_pool]

    results = []
    min_score = getattr(cfg, "similarity_minimum_score", 0.40)

    for tx_cand in cands:
        if tx_target.transaction_id == tx_cand.transaction_id:
            continue

        if not candidates_compatible(tx_target, tx_cand):
            continue

        matching_features = []

        # Amount check
        t_amt = float(tx_target.net_amount or 0.0)
        c_amt = float(tx_cand.net_amount or 0.0)
        amt_diff = abs(t_amt - c_amt)
        if amt_diff == 0.0:
            matching_features.append("exact_amount")
        elif amt_diff <= cfg.absolute_amount_tolerance:
            matching_features.append("within_amount_tolerance")

        # Identifier check
        min_id_len = getattr(cfg, "minimum_identifier_length", 5)
        id_type = "none"
        
        t_utr_norm = str(tx_target.utr or "").strip().lower()
        c_utr_norm = str(tx_cand.utr or "").strip().lower()
        t_ord_norm = str(tx_target.order_id or "").strip().lower()
        c_ord_norm = str(tx_cand.order_id or "").strip().lower()

        if t_utr_norm and c_utr_norm and len(t_utr_norm) >= min_id_len and t_utr_norm == c_utr_norm:
            id_type = "exact_utr"
            matching_features.append("exact_utr")
        elif t_ord_norm and c_ord_norm and len(t_ord_norm) >= min_id_len and t_ord_norm == c_ord_norm:
            id_type = "exact_order_id"
            matching_features.append("exact_order_id")
        elif tx_target.description and tx_cand.description:
            t_desc = str(tx_target.description).upper().strip()
            c_desc = str(tx_cand.description).upper().strip()
            if len(t_desc) >= 4 and len(c_desc) >= 4 and (t_desc in c_desc or c_desc in t_desc):
                id_type = "partial"
                matching_features.append("partial_narration_match")

        # Date diff check
        ddiff = get_date_diff(tx_target.transaction_date, tx_cand.transaction_date, cfg)
        if ddiff <= cfg.date_tolerance_days:
            matching_features.append(f"date_proximity_{ddiff}d")

        # Narration similarity
        narr_sim = narration_similarity(tx_target.description or tx_target.utr, tx_cand.description or tx_cand.utr)
        if narr_sim >= cfg.narration_similarity_threshold:
            matching_features.append(f"narration_similarity_{narr_sim}")

        # Fee Variance / Deduction Detection
        if id_type != "none" and amt_diff > 0.0:
            matching_features.append(f"fee_variance_₹{amt_diff:.2f}")

        # Need at least amount closeness or identifier or narration match to be SIMILAR
        if not matching_features:
            continue

        evidence = MatchEvidence(
            identifier_match_type=id_type,
            amount_diff=amt_diff,
            date_diff_days=ddiff,
            narration_similarity=narr_sim,
            currency_match=True,
            direction_match=True
        )

        score = compute_confidence(evidence, cfg)

        if score >= min_score:
            cand_stmt = tx_cand.counterpart_statement_id or tx_cand.primary_statement_id or ""
            src_name = getattr(tx_cand, "source_name", "") or getattr(tx_cand, "statement_name", "")
            src_color = getattr(tx_cand, "source_color", "") or "#3b82f6"
            results.append({
                "id": tx_cand.transaction_id,
                "candidate_id": tx_cand.transaction_id,
                "statement_id": cand_stmt,
                "source_name": src_name,
                "source_color": src_color,
                "amount": float(tx_cand.net_amount or 0.0),
                "date": tx_cand.transaction_date or "",
                "description": tx_cand.description or "",
                "utr": tx_cand.utr or "",
                "order_id": tx_cand.order_id or "",
                "similarity_score": score,
                "amount_difference": round(amt_diff, 2),
                "date_difference_days": ddiff,
                "narration_similarity": narr_sim,
                "matching_features": matching_features,
            })

    results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return results
