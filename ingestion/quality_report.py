"""
quality_report.py — Ingestion Engine Stage 6 (Data Quality Report) for Ledger AI v2.

Generates a source-agnostic QualityReport summarizing completeness, missing fields,
invalid dates, duplicates, and generic dataset health warnings across CanonicalTransaction rows.

Rule: Warning logic must be generic (e.g. "field X is missing on N% of rows"), with no source-specific hardcoded checks.
"""

import dateutil.parser
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

from schema import CanonicalTransaction
from ingestion.source_detector import SourceDetectionResult


@dataclass
class QualityReport:
    """
    Data quality and health report for an ingested dataset.
    """
    rows_detected: int
    valid_transactions: int
    ignored_rows: int
    missing_transaction_ids: int
    missing_dates: int
    missing_amounts: int
    invalid_dates: int
    duplicate_ids: int
    source_confidence: float
    schema_confidence: float
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_valid_date(date_str: Optional[str]) -> bool:
    if not date_str:
        return False
    try:
        dateutil.parser.parse(str(date_str))
        return True
    except Exception:
        return False


def build_quality_report(
    canonical_rows: List[CanonicalTransaction],
    source_detection: Optional[SourceDetectionResult] = None
) -> QualityReport:
    """
    Builds a QualityReport instance for a list of CanonicalTransaction records.
    """
    total_rows = len(canonical_rows)
    if total_rows == 0:
        return QualityReport(
            rows_detected=0,
            valid_transactions=0,
            ignored_rows=0,
            missing_transaction_ids=0,
            missing_dates=0,
            missing_amounts=0,
            invalid_dates=0,
            duplicate_ids=0,
            source_confidence=source_detection.channel_confidence if source_detection else 0.0,
            schema_confidence=0.0,
            warnings=["Dataset is empty."]
        )

    missing_ids = 0
    missing_dates = 0
    missing_amounts = 0
    invalid_dates = 0
    seen_ids = set()
    duplicate_ids = 0
    valid_tx_count = 0

    field_presence_counts: Dict[str, int] = {
        "transaction_date": 0,
        "net_amount": 0,
        "utr": 0,
        "order_id": 0,
        "settlement_id": 0,
        "description": 0,
        "customer_name": 0,
        "status": 0
    }

    for tx in canonical_rows:
        # Check ID
        if not tx.transaction_id:
            missing_ids += 1
        elif tx.transaction_id in seen_ids:
            duplicate_ids += 1
        else:
            seen_ids.add(tx.transaction_id)

        # Check Date
        if not tx.transaction_date:
            missing_dates += 1
        elif not _is_valid_date(tx.transaction_date):
            invalid_dates += 1
        else:
            field_presence_counts["transaction_date"] += 1

        # Check Amount
        if tx.net_amount is None and tx.gross_amount is None and tx.credit_amount is None and tx.debit_amount is None:
            missing_amounts += 1
        else:
            field_presence_counts["net_amount"] += 1

        # Check presence of optional attributes for generic warning metrics
        if tx.utr:
            field_presence_counts["utr"] += 1
        if tx.order_id:
            field_presence_counts["order_id"] += 1
        if tx.settlement_id:
            field_presence_counts["settlement_id"] += 1
        if tx.description:
            field_presence_counts["description"] += 1
        if tx.customer_name:
            field_presence_counts["customer_name"] += 1
        if tx.status:
            field_presence_counts["status"] += 1

        # Valid transaction definition
        if tx.transaction_id and (tx.net_amount is not None or tx.gross_amount is not None) and tx.transaction_date:
            valid_tx_count += 1

    # Generic Warnings Generation (Threshold: field present in < 30% of non-empty dataset rows)
    warnings: List[str] = []
    if missing_ids > 0:
        warnings.append(f"{missing_ids} row(s) missing primary transaction IDs.")
    if duplicate_ids > 0:
        warnings.append(f"{duplicate_ids} duplicate transaction ID(s) detected.")
    if invalid_dates > 0:
        warnings.append(f"{invalid_dates} row(s) contain unparseable date formats.")

    for field_name, count in field_presence_counts.items():
        pct = (count / total_rows) * 100.0
        if pct < 30.0 and total_rows >= 5:
            warnings.append(f"Field '{field_name}' is sparse (populated in only {pct:.1f}% of rows).")

    # Schema confidence metric
    core_present = field_presence_counts["transaction_date"] + field_presence_counts["net_amount"]
    schema_confidence = round(min(1.0, core_present / (total_rows * 2)), 4)

    src_confidence = source_detection.channel_confidence if source_detection else 1.0

    return QualityReport(
        rows_detected=total_rows,
        valid_transactions=valid_tx_count,
        ignored_rows=total_rows - valid_tx_count,
        missing_transaction_ids=missing_ids,
        missing_dates=missing_dates,
        missing_amounts=missing_amounts,
        invalid_dates=invalid_dates,
        duplicate_ids=duplicate_ids,
        source_confidence=src_confidence,
        schema_confidence=schema_confidence,
        warnings=warnings
    )
