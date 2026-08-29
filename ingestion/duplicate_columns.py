"""
duplicate_columns.py — Ingestion Engine Stage (Duplicate Column Detection) for Ledger AI v2.

Detects functionally redundant columns within an uploaded statement:
If two columns contain identical values (after normalization) across all rows,
drops the lower-priority column according to the priority rules in config/column_aliases.json.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "column_aliases.json"


def _load_field_priority() -> List[str]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("canonical_field_priority", [])
        except Exception:
            pass
    return [
        "utr", "order_id", "settlement_id", "auth_code",
        "transaction_date", "value_date", "net_amount", "gross_amount",
        "credit_amount", "debit_amount", "fee_amount", "tax_amount",
        "customer_name", "description", "status", "currency"
    ]


def _normalize_cell_value(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("nan", "none", "null", ""):
        return ""
    # Strip currency symbols and commas for amount comparisons
    s = re.sub(r"[₹$,]", "", s).strip()
    return s


def detect_duplicate_columns(
    mapped_rows: List[Dict[str, Any]],
    column_mapping_dict: Optional[Dict[str, str]] = None
) -> Tuple[List[str], List[str]]:
    """
    Scans a list of row dicts for duplicate columns with identical values in every row.

    Args:
        mapped_rows: List of row dictionaries from an uploaded file.
        column_mapping_dict: Optional dict mapping raw column name -> mapped canonical field name.

    Returns:
        Tuple of (dropped_column_names, drop_explanations).
    """
    if not mapped_rows or len(mapped_rows) == 0:
        return [], []

    # Exclude internal metadata keys
    ignored_keys = {"source_file", "source_sheet", "source_row_number", "source_page", "is_primary"}
    sample_row = mapped_rows[0]
    candidate_cols = [c for c in sample_row.keys() if c not in ignored_keys]

    field_priority = _load_field_priority()
    col_mapping = column_mapping_dict or {}

    def get_priority(col_name: str) -> int:
        mapped_field = col_mapping.get(col_name, col_name.lower())
        if mapped_field in field_priority:
            return field_priority.index(mapped_field)
        return 999  # Lower priority for generic/unmapped fields

    dropped_cols: List[str] = []
    explanations: List[str] = []
    active_cols = list(candidate_cols)

    i = 0
    while i < len(active_cols):
        col_a = active_cols[i]
        if col_a in dropped_cols:
            i += 1
            continue

        j = i + 1
        while j < len(active_cols):
            col_b = active_cols[j]
            if col_b in dropped_cols:
                j += 1
                continue

            # Compare col_a and col_b across all rows
            is_identical = True
            for r in mapped_rows:
                val_a = _normalize_cell_value(r.get(col_a))
                val_b = _normalize_cell_value(r.get(col_b))
                if val_a != val_b:
                    is_identical = False
                    break

            if is_identical:
                prio_a = get_priority(col_a)
                prio_b = get_priority(col_b)

                # Keep higher priority (lower index value)
                if prio_a <= prio_b:
                    keep_col, drop_col = col_a, col_b
                else:
                    keep_col, drop_col = col_b, col_a

                dropped_cols.append(drop_col)
                msg = f"Column '{drop_col}' was dropped — identical to '{keep_col}' for every row."
                explanations.append(msg)

                if drop_col == col_a:
                    break

            j += 1
        i += 1

    return dropped_cols, explanations
