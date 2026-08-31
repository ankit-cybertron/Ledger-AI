"""
scoring_engine.py — Dynamic Evidence-Weighted Scoring Engine (T3B.3) for Ledger AI v2.

Replaces flat, stage-based confidence constants with dynamic evidence scoring.
Computes a weighted confidence score derived from identifier matching strength,
amount precision, date proximity, and narration similarity.
"""

from dataclasses import dataclass
from typing import Optional
from config import MatchingConfig


@dataclass
class MatchEvidence:
    """
    Evidence bundle captured per match candidate pair.
    """
    identifier_match_type: str = "none"  # "exact_utr", "exact_rrn", "exact_order_id", "partial", "none"
    amount_diff: float = 0.0
    date_diff_days: int = 0
    narration_similarity: float = 0.0
    currency_match: bool = True
    direction_match: bool = True


def compute_confidence(evidence: MatchEvidence, cfg: Optional[MatchingConfig] = None) -> float:
    """
    Computes a weighted confidence score from evidence signals per T3B.3.
    """
    if cfg is None:
        cfg = MatchingConfig()

    w_id = getattr(cfg, "scoring_weight_identifier", 0.40)
    w_amt = getattr(cfg, "scoring_weight_amount", 0.30)
    w_date = getattr(cfg, "scoring_weight_date", 0.15)
    w_narr = getattr(cfg, "scoring_weight_narration", 0.15)

    # 1. Identifier Subscore
    id_type = str(evidence.identifier_match_type or "none").lower()
    if id_type in ["exact", "exact_match", "exact_utr", "exact_rrn", "exact_utr_match"]:
        s_id = 1.00

    elif id_type in ["exact_order_id", "exact_order_id_match", "exact_order_in_bank_description"]:
        s_id = 0.95
    elif id_type in ["partial", "order_subledger_date_match"]:
        s_id = 0.60
    else:
        s_id = 0.00

    # 2. Amount Subscore
    amt_diff = abs(float(evidence.amount_diff or 0.0))
    abs_tol = float(cfg.absolute_amount_tolerance if cfg.absolute_amount_tolerance is not None else 1.00)
    if amt_diff == 0.0:
        s_amt = 1.00
    elif abs_tol > 0 and amt_diff <= abs_tol:
        s_amt = max(0.50, 1.00 - (amt_diff / (2.0 * abs_tol)))
    elif id_type in ["exact", "exact_match", "exact_utr", "exact_rrn", "exact_utr_match", "exact_order_id", "exact_order_id_match"]:
        # Exact identifier match with amount variance represents a gateway fee / MDR deduction
        s_amt = 0.80
    else:
        s_amt = 0.00

    # 3. Date Subscore
    ddiff = abs(int(evidence.date_diff_days or 0))
    date_tol = int(cfg.date_tolerance_days if cfg.date_tolerance_days is not None else 3)
    if ddiff == 0:
        s_date = 1.00
    elif date_tol > 0 and ddiff <= date_tol:
        s_date = max(0.50, 1.00 - (ddiff / (2.0 * date_tol)))
    else:
        s_date = 0.00

    # 4. Narration Subscore
    s_narr = min(1.00, max(0.00, float(evidence.narration_similarity or 0.0)))

    # Weighted Total Score
    total_score = (s_id * w_id) + (s_amt * w_amt) + (s_date * w_date) + (s_narr * w_narr)

    # Incompatibility penalty
    if not evidence.currency_match or not evidence.direction_match:
        penalty = float(getattr(cfg, "incompatibility_penalty", 0.50))
        total_score *= penalty

    return round(min(1.00, max(0.00, total_score)), 4)
