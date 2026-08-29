"""
reconcile.py — Reconciliation Pipeline Orchestrator (v2 extended with Part 3B Four-Status Taxonomy) for Ledger AI v2.

Orchestrates multi-stage reconciliation:
  Stage 1: Deterministic Exact Matches (primary <-> counterpart)
  Stage 2: Dynamic Tolerance & Split Matches (1:1, 1:N, N:1, N:N)
  Stage 3: ML Confidence Matching (batch thresholding)
  Stage 4: Similarity Scan for Unmatched Primary Records -> SIMILAR or UNMATCHED

Four Status Taxonomy (T3B.1):
  - SETTLED: Matched and involves a primary statement transaction.
  - MATCHED: Matched counterpart-to-counterpart (neither side primary).
  - SIMILAR: Unmatched primary record with candidates cleared by similarity engine.
  - UNMATCHED: Zero matching features found.

Rule 7(d): LLM matching is manual-review-only, invoked on-demand from the UI, NOT as part of this batch pipeline.
Persists reconciliation_config.json on every run.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from datetime import datetime
import json
from typing import Optional, List, Dict, Any, Set

import pandas as pd
from dotenv import load_dotenv

from config import MatchingConfig
from schema import row_to_canonical
from matcher.exact_matcher import exact_match
from matcher.tolerance_matcher import tolerance_match
from matcher.similarity_engine import find_similar_candidates
from reconciler.settlement_status import evaluate_period_settlement

load_dotenv(ROOT / ".env")

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"
ML_DIR = ROOT / "data" / "ml"

EXACT_RESULTS_PATH = RESULTS_DIR / "exact_matches.csv"
TOLERANCE_RESULTS_PATH = RESULTS_DIR / "tolerance_matches.csv"
CONFIDENCE_RESULTS_PATH = ML_DIR / "confidence_predictions.csv"
OUTPUT_PATH = RESULTS_DIR / "reconciliation_results.csv"
CONFIG_OUTPUT_PATH = RESULTS_DIR / "reconciliation_config.json"


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _get_primary_statement_ids() -> Set[str]:
    primary_ids = set()
    db_path = ROOT / "frontend" / "data" / "statements_db.json"
    if db_path.exists():
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for stmt_id, stmt in data.items():
                    if stmt.get("is_primary"):
                        primary_ids.add(str(stmt_id))
        except Exception:
            pass

    pri_csv = GENERATED_DIR / "primary_records.csv"
    if pri_csv.exists():
        try:
            df = pd.read_csv(pri_csv)
            for col in ["primary_statement_id", "statement_id"]:
                if col in df.columns:
                    primary_ids.update(df[col].dropna().astype(str))
        except Exception:
            pass
    return primary_ids


def reconcile(cfg: Optional[MatchingConfig] = None) -> pd.DataFrame:
    """
    Orchestrates universal multi-source reconciliation across all uploaded statements (T3B.1).
    - If primary statement(s) exist (is_primary=True): Primary vs Counterparts -> SETTLED.
    - Counterparts vs Counterparts (or all statements if no primary set) -> MATCHED.
    - Unresolved records scanned across all other statement sources -> SIMILAR or UNMATCHED.
    """
    if cfg is None:
        cfg = MatchingConfig.load_with_env_overrides()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg.save(CONFIG_OUTPUT_PATH)

    from frontend import statement_store

    all_stmts_meta = statement_store.list_statements()
    all_stmts = []
    for s in all_stmts_meta:
        sdetail = statement_store.get_statement(s["id"])
        rows = sdetail.get("rows", []) if sdetail else []
        clean_rows = [r for r in rows if not statement_store._is_summary_dict_row(r)]
        all_stmts.append({
            "id": str(s["id"]),
            "name": str(s.get("name") or s.get("filename") or f"Statement {s['id']}"),
            "is_primary": bool(s.get("is_primary", False)),
            "rows": clean_rows,
            "txs": [row_to_canonical(r, "tx") for r in clean_rows]
        })

    pri_stmts = [s for s in all_stmts if s["is_primary"]]
    cnt_stmts = [s for s in all_stmts if not s["is_primary"]]

    resolved_ids = set()
    final_results = []

    def to_df(tx_list):
        if not tx_list:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in tx_list])

    # Pass 1: Primary vs Counterpart matching (if primary statement exists)
    if pri_stmts:
        pri_txs = [t for s in pri_stmts for t in s["txs"]]
        cnt_txs = [t for s in cnt_stmts for t in s["txs"]]

        em_df = exact_match(to_df(pri_txs), to_df(cnt_txs), cfg)
        if not em_df.empty:
            for _, r in em_df.iterrows():
                p_id = str(r["primary_transaction_id"])
                c_id = str(r["counterpart_transaction_id"])
                ps_id = str(r.get("primary_statement_id", ""))
                cs_id = str(r.get("counterpart_statement_id", ""))
                resolved_ids.add(p_id)
                resolved_ids.add(c_id)
                final_results.append({
                    "primary_transaction_id": p_id,
                    "primary_statement_id": ps_id,
                    "counterpart_transaction_id": c_id,
                    "counterpart_statement_id": cs_id,
                    "settlement_id": p_id,
                    "bank_transaction_id": c_id,
                    "stage": "exact",
                    "decision": "match",
                    "confidence": float(r.get("confidence", 1.0)),
                    "reason": "Exact deterministic match with primary statement.",
                    "status": "SETTLED"
                })

        unres_pri = [t for t in pri_txs if t.transaction_id not in resolved_ids]
        unres_cnt = [t for t in cnt_txs if t.transaction_id not in resolved_ids]
        if unres_pri and unres_cnt:
            tm_df, _ = tolerance_match(to_df(unres_pri), to_df(unres_cnt), cfg=cfg)
            if not tm_df.empty:
                for _, r in tm_df.iterrows():
                    p_id = str(r["primary_transaction_id"])
                    c_id = str(r["counterpart_transaction_id"])
                    ps_id = str(r.get("primary_statement_id", ""))
                    cs_id = str(r.get("counterpart_statement_id", ""))
                    resolved_ids.add(p_id)
                    resolved_ids.add(c_id)
                    final_results.append({
                        "primary_transaction_id": p_id,
                        "primary_statement_id": ps_id,
                        "counterpart_transaction_id": c_id,
                        "counterpart_statement_id": cs_id,
                        "settlement_id": p_id,
                        "bank_transaction_id": c_id,
                        "stage": "tolerance",
                        "decision": "match",
                        "confidence": float(r.get("confidence", 0.85)),
                        "reason": "Tolerance-stage match with primary statement.",
    # Pass 1B: Primary vs Primary matching (Inter-bank transfers between multiple primary statements)
    if len(pri_stmts) > 1:
        for i in range(len(pri_stmts)):
            for j in range(i + 1, len(pri_stmts)):
                p1 = pri_stmts[i]
                p2 = pri_stmts[j]
                unres_1 = [t for t in p1["txs"] if t.transaction_id not in resolved_ids]
                unres_2 = [t for t in p2["txs"] if t.transaction_id not in resolved_ids]
                if not unres_1 or not unres_2:
                    continue

                em_df = exact_match(to_df(unres_1), to_df(unres_2), cfg)
                if not em_df.empty:
                    for _, r in em_df.iterrows():
                        p_id = str(r["primary_transaction_id"])
                        c_id = str(r["counterpart_transaction_id"])
                        resolved_ids.add(p_id)
                        resolved_ids.add(c_id)
                        final_results.append({
                            "primary_transaction_id": p_id,
                            "primary_statement_id": p1["id"],
                            "counterpart_transaction_id": c_id,
                            "counterpart_statement_id": p2["id"],
                            "settlement_id": p_id,
                            "bank_transaction_id": c_id,
                            "stage": "exact",
                            "decision": "match",
                            "confidence": float(r.get("confidence", 1.0)),
                            "reason": f"Exact match between primary sources ({p1['name']} vs {p2['name']}).",
                            "status": "SETTLED"
                        })

                unres_1_rem = [t for t in p1["txs"] if t.transaction_id not in resolved_ids]
                unres_2_rem = [t for t in p2["txs"] if t.transaction_id not in resolved_ids]
                if unres_1_rem and unres_2_rem:
                    tm_df, _ = tolerance_match(to_df(unres_1_rem), to_df(unres_2_rem), cfg=cfg)
                    if not tm_df.empty:
                        for _, r in tm_df.iterrows():
                            p_id = str(r["primary_transaction_id"])
                            c_id = str(r["counterpart_transaction_id"])
                            resolved_ids.add(p_id)
                            resolved_ids.add(c_id)
                            final_results.append({
                                "primary_transaction_id": p_id,
                                "primary_statement_id": p1["id"],
                                "counterpart_transaction_id": c_id,
                                "counterpart_statement_id": p2["id"],
                                "settlement_id": p_id,
                                "bank_transaction_id": c_id,
                                "stage": "tolerance",
                                "decision": "match",
                                "confidence": float(r.get("confidence", 0.85)),
                                "reason": f"Tolerance match between primary sources ({p1['name']} vs {p2['name']}).",
                                "status": "SETTLED"
                            })

    # Pass 2: Counterpart vs Counterpart (or Multi-Source Pairwise matching if no primary statement)
    match_sources = cnt_stmts if pri_stmts else all_stmts
    for i in range(len(match_sources)):
        for j in range(i + 1, len(match_sources)):
            s1 = match_sources[i]
            s2 = match_sources[j]

            unres_1 = [t for t in s1["txs"] if t.transaction_id not in resolved_ids]
            unres_2 = [t for t in s2["txs"] if t.transaction_id not in resolved_ids]
            if not unres_1 or not unres_2:
                continue

            em_df = exact_match(to_df(unres_1), to_df(unres_2), cfg)
            if not em_df.empty:
                for _, r in em_df.iterrows():
                    p_id = str(r["primary_transaction_id"])
                    c_id = str(r["counterpart_transaction_id"])
                    resolved_ids.add(p_id)
                    resolved_ids.add(c_id)
                    final_results.append({
                        "primary_transaction_id": p_id,
                        "primary_statement_id": s1["id"],
                        "counterpart_transaction_id": c_id,
                        "counterpart_statement_id": s2["id"],
                        "settlement_id": p_id,
                        "bank_transaction_id": c_id,
                        "stage": "exact",
                        "decision": "match",
                        "confidence": float(r.get("confidence", 1.0)),
                        "reason": f"Exact match between non-primary sources ({s1['name']} vs {s2['name']}).",
                        "status": "MATCHED"
                    })

            unres_1_rem = [t for t in s1["txs"] if t.transaction_id not in resolved_ids]
            unres_2_rem = [t for t in s2["txs"] if t.transaction_id not in resolved_ids]
            if unres_1_rem and unres_2_rem:
                tm_df, _ = tolerance_match(to_df(unres_1_rem), to_df(unres_2_rem), cfg=cfg)
                if not tm_df.empty:
                    for _, r in tm_df.iterrows():
                        p_id = str(r["primary_transaction_id"])
                        c_id = str(r["counterpart_transaction_id"])
                        resolved_ids.add(p_id)
                        resolved_ids.add(c_id)
                        final_results.append({
                            "primary_transaction_id": p_id,
                            "primary_statement_id": s1["id"],
                            "counterpart_transaction_id": c_id,
                            "counterpart_statement_id": s2["id"],
                            "settlement_id": p_id,
                            "bank_transaction_id": c_id,
                            "stage": "tolerance",
                            "decision": "match",
                            "confidence": float(r.get("confidence", 0.85)),
                            "reason": f"Tolerance match between non-primary sources ({s1['name']} vs {s2['name']}).",
                            "status": "MATCHED"
                        })

    # Pass 3: Universal Similar & Unmatched Scan across ALL unresolved records in ANY statement
    for s_owner in all_stmts:
        for tx in s_owner["txs"]:
            if tx.transaction_id in resolved_ids:
                continue

            cand_pool = []
            for s_other in all_stmts:
                if s_other["id"] == s_owner["id"]:
                    continue
                cand_pool.extend([t for t in s_other["txs"] if t.transaction_id not in resolved_ids])

            similar_cands = find_similar_candidates(tx, to_df(cand_pool), cfg)
            if similar_cands:
                top_cand = similar_cands[0]
                c_id = str(top_cand["candidate_id"]).strip()
                resolved_ids.add(str(tx.transaction_id).strip())
                if c_id and c_id != "UNMATCHED":
                    resolved_ids.add(c_id)
                final_results.append({
                    "primary_transaction_id": tx.transaction_id,
                    "primary_statement_id": s_owner["id"],
                    "counterpart_transaction_id": top_cand["candidate_id"],
                    "counterpart_statement_id": top_cand.get("statement_id", ""),
                    "settlement_id": tx.transaction_id,
                    "bank_transaction_id": top_cand["candidate_id"],
                    "stage": "similarity_engine",
                    "decision": "review",
                    "confidence": top_cand["similarity_score"],
                    "reason": f"Similar candidate found: {top_cand['candidate_id']} ({', '.join(top_cand['matching_features'])}).",
                    "status": "SIMILAR"
                })
            else:
                resolved_ids.add(str(tx.transaction_id).strip())
                final_results.append({
                    "primary_transaction_id": tx.transaction_id,
                    "primary_statement_id": s_owner["id"],
                    "counterpart_transaction_id": "UNMATCHED",
                    "counterpart_statement_id": "",
                    "settlement_id": tx.transaction_id,
                    "bank_transaction_id": "UNMATCHED",
                    "stage": "unmatched",
                    "decision": "unmatched",
                    "confidence": 0.0,
                    "reason": "No candidate features overlap with other statement sources.",
                    "status": "UNMATCHED"
                })

    res_df = pd.DataFrame(final_results) if final_results else pd.DataFrame(columns=[
        "primary_transaction_id", "primary_statement_id", "counterpart_transaction_id",
        "counterpart_statement_id", "settlement_id", "bank_transaction_id",
        "stage", "decision", "confidence", "reason", "status"
    ])

    res_df.to_csv(OUTPUT_PATH, index=False)

    print("=" * 60)
    print("LEDGER - RECONCILIATION COMPLETE (Four-Status Taxonomy v2)")
    print("=" * 60)
    print(f"Total results: {len(res_df)}")
    print(f"Config saved : {CONFIG_OUTPUT_PATH}")
    print(f"Results saved: {OUTPUT_PATH}")
    return res_df


if __name__ == "__main__":
    reconcile()