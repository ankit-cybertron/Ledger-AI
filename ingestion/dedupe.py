"""
dedupe.py — Ingestion Engine Stage 7 (Duplicate Detection) for Ledger AI v2.

Performs three-stage pre-matching duplicate detection across canonical transaction rows:
  1. Exact Duplicate: Same transaction_id already present in store or batch.
  2. Probable Duplicate: Same content_hash (net_amount + transaction_date + utr/order_id + description).
  3. Duplicate Upload: Re-uploading an entire file/sheet (flagged if >80% of rows match content hashes in store).

Runs BEFORE matching, preventing re-ingestion of duplicate rows or synthetic ID generation.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Set

from schema import CanonicalTransaction


@dataclass
class DedupeReport:
    """
    Summary report of pre-matching duplicate analysis.
    """
    total_processed: int
    unique_count: int
    exact_duplicate_count: int
    probable_duplicate_count: int
    is_duplicate_upload: bool
    unique_rows: List[CanonicalTransaction]
    exact_duplicates: List[CanonicalTransaction]
    probable_duplicates: List[CanonicalTransaction]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "unique_count": self.unique_count,
            "exact_duplicate_count": self.exact_duplicate_count,
            "probable_duplicate_count": self.probable_duplicate_count,
            "is_duplicate_upload": self.is_duplicate_upload,
            "exact_duplicate_ids": [tx.transaction_id for tx in self.exact_duplicates],
            "probable_duplicate_hashes": [tx.content_hash for tx in self.probable_duplicates if tx.content_hash]
        }


def detect_duplicates(
    canonical_rows: List[CanonicalTransaction],
    existing_store_rows: Optional[List[CanonicalTransaction]] = None
) -> DedupeReport:
    """
    Analyzes incoming canonical transaction rows against batch and existing store records.
    Returns a DedupeReport separating unique_rows from exact and probable duplicates.
    """
    existing = existing_store_rows or []

    known_ids: Set[str] = {tx.transaction_id for tx in existing if tx.transaction_id}
    known_hashes: Set[str] = {tx.content_hash for tx in existing if tx.content_hash}

    seen_batch_ids: Set[str] = set()
    seen_batch_hashes: Set[str] = set()

    unique_rows: List[CanonicalTransaction] = []
    exact_duplicates: List[CanonicalTransaction] = []
    probable_duplicates: List[CanonicalTransaction] = []

    for tx in canonical_rows:
        tx_id = tx.transaction_id
        tx_hash = tx.content_hash

        # 1. Exact ID match (in store or earlier in batch)
        if tx_id and (tx_id in known_ids or tx_id in seen_batch_ids):
            exact_duplicates.append(tx)
            continue

        # 2. Probable Content Hash match (same amount + date + reference + description)
        if tx_hash and (tx_hash in known_hashes or tx_hash in seen_batch_hashes):
            probable_duplicates.append(tx)
            continue

        # Unique row
        if tx_id:
            seen_batch_ids.add(tx_id)
        if tx_hash:
            seen_batch_hashes.add(tx_hash)

        unique_rows.append(tx)

    # 3. Duplicate Upload Detection (>80% of rows already in store)
    total = len(canonical_rows)
    dup_count = len(exact_duplicates) + len(probable_duplicates)
    is_duplicate_upload = (dup_count / total >= 0.80) if total > 0 else False

    return DedupeReport(
        total_processed=total,
        unique_count=len(unique_rows),
        exact_duplicate_count=len(exact_duplicates),
        probable_duplicate_count=len(probable_duplicates),
        is_duplicate_upload=is_duplicate_upload,
        unique_rows=unique_rows,
        exact_duplicates=exact_duplicates,
        probable_duplicates=probable_duplicates
    )
