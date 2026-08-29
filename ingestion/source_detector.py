"""
source_detector.py — Ingestion Engine Stage 2 (Scored Source & Channel Detection) for Ledger AI v2.

Calculates confidence scores for candidate source_types (BANK, GATEWAY, INTERNAL_ORDER, SUBLEDGER)
and channels (UPI, CARD, NEFT, CASH, etc.) using configurable rule tables rather than hardcoded if branches.

Uses MatchingConfig thresholds:
  - top_score >= source_confidence_auto_accept (0.85) -> auto-accepted
  - source_confidence_needs_confirmation (0.60) <= top_score < 0.85 -> needs confirmation
  - top_score < 0.60 -> UNKNOWN
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from config import MatchingConfig
from ingestion.file_reader import RawTable
from schema import Channel

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "source_detection_rules.json"


@dataclass
class SourceDetectionResult:
    """
    Result container for channel detection.
    """
    channel: str
    channel_scores: Dict[str, float]
    channel_confidence: float
    needs_confirmation: bool


def _load_detection_rules() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "weights": {"filename": 0.35, "headers": 0.45, "values": 0.20},
        "channels": {}
    }


def _score_category(
    category_map: Dict[str, Dict[str, List[str]]],
    filename: str,
    headers: List[str],
    sample_values: List[str],
    weights: Dict[str, float]
) -> Tuple[Dict[str, float], str, float]:
    """
    Calculates normalized match scores for a dictionary of candidate rule definitions.
    Returns (scores_dict, top_candidate, top_score).
    """
    scores: Dict[str, float] = {}
    clean_filename = filename.lower()
    clean_headers = [str(h).strip().lower() for h in headers]
    combined_samples = " ".join(sample_values).lower()

    w_fn = weights.get("filename", 0.35)
    w_hdr = weights.get("headers", 0.45)
    w_val = weights.get("values", 0.20)

    for cand_name, rules in category_map.items():
        fn_kws = [k.lower() for k in rules.get("filename_keywords", [])]
        hdr_kws = [k.lower() for k in rules.get("header_keywords", [])]
        val_pats = rules.get("value_patterns", [])

        # 1. Filename match
        fn_match = any(k in clean_filename for k in fn_kws) if fn_kws else False
        fn_score = 1.0 if fn_match else 0.0

        # 2. Header match ratio
        hdr_hits = sum(1 for k in hdr_kws if any(k in h for h in clean_headers)) if hdr_kws else 0
        hdr_score = min(1.0, hdr_hits / min(3, len(hdr_kws))) if hdr_kws else 0.0

        # 3. Value patterns match
        val_hits = 0
        if val_pats and combined_samples:
            for pat in val_pats:
                try:
                    if re.search(pat, combined_samples, re.IGNORECASE):
                        val_hits += 1
                except Exception:
                    pass
        val_score = min(1.0, val_hits / len(val_pats)) if val_pats else 0.0

        # Composite score
        total_score = round(
            (fn_score * w_fn) + (hdr_score * w_hdr) + (val_score * w_val), 4
        )
        scores[cand_name] = total_score

    if not scores:
        return {"UNKNOWN": 0.0}, "UNKNOWN", 0.0

    sorted_cands = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_cand, top_score = sorted_cands[0]
    return scores, top_cand, top_score


def detect_source(
    raw_table: RawTable,
    cfg: Optional[MatchingConfig] = None
) -> SourceDetectionResult:
    """
    Detects channel for a RawTable with scoring breakdown.
    Applies MatchingConfig thresholds (source_confidence_auto_accept & source_confidence_needs_confirmation).
    """
    if cfg is None:
        cfg = MatchingConfig()

    rules = _load_detection_rules()
    weights = rules.get("weights", {"filename": 0.35, "headers": 0.45, "values": 0.20})

    # Collect up to 25 sample cell values across rows for pattern detection
    sample_values: List[str] = []
    for row in raw_table.rows[:5]:
        for k, v in row.items():
            if k not in ("source_file", "source_sheet", "source_row_number") and v is not None and not str(v).startswith("nan"):
                sample_values.append(str(v))

    # --- Detect Channel ---
    ch_rules = rules.get("channels", {})
    ch_scores, raw_ch_cand, raw_ch_score = _score_category(
        ch_rules, raw_table.source_file, raw_table.headers, sample_values, weights
    )

    if raw_ch_score >= cfg.source_confidence_auto_accept:
        final_ch = Channel.normalize(raw_ch_cand)
        ch_needs_confirm = False
    elif raw_ch_score >= cfg.source_confidence_needs_confirmation:
        final_ch = Channel.normalize(raw_ch_cand)
        ch_needs_confirm = True
    else:
        final_ch = "UNKNOWN"
        ch_needs_confirm = True

    return SourceDetectionResult(
        channel=final_ch,
        channel_scores=ch_scores,
        channel_confidence=raw_ch_score,
        needs_confirmation=ch_needs_confirm
    )

