"""
column_mapper.py — Ingestion Engine Stage 3 (Three-Stage Column Mapping) for Ledger AI v2.

Maps raw header strings to CanonicalTransaction fields using a 3-stage pipeline:
  Stage 3A: Exact match against configurable alias table (config/column_aliases.json) -> confidence 1.0, method "exact_alias".
  Stage 3B: Fuzzy string similarity fallback -> confidence 0.6-0.9, method "fuzzy".
  Stage 3C: Log low-confidence / unmapped headers to unmapped_headers.log instead of silently dropping them.

Thresholds are governed by MatchingConfig (column_mapping_confidence_floor).
"""

import json
import logging
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import MatchingConfig
from ingestion.file_reader import RawTable

ALIAS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "column_aliases.json"
LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
LOG_FILE = LOG_DIR / "unmapped_headers.log"


@dataclass
class ColumnMapping:
    """
    Metadata describing the mapping of a raw file column to a canonical field.
    """
    field: str
    source_column: str
    method: str  # "exact_alias" | "fuzzy" | "semantic"
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_column_aliases() -> Dict[str, List[str]]:
    if ALIAS_CONFIG_PATH.exists():
        try:
            with open(ALIAS_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k: v for k, v in data.items() if isinstance(v, list) and k != "canonical_field_priority"}
        except Exception:
            pass
    return {}


def _log_unmapped_header(source_file: str, header: str, best_candidate: Optional[str] = None, best_confidence: float = 0.0):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    msg = f"[UNMAPPED_HEADER] file='{source_file}' header='{header}' best_match='{best_candidate or 'None'}' confidence={best_confidence:.2f}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass


def _norm_header(header: str) -> str:
    return str(header).strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def map_columns(raw_table: RawTable, cfg: Optional[MatchingConfig] = None) -> List[ColumnMapping]:
    """
    Maps raw table headers to CanonicalTransaction field names.
    Returns a list of ColumnMapping objects.
    """
    if cfg is None:
        cfg = MatchingConfig()

    aliases = _load_column_aliases()
    mappings: List[ColumnMapping] = []
    mapped_canonical_fields = set()

    # Pre-build lookup for exact alias matching (normalized_alias -> canonical_field)
    alias_lookup: Dict[str, str] = {}
    for canonical_field, alias_list in aliases.items():
        for alias in alias_list:
            alias_lookup[_norm_header(alias)] = canonical_field

    unmapped_headers: List[str] = []

    # --- Stage 3A: Exact Alias Matching ---
    for raw_hdr in raw_table.headers:
        norm = _norm_header(raw_hdr)
        if norm in alias_lookup:
            c_field = alias_lookup[norm]
            if c_field not in mapped_canonical_fields:
                mappings.append(
                    ColumnMapping(
                        field=c_field,
                        source_column=raw_hdr,
                        method="exact_alias",
                        confidence=1.0
                    )
                )
                mapped_canonical_fields.add(c_field)
                continue

        unmapped_headers.append(raw_hdr)

    # --- Stage 3B: Fuzzy String Similarity Fallback ---
    still_unmapped: List[str] = []
    for raw_hdr in unmapped_headers:
        norm = _norm_header(raw_hdr)
        best_field: Optional[str] = None
        best_sim: float = 0.0

        for canonical_field, alias_list in aliases.items():
            if canonical_field in mapped_canonical_fields:
                continue
            
            # Skip financial amount mapping for account balance columns
            if "balance" in norm and canonical_field in ("net_amount", "gross_amount", "credit_amount", "debit_amount", "fee_amount", "tax_amount"):
                continue

            # Skip fuzzy mapping for count / quantity columns (e.g. # Transactions, Txn Count, Qty)
            if any(k in norm for k in ("count", "#", "qty", "quantity", "num_", "number_of", "no_of", "txns")):
                continue

            # Check similarity against canonical field name and its aliases
            candidates = [canonical_field] + alias_list
            for cand in candidates:
                cand_norm = _norm_header(cand)
                ratio = SequenceMatcher(None, norm, cand_norm).ratio()
                if ratio > best_sim:
                    best_sim = ratio
                    best_field = canonical_field

        if best_field and best_sim >= cfg.column_mapping_confidence_floor:
            mappings.append(
                ColumnMapping(
                    field=best_field,
                    source_column=raw_hdr,
                    method="fuzzy",
                    confidence=round(best_sim, 2)
                )
            )
            mapped_canonical_fields.add(best_field)
        else:
            still_unmapped.append(raw_hdr)
            _log_unmapped_header(
                source_file=raw_table.source_file,
                header=raw_hdr,
                best_candidate=best_field,
                best_confidence=best_sim
            )

    return mappings
