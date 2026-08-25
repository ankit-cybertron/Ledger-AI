"""
eligibility.py — Ingestion Engine Status Eligibility Gate (T2.2) for Ledger AI v2.

Filters ingested CanonicalTransaction records based on status eligibility:
  - Excludes non-event rows (FAILED, DECLINED, CANCELLED, PENDING) from matching.
  - Excluded rows are NOT reconciliation exceptions — they are non-events that are logged for audit.
  - Excluded rows never enter matcher pipelines or Exception Ledgers.
"""

import json
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Set

from schema import CanonicalTransaction, TransactionStatus
from config import MatchingConfig

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "eligibility_rules.json"


def _load_excluded_statuses() -> Set[str]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {str(s).upper() for s in data.get("default_excluded_statuses", [])}
        except Exception:
            pass
    return {"FAILED", "DECLINED", "CANCELLED", "PENDING", "REJECTED"}


def filter_eligible(
    canonical_rows: List[CanonicalTransaction],
    cfg: Optional[MatchingConfig] = None,
    custom_excluded_statuses: Optional[Set[str]] = None
) -> Tuple[List[CanonicalTransaction], List[Dict[str, Any]]]:
    """
    Separates CanonicalTransaction rows into (eligible_transactions, excluded_records).

    Excluded rows carry audit reasons and are prevented from entering downstream
    matching pipelines or Exception Ledgers.
    """
    excluded_set = custom_excluded_statuses if custom_excluded_statuses is not None else _load_excluded_statuses()

    eligible: List[CanonicalTransaction] = []
    excluded: List[Dict[str, Any]] = []

    for tx in canonical_rows:
        norm_status = TransactionStatus.normalize(tx.status) if tx.status else None

        if norm_status and norm_status in excluded_set:
            excluded.append(
                {
                    "transaction_id": tx.transaction_id,
                    "source_file": tx.source_file,
                    "source_row_number": tx.source_row_number,
                    "raw_status": tx.status,
                    "normalized_status": norm_status,
                    "reason": f"Excluded from matching engine: Normalized status '{norm_status}' is in non-event exclusion set.",
                    "transaction": tx.to_dict()
                }
            )
        else:
            eligible.append(tx)

    return eligible, excluded
