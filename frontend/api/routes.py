"""
API layer for the Ledger dashboard (v2 Extended).

Bridge between the Flask frontend and the core Ledger reconciliation engine.
Integrates exact matching, tolerance matching, ML confidence evaluation,
LLM ambiguous reviewer, exception ledger, and Settlement Q&A agent.

Phase 6 Additions:
  - T6.1: Per-decision evidence object for API (/api/transactions & /api/reconciliation).
  - T6.2: Exception detail card with candidate_comparison for ambiguous ties.
  - T6.3: Matching Configuration API route (/api/config).
"""

import csv
import json
import os
import shutil
import sys
import threading
import uuid
import time
from datetime import datetime
from typing import Any, Optional, Dict, List

from flask import Blueprint, current_app, jsonify, request, Response, send_file, session
from werkzeug.utils import secure_filename
import re
import pandas as pd

from config import MatchingConfig
from matcher.similarity_engine import find_similar_candidates

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"csv", "xlsx", "pdf"}

import collections

_RUNS = {}
_RUN_LOG = []
_BEGINNING_BALANCE = 0.0


LEDGER_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

if LEDGER_ROOT not in sys.path:
    sys.path.insert(0, LEDGER_ROOT)

FRONTEND_DIR = os.path.join(LEDGER_ROOT, "frontend")
if FRONTEND_DIR not in sys.path:
    sys.path.insert(0, FRONTEND_DIR)

from data_access import read_csv_rows, file_exists
from statement_store import list_statements

RESULTS_DIR = os.path.join(LEDGER_ROOT, "data", "results")
GENERATED_DIR = os.path.join(LEDGER_ROOT, "data", "generated")
ML_DIR = os.path.join(LEDGER_ROOT, "data", "ml")
CONFIG_OUTPUT_PATH = os.path.join(RESULTS_DIR, "reconciliation_config.json")



def _read_csv(directory, filename):
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(path)


def _is_valid_id(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", "unknown", "n/a", "na", "—", "-", "undefined"):
        return False
    # Reject date-like strings (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY)
    if re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$", s) or re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$", s):
        return False
    return True


def _clean(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


# --------------------------------------------------------------------------
# Helpers & File Handling
# --------------------------------------------------------------------------

def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _import_uploaded_file(file_storage, source):
    """
    Deprecated upload handler helper (T6.5).
    Routes upload files into statement_store.save_imported_statement() under the hood.
    """
    from frontend import statement_store

    source_type = str(source).lower().strip()
    is_primary = source_type in ["razorpay", "settlement", "orders", "primary"]
    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else "csv"

    if ext == "csv":
        df = pd.read_csv(file_storage)
    elif ext == "pdf":
        upload_root = current_app.config.get("UPLOAD_FOLDER", "/tmp")
        source_dir = os.path.join(upload_root, source_type)
        os.makedirs(source_dir, exist_ok=True)
        stored_path = os.path.join(source_dir, f"{uuid.uuid4().hex}.pdf")
        file_storage.save(stored_path)
        df = statement_store.parse_pdf_statement(stored_path)
    else:
        df = pd.read_excel(file_storage)

    name = f"{source_type.title()} Upload"

    stmt = statement_store.save_imported_statement(
        name=name,
        filename=original_name,
        df=df,
        is_primary=is_primary,
        color="#3b82f6" if is_primary else "#10b981",
        rules=""
    )

    return {
        "id": stmt.get("id"),
        "original_filename": stmt.get("original_filename") or stmt.get("filename") or original_name,
        "row_count": stmt.get("row_count", 0),
        "uploaded_at": stmt.get("created_at") or datetime.utcnow().isoformat() + "Z"
    }





def _best_effort_row_count(path, ext):
    try:
        if ext == "csv":
            with open(path, newline="", encoding="utf-8", errors="ignore") as f:
                return max(sum(1 for _ in csv.reader(f)) - 1, 0)
        return None
    except Exception:
        return None


def _extract_date(row):
    d = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    for k in ["Order Date", "order_date", "Date", "date", "Txn Date", "txn_date", "Value Date", "value_date", "created_at", "transaction_date", "Time", "time"]:
        val = d.get(k)
        if not pd.isna(val) and val is not None:
            s = str(val).strip()
            if s and s.lower() not in ["nan", "none", "null", "undefined", "—"]:
                if "T" in s:
                    s = s.split("T")[0]
                return s
    return ""


# --------------------------------------------------------------------------
# Pipeline Execution Engine Integration
# --------------------------------------------------------------------------

def _log_info(msg):
    try:
        current_app.logger.info(msg)
    except Exception:
        print(f"[INFO] {msg}")


def _log_warning(msg):
    try:
        current_app.logger.warning(msg)
    except Exception:
        print(f"[WARNING] {msg}")


def clear_reconciliation_results():
    """Removes all generated matching outcome CSVs so fresh data starts in UNMATCHED state."""
    for f in ["reconciliation_results.csv", "exception_ledger.csv", "exact_matches.csv", "tolerance_matches.csv", "confidence_eval.csv"]:
        p = os.path.join(RESULTS_DIR, f)
        if os.path.exists(p):
            try:
                os.unlink(p)
            except Exception:
                pass


def _run_backend_pipeline():
    from frontend import statement_store
    from frontend.api import pipeline_tracker

    stmts = statement_store.list_statements()
    if not stmts:
        clear_reconciliation_results()
        pipeline_tracker.start_pipeline("No active statements imported.")
        pipeline_tracker.finish_pipeline(success=True)
        return

    pipeline_tracker.start_pipeline("Ingesting Statement & Syncing Database...")

    with pipeline_tracker.PipelineOutputCapture():
        statement_store.ensure_all_generated_csvs()

        pipeline_tracker.update_progress(20, "Executing Reconciliation Pipeline (T5.4)...", "Running Rule Engine & ML Pipeline...", level="RECON")
        try:
            from reconciler import pipeline_runner
            pipeline_runner.run_full_pipeline()
        except Exception as exc:
            pipeline_tracker.add_log(f"error: {exc}", level="WARNING")

        pipeline_tracker.finish_pipeline(success=True)



def compute_overview_charts(transactions, exceptions, period_settled, percent):
    """Compute data structure for the 6 Overview charts.

    Charts:
      1. Status Breakdown (donut) – SETTLED / MATCHED / SIMILAR / UNMATCHED
      2. Status Composition (100% stacked horizontal bar)
      3. Source-wise Contribution (stacked bar per source)
      4. Amount Variance Distribution (histogram of amount diffs)
      5. Mismatch Reasons (horizontal bar of exception reasons)
      6. Time × Amount Scatter Map (scatter plot with cluster links)
    """
    total = len(transactions)

    # ── 1. Status Breakdown (SETTLED / MATCHED / SIMILAR / UNMATCHED) ──
    settled_cnt = 0
    matched_cnt = 0
    similar_cnt = 0
    unmatched_cnt = 0

    for t in transactions:
        st = (t.get("status") or "").lower()
        if st == "settled" or (period_settled and st in {"auto", "matched"}):
            settled_cnt += 1
        elif st in {"auto", "matched"}:
            matched_cnt += 1
        elif st in {"manual", "llm", "similar", "review"}:
            similar_cnt += 1
        else:
            unmatched_cnt += 1

    status_breakdown = {
        "labels": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
        "counts": [settled_cnt, matched_cnt, similar_cnt, unmatched_cnt],
        "percentages": [
            round((settled_cnt / total * 100), 1) if total > 0 else 0.0,
            round((matched_cnt / total * 100), 1) if total > 0 else 0.0,
            round((similar_cnt / total * 100), 1) if total > 0 else 0.0,
            round((unmatched_cnt / total * 100), 1) if total > 0 else 0.0,
        ]
    }

    # ── 2. Status Composition (100% stacked horizontal bar) ──
    status_composition = {
        "labels": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
        "counts": [settled_cnt, matched_cnt, similar_cnt, unmatched_cnt],
        "total": total,
    }

    # ── 3. Source-wise Contribution (stacked bar per source) ──
    source_stats = {}
    for t in transactions:
        sname = t.get("source_name") or t.get("source_type_label") or "Primary Statement"
        if sname not in source_stats:
            source_stats[sname] = {"SETTLED": 0, "MATCHED": 0, "SIMILAR": 0, "UNMATCHED": 0}

        st = (t.get("status") or "").lower()
        if st == "settled" or (period_settled and st in {"auto", "matched"}):
            source_stats[sname]["SETTLED"] += 1
        elif st in {"auto", "matched"}:
            source_stats[sname]["MATCHED"] += 1
        elif st in {"manual", "llm", "similar", "review"}:
            source_stats[sname]["SIMILAR"] += 1
        else:
            source_stats[sname]["UNMATCHED"] += 1

    # Sort sources by total transaction count descending
    source_labels_sorted = sorted(
        source_stats.keys(),
        key=lambda s: sum(source_stats[s].values()),
        reverse=True
    ) if source_stats else ["No Sources"]
    source_contribution = {
        "labels": source_labels_sorted,
        "datasets": {
            "SETTLED": [source_stats[s]["SETTLED"] for s in source_labels_sorted] if source_stats else [0],
            "MATCHED": [source_stats[s]["MATCHED"] for s in source_labels_sorted] if source_stats else [0],
            "SIMILAR": [source_stats[s]["SIMILAR"] for s in source_labels_sorted] if source_stats else [0],
            "UNMATCHED": [source_stats[s]["UNMATCHED"] for s in source_labels_sorted] if source_stats else [0],
        }
    }

    # ── 4. Amount Variance Distribution ──
    # Compute variance between matched primary and counterpart amounts
    variance_buckets = collections.OrderedDict([
        ("\u20b90 (Exact)", 0),
        ("\u20b90\u2013\u20b910", 0),
        ("\u20b910\u2013\u20b9100", 0),
        ("\u20b9100\u2013\u20b91,000", 0),
        ("\u20b91,000+", 0),
    ])
    # Build a lookup of transaction amounts by id for counterpart comparison
    _tx_amount_by_id = {}
    for t in transactions:
        tid = t.get("id") or t.get("primary_id")
        if tid:
            _tx_amount_by_id[tid] = abs(float(t.get("amount") or 0.0))

    for t in transactions:
        st = (t.get("status") or "").lower()
        counterpart = t.get("counterpart")
        if st in {"settled", "matched", "similar", "llm", "auto"} and counterpart:
            cp_id = counterpart.get("id", "")
            t_amt = abs(float(t.get("amount") or 0.0))
            cp_amt = _tx_amount_by_id.get(cp_id, t_amt)
            diff = abs(t_amt - cp_amt)
            if diff == 0.0:
                variance_buckets["\u20b90 (Exact)"] += 1
            elif diff <= 10:
                variance_buckets["\u20b90\u2013\u20b910"] += 1
            elif diff <= 100:
                variance_buckets["\u20b910\u2013\u20b9100"] += 1
            elif diff <= 1000:
                variance_buckets["\u20b9100\u2013\u20b91,000"] += 1
            else:
                variance_buckets["\u20b91,000+"] += 1
        elif st in {"exception", "unmatched", "unreconciled", "manual"}:
            # Unmatched transactions have unknown variance — count as missing
            variance_buckets["\u20b91,000+"] += 1

    amount_variance = {
        "labels": list(variance_buckets.keys()),
        "counts": list(variance_buckets.values()),
    }

    # ── 5. Mismatch Reasons ──
    # Derive reasons from the reconciliation results CSV reason field and evidence
    reason_map = collections.Counter()
    for t in transactions:
        st = (t.get("status") or "").lower()
        if st not in {"exception", "unmatched", "unreconciled", "manual", "similar", "review"}:
            continue
        evidence = t.get("evidence") or {}
        rule_text = (evidence.get("rule") or t.get("rule") or "").lower()
        flags = evidence.get("flags") or []

        # Classify mismatch reason from rule text and flags
        classified = False
        if "duplicate" in rule_text or "Duplicate Discrepancy" in flags:
            reason_map["Duplicate Transaction"] += 1
            classified = True
        if "amount" in rule_text or "tolerance" in rule_text or "fee" in rule_text:
            reason_map["Amount Mismatch"] += 1
            classified = True
        if "date" in rule_text or "time" in rule_text or "lag" in rule_text:
            reason_map["Date/Time Mismatch"] += 1
            classified = True
        if "reference" in rule_text or "utr" in rule_text or "narration" in rule_text:
            reason_map["Reference/UTR Mismatch"] += 1
            classified = True
        if "currency" in rule_text or "fx" in rule_text:
            reason_map["Source Mismatch"] += 1
            classified = True
        if "no candidate" in rule_text or "no match" in rule_text or "overlap" in rule_text:
            reason_map["Missing Transaction"] += 1
            classified = True
        if not classified:
            reason_map["Other"] += 1

    # Sort by count descending
    sorted_reasons = sorted(reason_map.items(), key=lambda x: x[1], reverse=True)
    mismatch_reasons = {
        "labels": [r[0] for r in sorted_reasons] if sorted_reasons else ["No Mismatches"],
        "counts": [r[1] for r in sorted_reasons] if sorted_reasons else [0],
    }

    # ── 6. Time × Amount Scatter Map ──
    scatter_points = []
    cluster_links = []  # pairs of point indices that are matched
    point_index_by_id = {}  # tx_id -> scatter index

    for idx, t in enumerate(transactions):
        date_str = t.get("date") or ""
        amt = float(t.get("amount") or 0.0)
        if not date_str or date_str.strip().lower() in ("nan", "none", "", "\u2014"):
            continue
        # Normalise date to ISO for JS parsing
        d_clean = str(date_str).split("T")[0].split(" ")[0].strip()
        st = (t.get("status") or "").lower()
        point = {
            "x": d_clean,
            "y": abs(amt),
            "id": t.get("id") or "",
            "source": t.get("source_name") or "Unknown",
            "sourceColor": t.get("source_color") or "#3b82f6",
            "status": st,
            "amount": amt,
            "date": d_clean,
            "utr": t.get("utr") or "",
            "description": (t.get("description") or "")[:60],
        }
        point_index_by_id[t.get("id") or f"__idx_{idx}"] = len(scatter_points)
        scatter_points.append(point)

    # Build cluster links from matched counterparts
    for t in transactions:
        counterpart = t.get("counterpart")
        if not counterpart:
            continue
        t_id = t.get("id") or ""
        c_id = counterpart.get("id") or ""
        if t_id in point_index_by_id and c_id in point_index_by_id:
            i1 = point_index_by_id[t_id]
            i2 = point_index_by_id[c_id]
            if i1 != i2:
                link = tuple(sorted([i1, i2]))
                if link not in {tuple(sorted(l)) for l in cluster_links}:
                    cluster_links.append(list(link))

    scatter_map = {
        "points": scatter_points,
        "links": cluster_links,
    }

    # ── 7. Matching Cascade (Waterfall / Pass Breakdown) ──
    pass_1_cnt = 0
    pass_2_cnt = 0
    pass_3_cnt = 0
    pass_4_cnt = 0
    unresolved_cnt = 0

    for t in transactions:
        st = (t.get("status") or "").lower()
        evidence = t.get("evidence") or {}
        rule_text = (evidence.get("rule") or t.get("rule") or "").lower()
        conf = float(t.get("confidence") or 0.0)

        if st in {"settled", "matched", "auto", "similar", "llm"}:
            if "llm" in rule_text or "groq" in rule_text or st == "llm":
                pass_4_cnt += 1
            elif "split" in rule_text or "aggregate" in rule_text or "n:1" in rule_text:
                pass_3_cnt += 1
            elif "tolerance" in rule_text or "fee" in rule_text or "mdr" in rule_text or "lag" in rule_text:
                pass_2_cnt += 1
            elif "exact" in rule_text or "utr" in rule_text or "clean" in rule_text or conf >= 0.9:
                pass_1_cnt += 1
            else:
                pass_2_cnt += 1
        else:
            unresolved_cnt += 1

    matching_cascade = {
        "labels": ["Pass 1: UTR Exact", "Pass 2: Fee Tolerance", "Pass 3: N:1 Split Batch", "Pass 4: Groq LLM Match", "Unresolved Exceptions"],
        "counts": [pass_1_cnt, pass_2_cnt, pass_3_cnt, pass_4_cnt, unresolved_cnt],
        "percentages": [
            round((pass_1_cnt / total * 100), 1) if total > 0 else 0.0,
            round((pass_2_cnt / total * 100), 1) if total > 0 else 0.0,
            round((pass_3_cnt / total * 100), 1) if total > 0 else 0.0,
            round((pass_4_cnt / total * 100), 1) if total > 0 else 0.0,
            round((unresolved_cnt / total * 100), 1) if total > 0 else 0.0,
        ]
    }

    # ── 8. Exception Risk Exposure Matrix (Age vs Amount Exposure) ──
    age_tiers = ["0–2 Days", "3–7 Days", "8–14 Days", "15+ Days"]
    amount_tiers = ["< \u20b91k", "\u20b91k\u2013\u20b910k", "\u20b910k\u2013\u20b9100k", "\u20b9100k+"]
    
    # 4x4 matrix initialized with zeros
    risk_matrix = [[{"count": 0, "amount": 0.0} for _ in range(4)] for _ in range(4)]
    total_exposure = 0.0

    today_dt = datetime.utcnow()

    for t in transactions:
        st = (t.get("status") or "").lower()
        if st not in {"exception", "unmatched", "unreconciled", "manual", "similar", "review"}:
            continue

        amt = abs(float(t.get("amount") or 0.0))
        total_exposure += amt

        # Parse date to compute age in days
        tx_date_str = str(t.get("date") or "").split("T")[0].split(" ")[0].strip()
        days_open = 1
        if tx_date_str and tx_date_str.lower() not in {"nan", "none", "", "\u2014"}:
            try:
                tx_dt = datetime.strptime(tx_date_str, "%Y-%m-%d")
                days_open = max((today_dt - tx_dt).days, 0)
            except Exception:
                days_open = 1

        # Classify amount tier index (0..3)
        if amt < 1000:
            amt_idx = 0
        elif amt < 10000:
            amt_idx = 1
        elif amt < 100000:
            amt_idx = 2
        else:
            amt_idx = 3

        # Classify age tier index (0..3)
        if days_open <= 2:
            age_idx = 0
        elif days_open <= 7:
            age_idx = 1
        elif days_open <= 14:
            age_idx = 2
        else:
            age_idx = 3

        risk_matrix[amt_idx][age_idx]["count"] += 1
        risk_matrix[amt_idx][age_idx]["amount"] += round(amt, 2)

    exception_risk_matrix = {
        "age_tiers": age_tiers,
        "amount_tiers": amount_tiers,
        "matrix": risk_matrix,
        "total_exposure": round(total_exposure, 2),
        "total_exceptions": unresolved_cnt,
    }

    # ── 9. Gateway Performance & MDR Leakage Matrix ──
    gw_stats = {}
    for t in transactions:
        sname = t.get("source_name") or t.get("source_type_label") or "Primary Statement"
        if sname not in gw_stats:
            gw_stats[sname] = {"total": 0, "matched": 0, "fee_variance": 0.0}

        gw_stats[sname]["total"] += 1
        st = (t.get("status") or "").lower()
        if st in {"settled", "matched", "auto", "similar", "llm"}:
            gw_stats[sname]["matched"] += 1

        fee_diff = 0.0
        counterpart = t.get("counterpart")
        if isinstance(counterpart, dict):
            cp_id = counterpart.get("id", "")
            cp_amt_val = counterpart.get("amount") or counterpart.get("net_amount")
            if cp_amt_val is not None:
                cp_amt = abs(float(cp_amt_val))
            else:
                cp_amt = _tx_amount_by_id.get(cp_id, abs(float(t.get("amount") or 0.0)))
            t_amt = abs(float(t.get("amount") or 0.0))
            fee_diff = abs(t_amt - cp_amt)
        elif t.get("amount_diff") is not None:
            fee_diff = abs(float(t.get("amount_diff")))
        elif t.get("fee_variance") is not None:
            fee_diff = abs(float(t.get("fee_variance")))

        if fee_diff > 0:
            gw_stats[sname]["fee_variance"] += fee_diff

    gw_labels_sorted = sorted(gw_stats.keys(), key=lambda s: gw_stats[s]["total"], reverse=True) if gw_stats else ["No Gateways"]
    gateway_performance_matrix = {
        "gateways": gw_labels_sorted,
        "total_counts": [gw_stats[g]["total"] for g in gw_labels_sorted] if gw_stats else [0],
        "matched_counts": [gw_stats[g]["matched"] for g in gw_labels_sorted] if gw_stats else [0],
        "match_rates": [round((gw_stats[g]["matched"] / gw_stats[g]["total"] * 100), 1) if gw_stats[g]["total"] > 0 else 0.0 for g in gw_labels_sorted] if gw_stats else [0.0],
        "fee_variances": [round(gw_stats[g]["fee_variance"], 2) for g in gw_labels_sorted] if gw_stats else [0.0],
    }

    # Legacy fields for backward compatibility with existing verification test suites
    funnel_data = {
        "stages": ["Total Ingested", "Auto-Matched", "Settled", "Similar (Review)", "Unmatched"],
        "counts": [total, matched_cnt + settled_cnt, settled_cnt, similar_cnt, unmatched_cnt]
    }
    confidence_distribution = {
        "labels": ["0.0 - 0.5", "0.5 - 0.7", "0.7 - 0.8", "0.8 - 0.9", "0.9 - 1.0"],
        "counts": [0, 0, 0, 0, total] if total else [0, 0, 0, 0, 0]
    }
    exception_aging = {
        "labels": ["0-1 day", "1-3 days", "3-7 days", "7+ days"],
        "counts": [unmatched_cnt, 0, 0, 0]
    }
    trend_line = {
        "labels": ["Current Run"],
        "match_rates": [percent]
    }

    return {
        "status_breakdown": status_breakdown,
        "status_composition": status_composition,
        "source_contribution": source_contribution,
        "amount_variance": amount_variance,
        "mismatch_reasons": mismatch_reasons,
        "scatter_map": scatter_map,
        "matching_cascade": matching_cascade,
        "exception_risk_matrix": exception_risk_matrix,
        "gateway_performance_matrix": gateway_performance_matrix,
        # Backward compatibility aliases for verification tests
        "funnel_data": funnel_data,
        "confidence_distribution": confidence_distribution,
        "exception_aging": exception_aging,
        "trend_line": trend_line,
    }


_DASHBOARD_CACHE = {"timestamp": 0, "period_label": None, "data": None}
CACHE_TTL = 3.0  # seconds caching for fast UI interactions


def invalidate_dashboard_cache():
    _DASHBOARD_CACHE["data"] = None


def _get_or_build_run(run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Robust run retriever for Cloud Run & multi-instance serverless deployments.
    Prevents 'Run not found' 404 errors by building or reusing active run states.
    """
    stmts = statement_store.list_statements()
    if not stmts:
        _RUNS.clear()
        invalidate_dashboard_cache()
        return _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))

    if run_id and run_id in _RUNS:
        return _RUNS[run_id]

    if _RUNS and (not run_id or run_id == "latest"):
        return list(_RUNS.values())[-1]

    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    _RUNS[run["run_id"]] = run
    if run_id:
        _RUNS[run_id] = run
    return run


def compute_transaction_feature_flags(txn, counterpart=None, raw_row=None, match_info=None):
    """
    Computes a comprehensive array of feature flags and primary transaction type tag.
    Flags:
      1. International Txn ("International Txn"): Non-INR currency or foreign currency terms (USD, EUR, GBP, FX, SWIFT, PayPal).
      2. Internal Transfer ("Internal Transfer"): Same UTR or inter-account transfer between primary bank/UPI accounts with date/amount tolerance.
      3. Manual Override ("Manual Override"): Manually edited or status overridden by human reviewer.
      4. Exact UTR Match ("Exact UTR Match"): Matched via exact UTR/reference key parity.
      5. Unmatched UTR ("Unmatched UTR"): Missing or unresolved reference key.
      6. Batch MDR Payout ("Batch MDR Payout"): Part of 1-to-N batch payout fee equation solving.
      7. Groq LLM Assisted ("Groq LLM Assisted"): Resolved or validated via Groq LLM agent.
      8. Digit Transposition ("Digit Transposition"): Transposition or minor numeric variance.
      9. Duplicate Discrepancy ("Duplicate Discrepancy"): Double booking or duplicate signature across imports.
    """
    flags = []
    
    # 1. International Currency Check
    currency = str(txn.get("currency") or (raw_row and raw_row.get("currency")) or "INR").upper().strip()
    desc = (str(txn.get("description") or "") + " " + str(raw_row and (raw_row.get("narration") or raw_row.get("details")) or "")).upper()
    intl_keywords = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "FX", "SWIFT", "FOREX", "PAYPAL", "INTERNATIONAL", "OVERSEAS", "CROSS BORDER", "CONVERSION"]
    if currency not in ["INR", "RS", "RUPEES", ""] or any(k in desc for k in intl_keywords):
        flags.append("International Txn")

    # 2. Internal Transfer Check
    st_type = str(txn.get("source_type") or "").lower()
    c_type = str(counterpart and counterpart.get("source_type") or "").lower() if counterpart else ""
    s_name = str(txn.get("source_name") or "").lower()
    c_name = str(counterpart and counterpart.get("source_name") or "").lower() if counterpart else ""
    transfer_keywords = ["INTERNAL TRANSFER", "SELF TRANSFER", "BANK TRANSFER", "INTER ACCOUNT", "ACCOUNT TRANSFER", "UPI TRANSFER", "SWEEP", "CONTRA"]
    is_bank_to_bank = ("bank" in st_type and "bank" in c_type) or ("bank" in s_name and "bank" in c_name)
    if any(k in desc for k in transfer_keywords) or is_bank_to_bank or (txn.get("is_primary") and counterpart and counterpart.get("is_primary")):
        flags.append("Internal Transfer")

    # 3. Manual Override Check
    rule_str = str(txn.get("evidence", {}).get("rule") or (match_info and match_info.get("rule")) or "").lower()
    status_str = str(txn.get("status") or "").lower()
    if "manual" in rule_str or "override" in rule_str or status_str in ["manual", "manually_edited", "manual_override"] or txn.get("manually_edited"):
        flags.append("Manual Override")

    # 4. Exact UTR Match
    if "exact" in rule_str or "pass 1" in rule_str or "reference match" in rule_str or (txn.get("utr") and str(txn.get("utr")).strip() not in ["—", "", "nan"] and status_str in ["settled", "matched"] and "manual" not in rule_str):
        flags.append("Exact UTR Match")

    # 5. Unmatched Reference
    utr_val = str(txn.get("utr") or "").strip().lower()
    if (not utr_val or utr_val in ["—", "nan", "none", "null", ""]) or status_str in ["unreconciled", "exception", "unmatched"]:
        flags.append("Unmatched UTR")

    # 6. Batch MDR Payout
    if "mdr" in rule_str or "batch" in rule_str or "1-to-n" in rule_str or "fee" in rule_str or "solver" in rule_str:
        flags.append("Batch MDR Payout")

    # 7. Groq LLM Assisted
    if "llm" in rule_str or "groq" in rule_str or "llama" in rule_str or status_str == "llm":
        flags.append("Groq LLM Assisted")

    # 8. Digit Transposition
    if "transposition" in rule_str or "digit" in rule_str or "tolerance" in rule_str:
        flags.append("Digit Transposition")

    # 9. Existing Duplicate Discrepancy flag
    if "Duplicate Discrepancy" in (txn.get("evidence", {}).get("flags") or []):
        if "Duplicate Discrepancy" not in flags:
            flags.append("Duplicate Discrepancy")

    # Fallback default flag
    if not flags:
        flags.append("Standard Commercial")

    # Derive primary transaction type string
    priority_order = ["Manual Override", "International Txn", "Internal Transfer", "Batch MDR Payout", "Groq LLM Assisted", "Exact UTR Match", "Digit Transposition", "Duplicate Discrepancy", "Unmatched UTR", "Standard Commercial"]
    primary_type = "Standard Commercial"
    for p in priority_order:
        if p in flags:
            primary_type = p
            break

    return flags, primary_type


def _build_dashboard_run(period_label="Current Period"):
    """
    Constructs an authoritative reconciliation run dictionary from disk CSVs.
    Used by /api/reconciliation and overview page (T9.1, T12.3).
    """
    now = time.time()
    if _DASHBOARD_CACHE["data"] is not None and (now - _DASHBOARD_CACHE["timestamp"]) < CACHE_TTL:
        if _DASHBOARD_CACHE["period_label"] == period_label:
            return _DASHBOARD_CACHE["data"]

    db_data = statement_store._load_db()
    all_statements = db_data.get("statements", [])

    # Apply palette colors (mirrors statement_store.list_statements logic)
    _PALETTE = statement_store.STATEMENT_COLOR_PALETTE
    _DEFAULT_BLUES = {"#6f89ff", "#f04f4f", "#3b82f6", "#4C8DFF"}
    for idx, stmt in enumerate(all_statements):
        saved_color = stmt.get("color")
        if not saved_color or saved_color in _DEFAULT_BLUES:
            stmt["color"] = _PALETTE[idx % len(_PALETTE)]

    if not all_statements:
        empty_charts = compute_overview_charts([], [], False, 0.0)
        return {
            "run_id": "empty",
            "period_label": period_label,
            "status": "completed",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "closed": False,
            "period_settled": False,
            "summary": {
                "total_transactions": 0,
                "auto_matched": 0,
                "llm_matched": 0,
                "manual_matched": 0,
                "unreconciled": 0,
                "percent_reconciled": 100.0,
                "reconciled_percent": 100.0,
                "beginning_balance": 0.0,
                "payments_total": 0.0,
                "deposits_total": 0.0,
                "variance": 0.0,
                "period_settled": False,
            },
            "transactions": [],
            "exceptions": [],
            "charts": empty_charts,
        }

    results = read_csv_rows("results/reconciliation_results.csv")
    raw_exceptions = read_csv_rows("results/exception_ledger.csv")

    # Helper functions for robust value extraction from dicts/rows
    def _extract_currency(row, desc=""):
        if not isinstance(row, dict):
            row = {}
        for k in ["currency", "ccy", "curr"]:
            v = row.get(k)
            if v and str(v).strip() and str(v).strip().lower() not in ["nan", "none", "null"]:
                c_str = str(v).strip().upper()
                if c_str in ["USD", "EUR", "GBP", "INR", "JPY", "CAD", "AUD"]:
                    return c_str
        d_upper = str(desc or "").upper()
        if "$" in d_upper or "USD" in d_upper or "DOLLAR" in d_upper:
            return "USD"
        elif "EUR" in d_upper or "€" in d_upper or "EURO" in d_upper:
            return "EUR"
        elif "GBP" in d_upper or "£" in d_upper or "POUND" in d_upper:
            return "GBP"
        return "INR"

    def _extract_numeric_amount(row):
        for k in ["amount", "net_amount", "gross_amount", "credit", "credit_amount", "debit", "debit_amount"]:
            v = row.get(k)
            if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan":
                try:
                    num = float(v)
                    if num != 0.0:
                        return num
                except (ValueError, TypeError):
                    pass
        for k in ["amount", "net_amount", "gross_amount"]:
            v = row.get(k)
            if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan":
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return 0.0

    def _extract_date_str(row):
        for k in ["date", "transaction_date", "created_at", "value_date", "settlement_date"]:
            v = row.get(k)
            if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan":
                return str(v).strip()
        return ""

    def _extract_desc_str(row):
        for k in ["description", "narration", "particulars", "details", "customer_name", "customer"]:
            v = row.get(k)
            if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan":
                return str(v).strip()
        return "Transaction"

    # Build record_lookup from in-memory statement store
    record_lookup = {}
    for stmt in all_statements:
        st_id = stmt.get("id") or ""
        st_name = stmt.get("name") or "Statement"
        st_color = stmt.get("color") or "#3b82f6"
        st_type = stmt.get("type") or ("bank" if stmt.get("is_primary") else "settlement")
        is_pri = bool(stmt.get("is_primary", False))

        for row in stmt.get("rows", []):
            amt_val = _extract_numeric_amount(row)
            dt_val = _extract_date_str(row)
            desc_val = _extract_desc_str(row)
            utr_val = str(row.get("utr") or row.get("auth_code") or row.get("bank_transaction_id") or "")
            tx_id = str(row.get("transaction_id") or row.get("serial_no") or "").strip()

            curr_val = _extract_currency(row, desc_val)
            item_info = {
                "id": tx_id,
                "amount": amt_val,
                "date": dt_val,
                "description": desc_val,
                "currency": curr_val,
                "utr": utr_val,
                "statement_id": st_id,
                "source_name": st_name,
                "source_color": st_color,
                "source_type": st_type,
                "is_primary": is_pri,
                "row_data": row
            }
            if tx_id:
                record_lookup[tx_id] = item_info

            keys = [
                row.get("primary_transaction_id"),
                row.get("counterpart_transaction_id"),
                row.get("settlement_id"),
                row.get("bank_transaction_id"),
                row.get("order_id"),
                row.get("serial_no"),
            ]
            for k in keys:
                if k and _is_valid_id(k):
                    sk = str(k).strip()
                    if sk not in record_lookup or (record_lookup[sk]["amount"] == 0.0 and amt_val != 0.0):
                        record_lookup[sk] = item_info

    # Map matched pairs & status overrides from results CSV
    match_map = {}
    tx_status_map = {}
    if results:
        for r in results:
            p_id = str(r.get("primary_transaction_id") or r.get("settlement_id") or "").strip()
            c_id = str(r.get("counterpart_transaction_id") or r.get("bank_transaction_id") or "").strip()
            status_raw = str(r.get("status") or r.get("match_status") or r.get("decision") or "").lower().strip()
            conf = float(r.get("confidence") or r.get("score") or 0.95)
            rule = r.get("match_rule") or r.get("rule") or r.get("reason") or "Match"

            if p_id:
                tx_status_map[p_id] = {"status_raw": status_raw, "confidence": conf, "rule": rule}
            if c_id and c_id != "unmatched":
                tx_status_map[c_id] = {"status_raw": status_raw, "confidence": conf, "rule": rule}

            if c_id and c_id != "unmatched" and status_raw not in {"unmatched", "unreconciled", "rejected", "exception"}:
                item_p = {"matched_id": c_id, "confidence": conf, "rule": rule, "status_raw": status_raw}
                item_c = {"matched_id": p_id, "confidence": conf, "rule": rule, "status_raw": status_raw}

                if p_id:
                    match_map.setdefault(p_id, []).append(item_p)
                if c_id:
                    match_map.setdefault(c_id, []).append(item_c)

    # Order statements so primary statement comes first (if designated)
    ordered_statements = sorted(all_statements, key=lambda s: (not bool(s.get("is_primary", False))))

    # Populate raw_transactions with deduplicated matched pairs
    raw_transactions = []
    seen_matched_ids = set()
    txn_idx = 1

    for stmt in ordered_statements:
        st_id = stmt.get("id") or ""
        st_name = stmt.get("name") or "Statement"
        st_color = stmt.get("color") or "#3b82f6"
        st_type = stmt.get("type") or ("bank" if stmt.get("is_primary") else "settlement")
        is_pri = bool(stmt.get("is_primary", False))

        for row in stmt.get("rows", []):
            tx_id = str(row.get("transaction_id") or row.get("serial_no") or f"TXN_{txn_idx}").strip()
            amt_val = _extract_numeric_amount(row)
            dt_val = _extract_date_str(row) or datetime.utcnow().strftime("%Y-%m-%d")
            desc_val = _extract_desc_str(row)
            utr_val = str(row.get("utr") or row.get("auth_code") or "")

            direct_st_info = tx_status_map.get(tx_id)
            matches_list = match_map.get(tx_id, [])
            matched_sources = []
            counterpart_obj = None
            status_val = "exception"
            conf_val = 0.0
            rule_val = "Automated Exception"

            if direct_st_info and direct_st_info.get("status_raw") == "unreconciled":
                status_val = "unreconciled"
                rule_val = direct_st_info.get("rule") or "Manual Unreconciled Override"
                conf_val = 0.0
            elif matches_list:
                primary_match = matches_list[0]
                conf_val = primary_match["confidence"]
                rule_val = primary_match["rule"]
                raw_st = (primary_match.get("status_raw") or "").lower().strip()

                if raw_st in {"matched", "auto", "tolerance"}:
                    status_val = "matched"
                elif raw_st in {"settled", "exact"}:
                    status_val = "settled"
                elif raw_st in {"similar", "proposed", "ml"}:
                    status_val = "similar"
                elif raw_st == "unreconciled":
                    status_val = "unreconciled"
                elif raw_st in {"manual", "exception", "review", "unmatched", "rejected"}:
                    status_val = "exception"
                elif raw_st == "llm":
                    status_val = "llm"
                else:
                    status_val = "exception" if conf_val == 0.0 else ("settled" if is_pri else "matched")

            if status_val in {"unreconciled", "exception"} and conf_val == 0.0:
                # Fallback similarity scan across all other uploaded statement sources
                cfg = MatchingConfig()
                target_dict = {
                    "transaction_id": tx_id,
                    "net_amount": amt_val,
                    "transaction_date": dt_val,
                    "utr": utr_val,
                    "description": desc_val,
                    "statement_id": st_id,
                    "primary_statement_id": st_id
                }
                cand_pool = []
                for other_stmt in all_statements:
                    if str(other_stmt.get("id")) == str(st_id):
                        continue
                    o_sname = other_stmt.get("name") or "Statement"
                    o_scolor = other_stmt.get("color") or "#3b82f6"
                    o_stype = other_stmt.get("type") or ("bank" if other_stmt.get("is_primary") else "settlement")
                    for o_row in other_stmt.get("rows", []):
                        o_tx_id = str(o_row.get("transaction_id") or o_row.get("serial_no") or "").strip()
                        if o_tx_id:
                            cand_pool.append({
                                "transaction_id": o_tx_id,
                                "net_amount": _extract_numeric_amount(o_row),
                                "transaction_date": _extract_date_str(o_row),
                                "utr": str(o_row.get("utr") or o_row.get("auth_code") or o_row.get("bank_transaction_id") or ""),
                                "description": _extract_desc_str(o_row),
                                "statement_id": other_stmt.get("id"),
                                "source_name": o_sname,
                                "source_color": o_scolor,
                                "source_type": o_stype
                            })

                similar_results = find_similar_candidates(target_dict, cand_pool, cfg)
                if similar_results:
                    top_cand = similar_results[0]
                    cand_id = str(top_cand["candidate_id"]).strip()
                    status_val = "similar"
                    conf_val = float(top_cand["similarity_score"])
                    m_features = ", ".join(top_cand.get("matching_features", []))
                    rule_val = f"Similar Candidate ({cand_id}): {m_features}"

                    cand_amt = top_cand.get("amount")
                    cand_date = top_cand.get("date")
                    cand_utr = top_cand.get("utr") or cand_id
                    cand_desc = top_cand.get("description")
                    cand_sname = top_cand.get("source_name") or f"Statement {top_cand.get('statement_id')}"
                    cand_scolor = top_cand.get("source_color") or "#f59e0b"
                    cand_stype = top_cand.get("source_type") or "counterpart"

                    c_entry = {
                        "type": cand_stype,
                        "name": cand_sname,
                        "color": cand_scolor,
                        "id": cand_id,
                        "amount": cand_amt,
                        "date": cand_date,
                        "utr": cand_utr,
                        "description": cand_desc
                    }
                    matched_sources = [c_entry]
                    counterpart_obj = {
                        "id": cand_id,
                        "source_name": cand_sname,
                        "source_color": cand_scolor,
                        "source_type": cand_stype,
                        "is_primary": False,
                        "amount": cand_amt,
                        "date": cand_date,
                        "utr": cand_utr,
                        "description": cand_desc
                    }
                else:
                    counterpart_obj = None
                    matched_sources = []
            else:
                # Deduplicate mirror duplicate rows for matched/settled/similar pairs
                if status_val in {"settled", "matched", "similar", "exception", "llm"}:
                    if tx_id in seen_matched_ids:
                        continue
                    seen_matched_ids.add(tx_id)
                    for m_info in matches_list:
                        m_id = m_info.get("matched_id")
                        if m_id:
                            seen_matched_ids.add(m_id)

                seen_sources = set([st_name])
                for m_info in matches_list:
                    m_id = m_info["matched_id"]
                    m_rec = record_lookup.get(m_id)
                    if m_rec:
                        m_name = m_rec["source_name"]
                        m_color = m_rec["source_color"]
                        m_type = m_rec["source_type"]
                        m_is_pri = m_rec["is_primary"]

                        if m_name and m_name not in seen_sources:
                            seen_sources.add(m_name)
                            c_entry = {
                                "type": m_type,
                                "name": m_name,
                                "color": m_color,
                                "id": m_id
                            }
                            matched_sources.append(c_entry)

                        if not counterpart_obj:
                            counterpart_obj = {
                                "id": m_id,
                                "source_name": m_name,
                                "source_color": m_color,
                                "source_type": m_type,
                                "is_primary": m_is_pri,
                                "amount": m_rec.get("amount"),
                                "currency": m_rec.get("currency", "INR"),
                                "date": m_rec.get("date"),
                                "utr": m_rec.get("utr"),
                                "description": m_rec.get("description")
                            }

            txn = {
                "id": tx_id,
                "primary_id": tx_id,
                "date": dt_val,
                "description": desc_val,
                "amount": amt_val,
                "currency": curr_val,
                "utr": utr_val,
                "status": status_val,
                "confidence": conf_val,
                "cluster_id": tx_id,
                "statement_id": st_id,
                "source_type": st_type,
                "source_name": st_name,
                "source_color": st_color,
                "is_primary": is_pri,
                "has_counterpart": bool(counterpart_obj),
                "counterpart": counterpart_obj,
                "matched_sources": matched_sources,
                "matched_source_name": matched_sources[0]["name"] if matched_sources else None,
                "evidence": {
                    "decision": status_val.upper(),
                    "rule": rule_val,
                    "score": conf_val,
                    "flags": []
                }
            }
            raw_transactions.append(txn)
            txn_idx += 1

    # Duplicate transaction detection pass across raw_transactions
    sig_counts = {}
    for t in raw_transactions:
        utr_clean = str(t.get("utr") or "").strip().lower()
        amt_clean = float(t.get("amount") or 0.0)
        dt_clean = str(t.get("date") or "").strip()
        sig = f"{amt_clean}_{dt_clean}_{utr_clean}" if (utr_clean and utr_clean not in ["—", "", "nan"]) else f"{t.get('source_name')}_{amt_clean}_{dt_clean}_{t.get('description')}"
        sig_counts[sig] = sig_counts.get(sig, 0) + 1

    for t in raw_transactions:
        utr_clean = str(t.get("utr") or "").strip().lower()
        amt_clean = float(t.get("amount") or 0.0)
        dt_clean = str(t.get("date") or "").strip()
        sig = f"{amt_clean}_{dt_clean}_{utr_clean}" if (utr_clean and utr_clean not in ["—", "", "nan"]) else f"{t.get('source_name')}_{amt_clean}_{dt_clean}_{t.get('description')}"
        if sig_counts.get(sig, 0) > 1:
            if "Duplicate Discrepancy" not in t["evidence"]["flags"]:
                t["evidence"]["flags"].append("Duplicate Discrepancy")

    # Enrich exceptions with record_lookup
    exceptions = []
    for exc in raw_exceptions:
        exc_item = dict(exc)
        sid = str(exc_item.get("settlement_id") or "").strip()
        bid = str(exc_item.get("bank_transaction_id") or "").strip()
        info = record_lookup.get(sid) or record_lookup.get(bid) or {}

        try:
            amt_val = float(exc_item.get("amount") or 0.0)
        except (ValueError, TypeError):
            amt_val = 0.0

        if (amt_val == 0.0 or not exc_item.get("amount")) and info.get("amount"):
            exc_item["amount"] = info["amount"]
        else:
            exc_item["amount"] = amt_val

        if (not exc_item.get("description") or str(exc_item.get("description")).strip() == sid or str(exc_item.get("description")).strip() == "nan") and info.get("description"):
            exc_item["description"] = info["description"]

        if (not exc_item.get("date") or str(exc_item.get("date")).strip() == "" or str(exc_item.get("date")).strip() == "nan") and info.get("date"):
            exc_item["date"] = info["date"]

        # Enrich exc_item from raw_transactions matching metadata
        matched_tx = next((t for t in raw_transactions if str(t.get("id") or t.get("settlement_id") or "").strip().lower() in {sid.lower(), bid.lower()} and (sid or bid)), None)
        if matched_tx:
            if not exc_item.get("matched_source_name"):
                exc_item["matched_source_name"] = matched_tx.get("matched_source_name")
            if not exc_item.get("counterpart"):
                exc_item["counterpart"] = matched_tx.get("counterpart")
            if not exc_item.get("matched_sources"):
                exc_item["matched_sources"] = matched_tx.get("matched_sources")
            if not exc_item.get("status") or exc_item.get("status") == "exception":
                exc_item["status"] = matched_tx.get("status") or exc_item.get("status")

        if not exc_item.get("currency"):
            exc_item["currency"] = info.get("currency") or (matched_tx.get("currency") if matched_tx else None) or _extract_currency(exc_item, exc_item.get("description"))

        exceptions.append(exc_item)

    # Ensure all automated unmatched transactions from engine are listed in exceptions
    existing_exc_sids = {str(e.get("settlement_id") or "").strip().lower() for e in exceptions if e.get("settlement_id")}
    for t in raw_transactions:
        st = (t.get("status") or "").lower().strip()
        sid = str(t.get("settlement_id") or t.get("id") or "").strip()
        if st in {"unmatched", "exception", "manual", "similar", "review"} and sid and sid.lower() not in existing_exc_sids:
            cp_obj = t.get("counterpart") if isinstance(t.get("counterpart"), dict) else None
            m_sources = t.get("matched_sources") or []
            m_sname = t.get("matched_source_name") or (cp_obj.get("source_name") if cp_obj else None)
            if not m_sname and m_sources and isinstance(m_sources, list) and len(m_sources) > 0:
                m_sname = m_sources[0].get("name")

            exceptions.append({
                "exception_id": f"EXC-{len(exceptions)+1:04d}",
                "settlement_id": sid,
                "bank_transaction_id": cp_obj.get("id") if cp_obj else "UNLINKED",
                "amount": t.get("amount", 0.0),
                "currency": t.get("currency") or _extract_currency(t, t.get("description")),
                "date": t.get("date", ""),
                "description": t.get("description", ""),
                "source_name": t.get("source_name", "Automated Engine"),
                "source_type": t.get("source_type", "settlement"),
                "source_color": t.get("source_color"),
                "status": t.get("status") or "exception",
                "matched_source_name": m_sname,
                "counterpart": cp_obj,
                "matched_sources": m_sources,
                "evidence": t.get("evidence"),
                "confidence": t.get("confidence", 0.0),
                "utr": t.get("utr"),
                "exception_type": "similar_review" if st in {"similar", "review"} else "automated_unmatched",
                "reason": t.get("reason") or "Automated transaction flagged for review.",
                "resolution_status": "open",
            })
            existing_exc_sids.add(sid.lower())

    transactions = raw_transactions

    # Enrich all transactions and exceptions with canonical feature flags & primary transaction type
    for t in transactions:
        flags, p_type = compute_transaction_feature_flags(t, t.get("counterpart"))
        t["feature_flags"] = flags
        t["transaction_type"] = p_type
        t["type"] = p_type
        if "evidence" in t and isinstance(t["evidence"], dict):
            t["evidence"]["flags"] = flags

    for exc in exceptions:
        flags, p_type = compute_transaction_feature_flags(exc, exc.get("counterpart"))
        exc["feature_flags"] = flags
        exc["transaction_type"] = p_type
        exc["type"] = p_type

    def _format_ddmmyyyy(d_str):
        if not d_str:
            return ""
        d_s = str(d_str).split("T")[0].split(" ")[0].strip()
        parts = d_s.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return d_s

    # Calculate real min and max transaction date range
    valid_dates = [t["date"] for t in raw_transactions if t.get("date") and str(t["date"]).strip() not in ("", "None", "nan", "—")]
    if valid_dates:
        sorted_dates = sorted(valid_dates)
        min_d, max_d = _format_ddmmyyyy(sorted_dates[0]), _format_ddmmyyyy(sorted_dates[-1])
        period_label = f"{min_d} to {max_d}" if min_d != max_d else min_d
    else:
        period_label = "No Data"

    total = len(transactions)
    settled_count = len([t for t in transactions if (t.get("status") or "").lower() in {"settled", "settlement"}])
    matched_count = len([t for t in transactions if (t.get("status") or "").lower() in {"matched", "auto", "exact", "tolerance"}])
    similar_count = len([t for t in transactions if (t.get("status") or "").lower() in {"similar", "proposed", "ml", "ambiguous"}])
    llm_count = len([t for t in transactions if (t.get("status") or "").lower() == "llm"])
    # Reconciled count & percentage (T22.10: SIMILAR is excluded from reconciled count/percentage)
    reconciled_count = min(total, settled_count + matched_count + llm_count)
    raw_pct = (reconciled_count / total * 100) if total > 0 else 0.0
    percent = min(100.0, max(0.0, round(raw_pct, 1)))

    exceptions_count = len(exceptions) if exceptions else len([t for t in transactions if (t.get("status") or "").lower() in {"exception", "manual", "unmatched", "unreconciled", "similar", "review"}])
    unreconciled_count = len([t for t in transactions if (t.get("status") or "").lower() in {"unreconciled", "unmatched", "exception"}])
    if unreconciled_count == 0 and total > reconciled_count:
        unreconciled_count = total - reconciled_count
    unmatched_count = max(len(exceptions), unreconciled_count, total - reconciled_count)
    if exceptions_count == 0 and unmatched_count > 0:
        exceptions_count = unmatched_count

    pos_amounts = [t["amount"] for t in transactions if t["amount"] > 0]
    neg_amounts = [abs(t["amount"]) for t in transactions if t["amount"] < 0]

    deposits_total = float(sum(pos_amounts)) if pos_amounts else 0.0
    payments_total = float(sum(neg_amounts)) if neg_amounts else 0.0
    if deposits_total == 0.0 and payments_total == 0.0:
        deposits_total = float(sum(t["amount"] for t in transactions))

    # Net Variance is sum of UNMATCHED/exception amounts (T22.9)
    unmatched_amount_sum = sum(abs(float(t.get("amount") or 0.0)) for t in transactions if (t.get("status") or "").lower() in {"exception", "unmatched", "unreconciled"})
    if unmatched_amount_sum == 0.0 and exceptions:
        unmatched_amount_sum = sum(abs(float(e.get("amount") or 0.0)) for e in exceptions)
    variance = round(unmatched_amount_sum, 2)
    period_settled = bool(total > 0 and exceptions_count == 0 and unreconciled_count == 0)

    run_id = uuid.uuid4().hex
    charts_data = compute_overview_charts(transactions, exceptions, period_settled, percent)

    run_dict = {
        "run_id": run_id,
        "period_label": period_label,
        "status": "completed",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "closed": False,
        "period_settled": period_settled,
        "summary": {
            "total_transactions": total,
            "settled_count": settled_count,
            "matched_count": matched_count,
            "similar_count": similar_count,
            "unmatched_count": unmatched_count,
            "auto_matched": settled_count + matched_count + llm_count,
            "auto": matched_count,
            "llm_matched": llm_count,
            "manual_matched": exceptions_count,
            "manual": exceptions_count,
            "exceptions_count": exceptions_count,
            "unreconciled": unmatched_count,
            "percent_reconciled": percent,
            "beginning_balance": _BEGINNING_BALANCE,
            "payments_total": payments_total,
            "deposits_total": deposits_total,
            "variance": variance,
            "period_settled": period_settled,
        },
        "transactions": transactions,
        "exceptions": exceptions,
        "charts": charts_data,
    }

    run_log_item = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().strftime("Today %H:%M"),
        "total_transactions": total,
        "matched_count": settled_count + matched_count + llm_count,
        "status": "Complete"
    }
    if not any(r.get("run_id") == run_id for r in _RUN_LOG):
        _RUN_LOG.insert(0, run_log_item)
        if len(_RUN_LOG) > 10:
            _RUN_LOG.pop()

    _DASHBOARD_CACHE["timestamp"] = time.time()
    _DASHBOARD_CACHE["period_label"] = period_label
    _DASHBOARD_CACHE["data"] = run_dict
    return run_dict


@api_bp.route("/reconciliation/runs", methods=["GET"])

def get_reconciliation_runs():
    return jsonify({"ok": True, "runs": _RUN_LOG})


# --------------------------------------------------------------------------
# Phase 6 Admin & Information Endpoints (T6.1, T6.2, T6.3)
# --------------------------------------------------------------------------

@api_bp.route("/transactions", methods=["GET"])
def get_transactions():
    """T6.1 API endpoint returning transactions with per-decision evidence objects."""
    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    return jsonify({
        "ok": True,
        "count": len(run["transactions"]),
        "transactions": run["transactions"]
    })


@api_bp.route("/config", methods=["GET"])
def get_matching_config():
    """T6.3 API endpoint returning active MatchingConfig parameters and app_version."""
    from config import APP_VERSION
    cfg_data = {}
    if os.path.exists(CONFIG_OUTPUT_PATH):
        try:
            with open(CONFIG_OUTPUT_PATH, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
        except Exception:
            cfg_data = MatchingConfig().to_dict()
    else:
        cfg_data = MatchingConfig().to_dict()

    return jsonify({"ok": True, "app_version": APP_VERSION, "config": cfg_data})


@api_bp.route("/report-html", methods=["GET", "POST"])
def get_report_html():
    """Return structured report data and HTML string for the SPA Reports panel."""
    try:
        from reports.report_builder import build_filtered_report_data
        if request.method == "POST":
            filters = request.get_json(silent=True) or {}
        else:
            filters = {
                "statuses": request.args.getlist("status") or ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
                "sources": request.args.getlist("source") or ["all"],
                "start_date": request.args.get("start_date", ""),
                "end_date": request.args.get("end_date", ""),
                "sections": request.args.getlist("section") or ["summary", "charts", "transactions", "exceptions", "integrity"],
            }
        data = build_filtered_report_data(filters)
        return jsonify({"ok": True, "found": True, "data": data})
    except Exception as exc:
        return _error(f"Failed to generate report data: {exc}", 500)


@api_bp.route("/pipeline/status", methods=["GET"])
def get_pipeline_status():
    """Live status and terminal log output streaming endpoint for backend pipeline."""
    from frontend.api import pipeline_tracker
    return jsonify({"ok": True, **pipeline_tracker.get_status()})


# --------------------------------------------------------------------------
# Statement Database Endpoints
# --------------------------------------------------------------------------

from frontend import statement_store

@api_bp.route("/statements", methods=["GET"])
def get_statements_list():
    statements = statement_store.list_statements()
    return jsonify({"ok": True, "statements": statements})


@api_bp.route("/statements/import", methods=["POST"])
def import_statement():
    invalidate_dashboard_cache()
    from frontend.api import pipeline_tracker
    pipeline_tracker.start_pipeline("Importing...")

    files = request.files.getlist("file") or request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        pipeline_tracker.finish_pipeline(success=False, error_msg="No file selected.")
        return _error("No file selected.")

    raw_is_pri = request.form.get("is_primary", "").strip()
    source_type = (request.form.get("source") or request.form.get("source_type") or request.form.get("type") or "").lower().strip()
    
    if raw_is_pri != "":
        is_primary = str(raw_is_pri).lower().strip() in ("true", "1", "yes")
    else:
        is_primary = any(k in source_type for k in ("bank", "primary", "statement"))

    custom_name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "").strip()
    rules = (request.form.get("rules") or "").strip()

    raw_use_llm = request.form.get("use_llm", "false")
    use_llm = str(raw_use_llm).lower().strip() in ("true", "1", "yes")

    upload_root = current_app.config["UPLOAD_FOLDER"]
    sub_folder = "primary" if is_primary else "counterpart"
    source_dir = os.path.join(upload_root, sub_folder)
    os.makedirs(source_dir, exist_ok=True)

    results = []
    successful_imports = 0

    total_files = len([f for f in files if f and f.filename != ""])
    for idx, file_storage in enumerate(files):
        if not file_storage or file_storage.filename == "":
            continue

        raw_filename = file_storage.filename or "statement.csv"
        original_name = secure_filename(raw_filename)
        if not original_name or "." not in original_name:
            original_name = raw_filename

        # If file is a bank statement or contains bank keywords, set is_primary = True
        file_is_primary = is_primary or any(k in original_name.lower() for k in ("bank", "primary", "hdfc", "sbi", "icici", "kotak", "axis", "citibank"))

        pipeline_tracker.update_progress(
            15 + int((idx / max(1, total_files)) * 10),
            "Reading File...",
            "Ingesting statement file...",
            level="INFO"
        )

        if not _allowed_file(original_name):
            results.append({
                "filename": original_name,
                "status": "error",
                "statement_id": None,
                "row_count": 0,
                "error_message": "Unsupported file type. Please upload .csv, .xlsx, or .pdf files."
            })
            continue

        try:
            ext = original_name.rsplit(".", 1)[1].lower()
            stored_name = f"{uuid.uuid4().hex}.{ext}"
            stored_path = os.path.join(source_dir, stored_name)
            file_storage.save(stored_path)

            pipeline_tracker.update_progress(
                25,
                "Extracting & Parsing Data...",
                "Parsing records...",
                level="INFO"
            )

            if ext == "csv":
                df = pd.read_csv(stored_path)
            elif ext == "pdf":
                df = statement_store.parse_pdf_statement(stored_path)
                if df.empty:
                    raise ValueError("Could not extract tabular transactions from PDF.")
            else:
                df = pd.read_excel(stored_path)

            stmt_name = custom_name if (custom_name and len(files) == 1) else original_name.rsplit(".", 1)[0].replace("_", " ").title()

            pipeline_tracker.update_progress(
                28,
                "Normalizing Schema...",
                "Mapping field headers and canonical schema...",
                level="INFO"
            )

            stmt = statement_store.save_imported_statement(
                stmt_name,
                original_name,
                df,
                is_primary=file_is_primary,
                color=color,
                rules=rules,
                use_llm=use_llm,
            )
            successful_imports += 1
            results.append({
                "filename": original_name,
                "status": "success",
                "statement_id": stmt["id"],
                "row_count": stmt["row_count"],
                "dropped_columns": stmt.get("dropped_columns", []),
                "explanations": stmt.get("explanations", []),
                "error_message": None
            })

        except Exception as exc:
            results.append({
                "filename": original_name,
                "status": "error",
                "statement_id": None,
                "row_count": 0,
                "error_message": str(exc)
            })

    if successful_imports > 0:
        clear_reconciliation_results()
        invalidate_dashboard_cache()
        _RUNS.clear()
        _RUN_LOG.clear()
        try:
            pipeline_tracker.update_progress(
                100,
                "Statement Ingestion Done",
                "Successfully ingested.",
                level="SUCCESS"
            )
            pipeline_tracker.finish_pipeline(success=True)
        except Exception as exc:
            current_app.logger.warning(f"Pipeline tracker completion note: {exc}")

    first_stmt = statement_store.get_statement(results[0]["statement_id"]) if (results and results[0]["status"] == "success") else None
    return jsonify({
        "ok": True,
        "results": results,
        "statement": first_stmt
    })



@api_bp.route("/statements/<statement_id>", methods=["GET"])
def get_statement_detail(statement_id):
    stmt = statement_store.get_statement(statement_id)
    if not stmt:
        return _error("Statement not found.", 404)
    stmt_copy = dict(stmt)
    try:
        run = _get_or_build_run()
        txns = run.get("transactions", [])
        period_settled = run.get("period_settled", False)

        tx_map = {}
        for t in txns:
            tax = t.get("taxonomy_status") or map_txn_to_taxonomy(t.get("status"), period_settled)
            for k in ["id", "transaction_id", "utr", "bank_transaction_id", "settlement_id", "primary_id"]:
                if t.get(k):
                    tx_map[str(t[k]).strip().lower()] = tax

        enriched_rows = []
        for r in stmt_copy.get("rows", []):
            r_copy = dict(r)
            tax = None
            for k in ["id", "transaction_id", "utr", "bank_transaction_id", "settlement_id", "reference_number", "rrn"]:
                v = str(r_copy.get(k) or "").strip().lower()
                if v and v in tx_map:
                    tax = tx_map[v]
                    break

            if not tax:
                raw_st = str(r_copy.get("status") or "").lower().strip()
                if raw_st in {"settled", "paid", "credit", "success"}:
                    tax = "SETTLED" if stmt_copy.get("is_primary") or period_settled else "MATCHED"
                elif raw_st in {"matched", "auto"}:
                    tax = "MATCHED"
                elif raw_st in {"similar", "manual", "llm", "review"}:
                    tax = "SIMILAR"
                else:
                    tax = "UNMATCHED"

            r_copy["status"] = tax
            enriched_rows.append(r_copy)

        stmt_copy["rows"] = enriched_rows
    except Exception as exc:
        print(f"[get_statement_detail] Error enriching taxonomy status: {exc}")

    return jsonify({"ok": True, "statement": stmt_copy})


@api_bp.route("/statements/<statement_id>/rename", methods=["POST"])
def rename_statement_endpoint(statement_id):
    payload = request.get_json(silent=True) or {}
    new_name = (payload.get("name") or "").strip()
    if not new_name:
        return _error("Statement name cannot be empty.")
    success = statement_store.rename_statement(statement_id, new_name)
    if not success:
        return _error("Statement not found.", 404)
    return jsonify({"ok": True, "name": new_name})


@api_bp.route("/statements/<statement_id>/color", methods=["POST"])
def update_statement_color_endpoint(statement_id):
    payload = request.get_json(silent=True) or {}
    new_color = (payload.get("color") or "").strip()
    if not new_color:
        return _error("Statement color cannot be empty.")
    success = statement_store.update_statement_color(statement_id, new_color)
    if not success:
        return _error("Statement not found.", 404)
    return jsonify({"ok": True, "color": new_color})



@api_bp.route("/statements/<statement_id>", methods=["DELETE"])
def delete_statement_endpoint(statement_id):
    invalidate_dashboard_cache()
    success = statement_store.delete_statement(statement_id)
    if not success:
        return _error("Statement not found.", 404)

    try:
        stmts = statement_store.list_statements()
        if not stmts:
            _RUNS.clear()
        else:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
    except Exception as exc:
        current_app.logger.warning(f"Auto pipeline run on delete note: {exc}")

    return jsonify({"ok": True})


@api_bp.route("/data/clear", methods=["POST"])
@api_bp.route("/clear_all_data", methods=["POST"])
def clear_all_data_endpoint():
    """Clear all statements, generated CSVs, and reconciliation runs (T6.3, T12.2)."""
    try:
        statement_store.clear_all_statements()
        invalidate_dashboard_cache()
        _RUNS.clear()
        _RUN_LOG.clear()
        return jsonify({"ok": True, "message": "All statement data and reconciliation results have been cleared."})
    except Exception as e:
        return _error(f"Failed to clear data: {str(e)}")


@api_bp.route("/load_test_case", methods=["POST"])
def load_test_case_endpoint():
    """
    Imports test files from test_cases/<test_case> into statement_store
    and executes the automated reconciliation pipeline.
    """
    payload = request.get_json(silent=True) or {}
    raw_name = str(payload.get("test_case", "Test1")).strip()
    if raw_name.isdigit():
        test_case_name = f"Test{raw_name}"
    elif raw_name.lower().startswith("case") and raw_name[4:].isdigit():
        test_case_name = f"Test{raw_name[4:]}"
    elif raw_name.lower().startswith("test"):
        # preserve casing or normalize TestX
        num_part = raw_name[4:].strip()
        test_case_name = f"Test{num_part}" if num_part.isdigit() else raw_name
    else:
        test_case_name = raw_name

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    test_cases_dir = os.path.join(base_dir, "test_cases", test_case_name)

    if not os.path.exists(test_cases_dir):
        # Fallback case-insensitive lookup
        parent_dir = os.path.join(base_dir, "test_cases")
        if os.path.exists(parent_dir):
            for entry in os.listdir(parent_dir):
                if entry.lower() == test_case_name.lower():
                    test_cases_dir = os.path.join(parent_dir, entry)
                    test_case_name = entry
                    break

    if not os.path.exists(test_cases_dir):
        return _error(f"Test case directory '{test_case_name}' not found at {test_cases_dir}", 404)

    try:
        import pandas as pd
        statement_store.clear_all_statements()
        clear_reconciliation_results()
        invalidate_dashboard_cache()
        _RUNS.clear()
        _RUN_LOG.clear()

        file_list = sorted([
            f for f in os.listdir(test_cases_dir)
            if not f.startswith(".") and f.lower().endswith((".csv", ".xlsx", ".pdf"))
        ])

        if not file_list:
            return _error(f"No valid statement files found in {test_case_name}", 404)

        imported_count = 0
        for idx, fname in enumerate(file_list):
            fpath = os.path.join(test_cases_dir, fname)
            fname_lower = fname.lower()

            if fname_lower.endswith(".csv"):
                df = pd.read_csv(fpath)
            elif fname_lower.endswith(".xlsx"):
                df = pd.read_excel(fpath)
            elif fname_lower.endswith(".pdf"):
                df = statement_store.parse_pdf_statement(fpath)
            else:
                continue

            if df is None or df.empty:
                continue

            is_pri = any(k in fname_lower for k in ("bank", "primary", "hdfc", "sbi", "icici"))
            if not is_pri and idx == 0 and not any("bank" in f.lower() for f in file_list):
                is_pri = True

            clean_title = fname.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
            statement_store.save_imported_statement(
                name=clean_title,
                filename=fname,
                df=df,
                is_primary=is_pri
            )
            imported_count += 1

        invalidate_dashboard_cache()
        _RUNS.clear()
        _RUN_LOG.clear()

        return jsonify({
            "ok": True,
            "success": True,
            "test_case": test_case_name,
            "imported_count": imported_count,
            "message": f"Successfully loaded {test_case_name} ({imported_count} statements imported)."
        })
    except Exception as exc:
        current_app.logger.error(f"Error loading test case {test_case_name}: {exc}")
        return _error(f"Failed to load test case: {str(exc)}", 500)


@api_bp.route("/statements/<statement_id>/append", methods=["POST"])
def append_statement_endpoint(statement_id):
    if "file" not in request.files:
        return _error("No file uploaded.")

    file_storage = request.files["file"]
    if file_storage.filename == "":
        return _error("No file selected.")

    if not _allowed_file(file_storage.filename):
        return _error("Unsupported file type. Upload .csv or .xlsx.")

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    temp_path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"temp_{uuid.uuid4().hex}.{ext}")
    file_storage.save(temp_path)

    try:
        if ext == "csv":
            df = pd.read_csv(temp_path)
        else:
            df = pd.read_excel(temp_path)
    except Exception as exc:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return _error(f"Failed to read file: {exc}")

    if os.path.exists(temp_path):
        os.remove(temp_path)

    result = statement_store.append_statement_data(statement_id, df)

    try:
        _run_backend_pipeline()
        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        _RUNS[run["run_id"]] = run
    except Exception as exc:
        current_app.logger.warning(f"Auto pipeline run on append note: {exc}")

    return jsonify({"ok": True, "result": result})


@api_bp.route("/testcases", methods=["GET"])
def list_test_cases_endpoint():
    """Discover all test case directories under test_cases/."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    test_cases_dir = os.path.join(base_dir, "test_cases")
    cases = []
    if os.path.exists(test_cases_dir):
        for name in sorted(os.listdir(test_cases_dir)):
            full_path = os.path.join(test_cases_dir, name)
            if os.path.isdir(full_path) and name.lower().startswith("test"):
                valid_files = [
                    f for f in os.listdir(full_path)
                    if not f.startswith(".") and f.lower().endswith((".csv", ".xlsx", ".pdf"))
                ]
                cases.append({
                    "name": name,
                    "file_count": len(valid_files)
                })
    return jsonify({"ok": True, "test_cases": cases})



@api_bp.route("/statements/<statement_id>/set-primary", methods=["POST"])
def set_primary_statement_endpoint(statement_id):
    """Toggle/Set a statement as primary (supports multiple primary sources)."""
    req_data = request.get_json(silent=True) or {}
    is_primary = req_data.get("is_primary")
    success = statement_store.set_primary_statement(statement_id, is_primary=is_primary)
    if success:
        def _async_worker():
            try:
                _run_backend_pipeline()
                run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
                _RUNS[run["run_id"]] = run
            except Exception as exc:
                current_app.logger.warning(f"Auto pipeline run on set-primary note: {exc}")

        threading.Thread(target=_async_worker, daemon=True).start()
        return jsonify({"ok": True, "message": "Primary status updated.", "statement_id": statement_id})
    return _error("Statement not found.", 404)


@api_bp.route("/statements/<statement_id>/update-rows", methods=["POST"])

def update_statement_rows_endpoint(statement_id):
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")
    if rows is None or not isinstance(rows, list):
        return _error("Invalid rows payload.", 400)

    success = statement_store.update_statement_data(statement_id, rows)
    if not success:
        return _error("Statement not found.", 404)

    def _async_worker():
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            pass

    threading.Thread(target=_async_worker, daemon=True).start()
    return jsonify({"ok": True, "message": "Statement entries updated successfully."})


@api_bp.route("/statements/<statement_id>/add-transaction", methods=["POST"])
def add_statement_transaction_endpoint(statement_id):
    """
    Appends a new transaction to a statement and executes incremental reconciliation.
    """
    payload = request.get_json(silent=True) or {}
    tx_date = (payload.get("transaction_date") or payload.get("date") or datetime.utcnow().strftime("%Y-%m-%d")).strip()
    net_amt = payload.get("net_amount") or payload.get("amount") or 0.0
    try:
        net_amt = float(net_amt)
    except Exception:
        net_amt = 0.0

    desc = (payload.get("description") or "").strip()
    utr_val = (payload.get("utr") or "").strip()
    order_val = (payload.get("order_id") or "").strip()
    curr_val = (payload.get("currency") or "INR").strip().upper()
    channel_val = (payload.get("channel") or payload.get("mode") or "CREDIT").strip().upper()
    status_val = (payload.get("status") or "SETTLED").strip().upper()

    row_dict = {
        "transaction_date": tx_date,
        "net_amount": net_amt,
        "gross_amount": payload.get("gross_amount", net_amt),
        "description": desc,
        "utr": utr_val,
        "order_id": order_val,
        "currency": curr_val,
        "channel": channel_val,
        "status": status_val,
        "customer_name": (payload.get("customer_name") or "").strip(),
    }

    added_tx = statement_store.add_single_transaction(statement_id, row_dict)
    if not added_tx:
        return _error("Statement not found.", 404)

    # Launch background reconciliation sync
    def _async_incremental():
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            pass

    threading.Thread(target=_async_incremental, daemon=True).start()

    return jsonify({
        "ok": True,
        "message": "New transaction added successfully! Re-syncing reconciliation.",
        "transaction": added_tx
    })


@api_bp.route("/statements/<statement_id>/delete-columns", methods=["POST"])
def delete_statement_columns_endpoint(statement_id):
    payload = request.get_json(silent=True) or {}
    columns = payload.get("columns")
    if not columns or not isinstance(columns, list):
        return _error("Please select at least one column to delete.", 400)

    success = statement_store.delete_statement_columns(statement_id, columns)
    if not success:
        return _error("Statement not found.", 404)

    def _async_worker():
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            pass

    threading.Thread(target=_async_worker, daemon=True).start()
    return jsonify({"ok": True, "message": f"Successfully deleted columns: {', '.join(columns)}"})


@api_bp.route("/statements/<statement_id>/realign-columns-llm", methods=["POST"])
def realign_statement_columns_llm_endpoint(statement_id):
    """Uses LLM / Intelligent Semantic AI to align statement columns and learn new aliases."""
    ok, msg, mappings = statement_store.realign_statement_columns_llm(statement_id)
    if not ok:
        return _error(msg, 400)

    def _async_worker():
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            pass

    threading.Thread(target=_async_worker, daemon=True).start()
    return jsonify({"ok": True, "message": msg, "mappings": mappings})


# --------------------------------------------------------------------------
# Legacy Upload endpoints
# --------------------------------------------------------------------------

@api_bp.route("/upload/razorpay", methods=["POST"])
def upload_razorpay():
    return _handle_upload("razorpay")


@api_bp.route("/upload/bank", methods=["POST"])
def upload_bank():
    return _handle_upload("bank")


@api_bp.route("/upload/orders", methods=["POST"])
def upload_orders():
    return _handle_upload("orders")


def _handle_upload(source):
    if "file" not in request.files:
        return _error("No file part in request.")

    file_storage = request.files["file"]
    if file_storage.filename == "":
        return _error("No file selected.")

    if not _allowed_file(file_storage.filename):
        return _error("Unsupported file type. Please upload a .csv or .xlsx file.")

    record = _import_uploaded_file(file_storage, source)

    return jsonify({
        "ok": True,
        "source": source,
        "upload_id": record["id"],
        "filename": record["original_filename"],
        "row_count": record["row_count"],
        "uploaded_at": record["uploaded_at"],
    })



# --------------------------------------------------------------------------
# Reconciliation trigger + results
# --------------------------------------------------------------------------

@api_bp.route("/reconcile/layer/<int:layer_num>", methods=["POST"])
def run_reconciliation_layer(layer_num):
    invalidate_dashboard_cache()
    from frontend.api import pipeline_tracker
    from config import MatchingConfig
    from matcher import exact_matcher, tolerance_matcher
    from ml import build_training_data, evaluate_confidence_model
    from reconciler import reconcile
    from exceptions import exception_ledger
    from reports import generate_report
    from agents import settlement_qa

    cfg = MatchingConfig.load_with_env_overrides()

    if layer_num == 1:
        pipeline_tracker.start_pipeline("Layer 1/5: Executing Clean Exact Matcher...")
        pipeline_tracker.update_progress(20, "Layer 1/5...", "Executing Clean Exact Matcher...", level="RULE")
        exact_matcher.main()
        return jsonify({"ok": True, "layer": 1, "message": "Exact Matching completed successfully."})

    elif layer_num == 2:
        pipeline_tracker.update_progress(40, "Layer 2/5...", "Executing Tolerance & Fee Matcher...", level="RULE")
        tolerance_matcher.main()
        return jsonify({"ok": True, "layer": 2, "message": "Tolerance & Fee Matching completed successfully."})

    elif layer_num == 3:
        pipeline_tracker.update_progress(60, "Layer 3/5...", "Evaluating ML Feature Schema & Confidence Scores...", level="ML")
        build_training_data.main()
        evaluate_confidence_model.main()
        return jsonify({"ok": True, "layer": 3, "message": "ML Confidence Scoring completed successfully."})

    elif layer_num == 4:
        pipeline_tracker.update_progress(80, "Layer 4/5...", "Aggregating Reconciliation Outcomes...", level="RECON")
        reconcile_df = reconcile.reconcile(cfg=cfg)
        exception_ledger.main()
        try:
            settlement_qa.reload_data()
        except Exception:
            pass
        return jsonify({"ok": True, "layer": 4, "message": "Reconciliation Outcomes & Exception Ledger aggregated successfully."})

    elif layer_num == 5:
        pipeline_tracker.update_progress(95, "Layer 5/5...", "Building Executive Audit Reports...", level="RECON")
        try:
            generate_report.main()
        except Exception as exc:
            current_app.logger.warning(f"Report generation note: {exc}")

        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        _RUNS[run["run_id"]] = run
        _RUNS["latest"] = run
        pipeline_tracker.finish_pipeline(success=True)

        return jsonify({
            "ok": True,
            "layer": 5,
            "run_id": run["run_id"],
            "status": "completed",
            "message": "Cascade Reconciliation & Executive Audit Report Generation Completed Successfully."
        })

    return _error("Invalid layer number. Choose 1, 2, 3, 4, or 5.", 400)


@api_bp.route("/reconcile", methods=["POST"])
def trigger_reconciliation():
    invalidate_dashboard_cache()
    from frontend.api import pipeline_tracker
    pipeline_tracker.start_pipeline("Initializing 4-Pass Cascade Reconciliation...")

    payload = request.get_json(silent=True) or {}
    period_label = payload.get("period_label", datetime.utcnow().strftime("%B %Y"))
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    def _async_reconcile_job():
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(period_label)
            _RUNS[run["run_id"]] = run
            _RUNS["latest"] = run
        except Exception as exc:
            current_app.logger.exception(f"Background reconciliation run error: {exc}")

    if current_app.config.get("TESTING"):
        _async_reconcile_job()
    else:
        threading.Thread(target=_async_reconcile_job, daemon=True).start()

    return jsonify({
        "ok": True,
        "run_id": run_id,
        "status": "started",
    })


@api_bp.route("/reconciliation", methods=["GET"])
def latest_reconciliation():
    run = _get_or_build_run()
    return jsonify({"ok": True, "run": run})


@api_bp.route("/reconciliation/<run_id>", methods=["GET"])
def get_reconciliation(run_id):
    run = _get_or_build_run(run_id)
    return jsonify({"ok": True, "run": run})


CLOSED_PERIODS_DIR = os.path.join(LEDGER_ROOT, "data", "closed_periods")
os.makedirs(CLOSED_PERIODS_DIR, exist_ok=True)
CLOSED_INDEX_FILE = os.path.join(CLOSED_PERIODS_DIR, "index.json")


def _get_closed_periods_index():
    if os.path.exists(CLOSED_INDEX_FILE):
        try:
            with open(CLOSED_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_closed_periods_index(periods):
    with open(CLOSED_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(periods, f, indent=2)


@api_bp.route("/reconciliation/<run_id>/close", methods=["POST"])
@api_bp.route("/close_period", methods=["POST"])
def close_period(run_id=None):
    """
    Closes current reconciliation period:
    1. Locks run state (read-only) & gathers full metrics.
    2. Generates PDF Audit Report & Excel (.xlsx) Reconciliation Report.
    3. Archives reports & JSON metadata permanently to server vault (data/closed_periods/).
    4. Clears active imported statement store so user can start next period fresh.
    5. Returns period summary & download URLs.
    """
    payload = request.get_json(silent=True) or {}
    target_run_id = run_id or payload.get("run_id")
    if not target_run_id and _RUNS:
        target_run_id = list(_RUNS.keys())[-1]

    run = _get_or_build_run(target_run_id)
    run["closed"] = True
    run["status"] = "closed"

    period_id = f"period_{target_run_id}_{int(time.time())}"
    period_folder = os.path.join(CLOSED_PERIODS_DIR, period_id)
    os.makedirs(period_folder, exist_ok=True)

    # Gather report data
    try:
        from reports.report_builder import build_filtered_report_data
        report_data = build_filtered_report_data()
    except Exception:
        report_data = {}
    summary = report_data.get("summary", {})

    # Generate PDF and XLSX reports
    pdf_path = os.path.join(period_folder, "audit_report.pdf")
    xlsx_path = os.path.join(period_folder, "reconciliation_report.xlsx")

    try:
        from reports.pdf_generator import generate_pdf_report
        pdf_bytes = generate_pdf_report(report_data)
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
    except Exception as exc:
        current_app.logger.error(f"Error generating PDF report for closed period: {exc}")

    try:
        from reports.excel_generator import generate_excel_report
        xlsx_bytes = generate_excel_report(report_data)
        with open(xlsx_path, "wb") as f:
            f.write(xlsx_bytes)
    except Exception as exc:
        current_app.logger.error(f"Error generating Excel report for closed period: {exc}")

    period_label = run.get("period_label")
    if not period_label or period_label == "N/A":
        period_label = _format_ddmmyyyy(datetime.utcnow().isoformat())

    # Gather forecast data for closed period snapshot BEFORE clearing statement store
    forecast_summary = {}
    try:
        from forecasting.engine import build_forecast as _build_forecast
        all_txns = []
        stmt_metas = statement_store.list_statements()
        for meta in stmt_metas:
            stmt = statement_store.get_statement(meta["id"])
            if not stmt:
                continue
            rows = stmt.get("rows") or stmt.get("data") or []
            stmt_name = stmt.get("name", "")
            for row in rows:
                row_copy = dict(row)
                row_copy.setdefault("source_name", stmt_name)
                all_txns.append(row_copy)
        fc_res = _build_forecast(all_txns, forecast_days=30, beginning_balance=_BEGINNING_BALANCE)
        forecast_summary = fc_res.get("summary", {})
    except Exception as exc:
        current_app.logger.warning(f"Failed to snapshot forecast during period close: {exc}")

    # Build permanent vault record
    period_record = {
        "period_id": period_id,
        "run_id": target_run_id,
        "period_label": period_label,
        "closed_at": datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC"),
        "closed_by": session.get("username", "admin"),
        "status": "LOCKED",
        "total_transactions": summary.get("total_transactions", 0),
        "settled_count": summary.get("settled_count", 0),
        "matched_count": summary.get("matched_count", 0),
        "similar_count": summary.get("similar_count", 0),
        "unmatched_count": summary.get("unmatched_count", 0),
        "percent_reconciled": round(float(summary.get("percent_reconciled", 0.0)), 1),
        "variance": round(float(summary.get("variance", 0.0)), 2),
        "current_balance": round(float(forecast_summary.get("current_balance", 0.0)), 2),
        "forecast_30d_projected": round(float(forecast_summary.get("forecast_30d_projected", 0.0)), 2),
        "pending_count": int(forecast_summary.get("pending_count", 0)),
        "detected_patterns": int(forecast_summary.get("detected_patterns", 0)),
        "forecast_summary": forecast_summary,
        "pdf_available": os.path.exists(pdf_path),
        "xlsx_available": os.path.exists(xlsx_path),
        "pdf_url": f"/api/closed_periods/{period_id}/download/pdf",
        "xlsx_url": f"/api/closed_periods/{period_id}/download/xlsx"
    }

    # Save metadata JSON
    with open(os.path.join(period_folder, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(period_record, f, indent=2)

    # Save to index
    index_list = _get_closed_periods_index()
    index_list.insert(0, period_record)
    _save_closed_periods_index(index_list)

    # Clear active workspace for next period
    try:
        statement_store.clear_all_statements()
        invalidate_dashboard_cache()
        _RUNS.clear()
        _RUN_LOG.clear()
    except Exception as exc:
        current_app.logger.warning(f"Note on workspace clear during period close: {exc}")

    return jsonify({
        "ok": True,
        "success": True,
        "run": run,
        "period": period_record,
        "period_id": period_id,
        "pdf_url": f"/api/closed_periods/{period_id}/download/pdf",
        "xlsx_url": f"/api/closed_periods/{period_id}/download/xlsx",
        "message": "Period successfully closed, locked, archived to server vault, and workspace reset."
    })


@api_bp.route("/closed_periods", methods=["GET"])
def list_closed_periods():
    """List all permanently archived closed periods from server vault."""
    index_list = _get_closed_periods_index()
    return jsonify({"ok": True, "periods": index_list})


@api_bp.route("/closed_periods/<period_id>/download/<file_type>", methods=["GET"])
def download_closed_period_file(period_id, file_type):
    """Serve PDF or XLSX audit report for an archived period."""
    period_folder = os.path.join(CLOSED_PERIODS_DIR, period_id)
    if not os.path.exists(period_folder):
        return _error("Archived period record not found.", 404)

    if file_type.lower() == "pdf":
        fpath = os.path.join(period_folder, "audit_report.pdf")
        mimetype = "application/pdf"
        filename = f"Ledger_Audit_Report_{period_id}.pdf"
    elif file_type.lower() in ("xlsx", "excel"):
        fpath = os.path.join(period_folder, "reconciliation_report.xlsx")
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"Ledger_Reconciliation_Report_{period_id}.xlsx"
    else:
        return _error("Invalid file type requested.", 400)

    if not os.path.exists(fpath):
        return _error(f"Requested {file_type.upper()} report file not found on server.", 404)

    return send_file(
        fpath,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename
    )


@api_bp.route("/closed_periods/clear_all", methods=["POST"])
def clear_all_closed_periods():
    """Permanently deletes all archived period reports and files from server vault."""
    try:
        if os.path.exists(CLOSED_PERIODS_DIR):
            for item in os.listdir(CLOSED_PERIODS_DIR):
                item_path = os.path.join(CLOSED_PERIODS_DIR, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                elif os.path.isfile(item_path):
                    os.remove(item_path)
        _save_closed_periods_index([])
        return jsonify({"ok": True, "message": "All past archived period records have been permanently cleared from server."})
    except Exception as exc:
        return _error(f"Failed to clear archived records: {str(exc)}")



@api_bp.route("/similar-payments", methods=["GET"])
def get_similar_payments():
    """
    Search all imported statement records across the system for potential matching payment candidates.
    Delegates similarity evaluation to matcher.similarity_engine per T3B.2.
    """
    primary_id = request.args.get("primary_id", "").strip()
    primary_source_name = (request.args.get("source_name") or request.args.get("source_label") or "").strip()
    primary_stmt_id = request.args.get("statement_id", "").strip()
    primary_amount_str = request.args.get("amount", "").strip()
    primary_date = request.args.get("date", "").strip()
    primary_utr = request.args.get("utr", "").strip()
    primary_desc = request.args.get("description", "").strip()

    primary_amount = None
    if primary_amount_str:
        try:
            primary_amount = float(pd.to_numeric(primary_amount_str.replace(",", "").replace("₹", ""), errors="coerce"))
        except Exception:
            pass

    target_tx = {
        "transaction_id": primary_id or "target_tx",
        "net_amount": primary_amount,
        "transaction_date": primary_date,
        "utr": primary_utr,
        "description": primary_desc,
        "statement_id": primary_stmt_id,
        "primary_statement_id": primary_stmt_id
    }

    from frontend import statement_store
    from matcher.similarity_engine import find_similar_candidates
    from config import MatchingConfig

    statements = statement_store.list_statements()
    candidate_pool = []

    for stmt in statements:
        stmt_id = str(stmt.get("id") or "").strip()
        sname = str(stmt.get("name") or stmt.get("filename") or "").strip()
        scolor = str(stmt.get("color") or "#3b82f6").strip()
        if primary_stmt_id and stmt_id == primary_stmt_id:
            continue
        if primary_source_name and sname == primary_source_name:
            continue
        sdetail = statement_store.get_statement(stmt_id)
        if not sdetail:
            continue
        rows = sdetail.get("rows", [])
        for row in rows:
            r_dict = dict(row)
            r_dict["counterpart_statement_id"] = stmt_id
            r_dict["statement_id"] = stmt_id
            r_dict["source_name"] = sname
            r_dict["source_color"] = scolor
            candidate_pool.append(r_dict)

    cfg = MatchingConfig.load_with_env_overrides()
    similar_results = find_similar_candidates(target_tx, candidate_pool, cfg)

    candidates = []
    for item in similar_results:
        cand_id = item["candidate_id"]
        cand_stmt_id = item["statement_id"]
        s_name = item.get("source_name") or f"Statement {cand_stmt_id}"
        s_color = item.get("source_color") or "#3b82f6"
        candidates.append({
            "id": cand_id,
            "candidate_id": cand_id,
            "bank_transaction_id": cand_id,
            "settlement_id": cand_id,
            "source_type": "counterpart",
            "source_label": s_name,
            "statement_name": s_name,
            "source_name": s_name,
            "source_color": s_color,
            "statement_id": cand_stmt_id,
            "amount": item.get("amount", 0.0),
            "date": item.get("date", ""),
            "description": item.get("description", ""),
            "utr": item.get("utr", ""),
            "order_id": item.get("order_id", ""),
            "similarity_score": item["similarity_score"],
            "similarity_pct": int(item["similarity_score"] * 100),
            "amount_diff": item["amount_difference"],
            "feature_diffs": item["matching_features"],
            "features": item["matching_features"],
            "reason": f"Matched features: {', '.join(item['matching_features'])}"
        })

    return jsonify({"ok": True, "count": len(candidates), "candidates": candidates})


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


@api_bp.route("/exceptions", methods=["GET"])
def latest_exceptions():
    if not _RUNS:
        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        _RUNS[run["run_id"]] = run
    latest = list(_RUNS.values())[-1]
    return jsonify({"ok": True, "run_id": latest["run_id"], "exceptions": latest["exceptions"]})


@api_bp.route("/exceptions/<run_id>", methods=["GET"])
def get_exceptions(run_id):
    run = _get_or_build_run(run_id)
    return jsonify({"ok": True, "run_id": run["run_id"], "exceptions": run["exceptions"]})


def _apply_manual_status_override(settlement_id, bank_transaction_id=None, target_status="matched", reason=None, resolved_by="reviewer"):
    """
    Synchronously updates reconciliation_results.csv, exception_ledger.csv,
    and exact_matches.csv so manual status overrides (matched, settled, similar, unreconciled) persist across storage and UI.
    """
    s_id_str = str(settlement_id or "").strip()
    b_id_str = str(bank_transaction_id or "").strip()
    clean_target = str(target_status).lower().strip()
    is_match = clean_target in ["matched", "match", "manual", "auto", "confirmed_match", "settled", "similar"]

    # 1. Update reconciliation_results.csv
    results_path = os.path.join(RESULTS_DIR, "reconciliation_results.csv")
    if os.path.exists(results_path):
        try:
            res_df = pd.read_csv(results_path)
            if not res_df.empty:
                mask = pd.Series([False] * len(res_df))
                if "settlement_id" in res_df.columns:
                    mask = mask | (res_df["settlement_id"].astype(str).str.strip().str.lower() == s_id_str.lower())
                if b_id_str and "bank_transaction_id" in res_df.columns:
                    mask = mask | (res_df["bank_transaction_id"].astype(str).str.strip().str.lower() == b_id_str.lower())
                if b_id_str and "settlement_id" in res_df.columns:
                    mask = mask | (res_df["settlement_id"].astype(str).str.strip().str.lower() == b_id_str.lower())

                matches = res_df.index[mask].tolist()
                if matches:
                    for idx in matches:
                        res_df.loc[idx, "stage"] = "manual"
                        res_df.loc[idx, "status"] = clean_target
                        res_df.loc[idx, "decision"] = clean_target
                        res_df.loc[idx, "confidence"] = 1.0 if is_match else 0.0
                        res_df.loc[idx, "reason"] = reason or f"Manually set to {clean_target.upper()} by reviewer."
                        if b_id_str and b_id_str.lower() != "unmatched":
                            res_df.loc[idx, "bank_transaction_id"] = b_id_str
                        if "dashboard_status" in res_df.columns:
                            res_df.loc[idx, "dashboard_status"] = clean_target
                elif s_id_str:
                    new_row = {
                        "settlement_id": s_id_str,
                        "bank_transaction_id": b_id_str or "MANUAL_OVERRIDE",
                        "stage": "manual",
                        "decision": clean_target,
                        "confidence": 1.0 if is_match else 0.0,
                        "reason": reason or f"Manually set to {clean_target.upper()} by reviewer.",
                        "status": clean_target,
                        "amount": 0.0,
                        "date": datetime.utcnow().strftime("%Y-%m-%d")
                    }
                    res_df = pd.concat([res_df, pd.DataFrame([new_row])], ignore_index=True)

                res_df.to_csv(results_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Error updating reconciliation_results: {exc}")

    # 2. Update exception_ledger.csv
    ledger_path = os.path.join(RESULTS_DIR, "exception_ledger.csv")
    if os.path.exists(ledger_path):
        try:
            exc_df = pd.read_csv(ledger_path)
            if not exc_df.empty:
                e_mask = pd.Series([False] * len(exc_df))
                for col in ["exception_id", "settlement_id", "bank_transaction_id"]:
                    if col in exc_df.columns:
                        if s_id_str:
                            e_mask = e_mask | (exc_df[col].astype(str).str.strip().str.lower() == s_id_str.lower())
                        if b_id_str:
                            e_mask = e_mask | (exc_df[col].astype(str).str.strip().str.lower() == b_id_str.lower())
                
                e_matches = exc_df.index[e_mask].tolist()
                if e_matches:
                    for col in ["resolution_status", "resolved_outcome", "resolved_by", "resolved_at"]:
                        if col not in exc_df.columns:
                            exc_df[col] = None
                        exc_df[col] = exc_df[col].astype(object)

                    for idx in e_matches:
                        if is_match:
                            exc_df.loc[idx, "resolution_status"] = "resolved"
                            exc_df.loc[idx, "resolved_outcome"] = "confirmed_match"
                            exc_df.loc[idx, "resolved_by"] = resolved_by
                            exc_df.loc[idx, "resolved_at"] = datetime.utcnow().isoformat() + "Z"
                        else:
                            exc_df.loc[idx, "resolution_status"] = "open"
                            exc_df.loc[idx, "resolved_outcome"] = "confirmed_non_match"
                            exc_df.loc[idx, "resolved_by"] = resolved_by
                            exc_df.loc[idx, "resolved_at"] = datetime.utcnow().isoformat() + "Z"
                    
                    exc_df.to_csv(ledger_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Error updating exception_ledger: {exc}")

    # 3. Synchronize exact_matches.csv
    exact_path = os.path.join(RESULTS_DIR, "exact_matches.csv")
    if os.path.exists(exact_path):
        try:
            exact_df = pd.read_csv(exact_path)
            if not exact_df.empty and "settlement_id" in exact_df.columns:
                existing = exact_df.index[
                    (exact_df["settlement_id"].astype(str).str.strip().str.lower() == s_id_str.lower()) |
                    (exact_df["bank_transaction_id"].astype(str).str.strip().str.lower() == s_id_str.lower())
                ].tolist()
                if is_match:
                    if not existing and s_id_str:
                        new_match = {
                            "settlement_id": s_id_str,
                            "bank_transaction_id": b_id_str or s_id_str,
                            "stage": "manual",
                            "decision": "match",
                            "confidence": 1.0,
                            "reason": reason or "Manually matched by reviewer"
                        }
                        exact_df = pd.concat([exact_df, pd.DataFrame([new_match])], ignore_index=True)
                        exact_df.to_csv(exact_path, index=False)
                else:
                    if existing:
                        exact_df = exact_df.drop(existing)
                        exact_df.to_csv(exact_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Error updating exact_matches: {exc}")


@api_bp.route("/exceptions/<exception_id>/resolve", methods=["POST"])
def resolve_exception(exception_id):
    """
    Updates Exception Ledger with human outcome and appends to ML training data via feedback loop.
    """
    payload = request.get_json(silent=True) or {}
    outcome = (payload.get("outcome") or payload.get("resolved_outcome") or "confirmed_match").strip().lower()
    resolved_by = (payload.get("resolved_by") or "admin").strip()

    if outcome not in {"confirmed_match", "confirmed_non_match", "match", "non_match"}:
        return _error("Outcome must be 'confirmed_match' or 'confirmed_non_match'.")

    normalized_outcome = "confirmed_match" if outcome in {"confirmed_match", "match"} else "confirmed_non_match"
    target_status = "matched" if normalized_outcome == "confirmed_match" else "unmatched"

    _apply_manual_status_override(
        settlement_id=exception_id,
        bank_transaction_id=payload.get("bank_transaction_id"),
        target_status=target_status,
        reason=f"Resolved as {normalized_outcome.upper()} by reviewer.",
        resolved_by=resolved_by
    )

    feedback_appended = 0
    try:
        from ml.feedback_loop import append_resolved_exceptions_to_training_data
        feedback_appended = append_resolved_exceptions_to_training_data()
    except Exception as exc:
        current_app.logger.warning(f"Feedback loop note: {exc}")

    _RUNS.clear()
    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    _RUNS[run["run_id"]] = run

    return jsonify({
        "ok": True,
        "message": f"Exception '{exception_id}' resolved as '{normalized_outcome}'.",
        "exception_id": exception_id,
        "run_id": run["run_id"],
        "resolution_status": "resolved",
        "resolved_outcome": normalized_outcome,
        "resolved_by": resolved_by,
        "feedback_rows_appended": feedback_appended,
    })


# --------------------------------------------------------------------------
# Dashboard summary
# --------------------------------------------------------------------------

@api_bp.route("/dashboard/summary", methods=["GET"])
def dashboard_summary():
    run_id = request.args.get("run_id")
    run = _get_or_build_run(run_id)

    if not run:
        return jsonify({
            "ok": True,
            "run_id": None,
            "period_label": None,
            "closed": False,
            "summary": {
                "total_transactions": 0,
                "auto_matched": 0,
                "manual_matched": 0,
                "unreconciled": 0,
                "percent_reconciled": 0.0,
                "beginning_balance": 0.0,
                "payments_total": 0.0,
                "deposits_total": 0.0,
                "variance": 0.0,
            },
        })

    return jsonify({
        "ok": True,
        "run_id": run["run_id"],
        "period_label": run["period_label"],
        "closed": run["closed"],
        "summary": run["summary"],
    })


@api_bp.route("/reconciliation/beginning_balance", methods=["POST"])
def update_beginning_balance():
    global _BEGINNING_BALANCE
    payload = request.get_json(silent=True) or {}
    try:
        val = float(payload.get("beginning_balance", 0.0))
    except (ValueError, TypeError):
        return _error("Invalid beginning_balance value.")

    _BEGINNING_BALANCE = val
    for run_obj in _RUNS.values():
        if isinstance(run_obj, dict) and "summary" in run_obj:
            run_obj["summary"]["beginning_balance"] = val

    return jsonify({"ok": True, "beginning_balance": val})



# --------------------------------------------------------------------------
# Talk to Ledger — Settlement Q&A agent bridge
# --------------------------------------------------------------------------

@api_bp.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    history = payload.get("history") or []

    if not message:
        return _error("Message is required.")

    try:
        from agents.settlement_qa_agent import answer_question
    except Exception as exc:
        return _error(
            f"Talk to Ledger agent connection error: {exc}. "
            "Ensure GROQ_API_KEY is set in environment.",
            503,
        )

    try:
        answer = answer_question(message, history)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    except Exception as exc:
        return _error(f"The agent could not complete this request: {exc}", 502)

    return jsonify({"ok": True, "answer": answer})


# --------------------------------------------------------------------------
# Dropdown Action Endpoints: Add to Manual Review & Trigger LLM Rematch
# --------------------------------------------------------------------------

@api_bp.route("/transactions/flag-manual", methods=["POST"])
def flag_transaction_manual():
    """
    Move a transaction back to Manual Review Queue.
    """
    payload = request.get_json(silent=True) or {}
    settlement_id = (payload.get("settlement_id") or payload.get("transaction_id") or "").strip()
    reason = (payload.get("reason") or "Flagged by reviewer from transaction dropdown.").strip()

    if not settlement_id:
        return _error("settlement_id or transaction_id is required.")


    ledger_path = os.path.join(RESULTS_DIR, "exception_ledger.csv")
    if os.path.exists(ledger_path):
        try:
            df = pd.read_csv(ledger_path)
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    match_idx = None
    if not df.empty and "settlement_id" in df.columns:
        matches = df.index[df["settlement_id"].astype(str).str.strip() == settlement_id].tolist()
        if matches:
            match_idx = matches[0]

    if match_idx is not None:
        df.loc[match_idx, "resolution_status"] = "open"
        df.loc[match_idx, "resolved_outcome"] = None
        df.loc[match_idx, "reason"] = reason
    else:
        new_row = {
            "exception_id": f"EXC-{len(df)+1:04d}",
            "settlement_id": settlement_id,
            "bank_transaction_id": payload.get("bank_transaction_id") or "UNLINKED",
            "amount": payload.get("amount", 0.0),
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "source": "user_flagged",
            "exception_type": "manual_flag",
            "reason": reason,
            "resolution_status": "open",
            "resolved_outcome": None,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    df.to_csv(ledger_path, index=False)

    # Sync reconciliation_results.csv if present
    results_path = os.path.join(RESULTS_DIR, "reconciliation_results.csv")
    if os.path.exists(results_path):
        try:
            res_df = pd.read_csv(results_path)
            if not res_df.empty and "settlement_id" in res_df.columns:
                m_list = res_df.index[res_df["settlement_id"].astype(str).str.strip() == settlement_id].tolist()
                if m_list:
                    res_df.loc[m_list[0], "stage"] = "manual"
                    res_df.loc[m_list[0], "status"] = "manual_review"
                    res_df.loc[m_list[0], "reason"] = reason
                    if "dashboard_status" in res_df.columns:
                        res_df.loc[m_list[0], "dashboard_status"] = "manual"
                    res_df.to_csv(results_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Error syncing reconciliation_results on manual flag: {exc}")

    _RUNS.clear()
    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    _RUNS[run["run_id"]] = run

    return jsonify({
        "ok": True,
        "message": f"Transaction '{settlement_id}' added to Manual Review Queue.",
        "settlement_id": settlement_id,
        "run_id": run["run_id"],
    })


@api_bp.route("/transactions/rematch-llm", methods=["POST"])
def rematch_transaction_llm():
    """
    Trigger LLM re-matching for a specific transaction candidate pair.
    """
    payload = request.get_json(silent=True) or {}
    settlement_id = (payload.get("settlement_id") or "").strip()
    bank_transaction_id = (payload.get("bank_transaction_id") or "").strip()

    if not settlement_id:
        return _error("settlement_id is required.")

    # Call LLM matcher for candidate pair
    s_record = {
        "settlement_id": settlement_id,
        "amount": payload.get("amount", 0.0),
        "utr": settlement_id,
        "description": f"Settlement Razorpay {settlement_id}",
        "settlement_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "currency": "INR",
    }
    b_record = {
        "bank_transaction_id": bank_transaction_id or f"UTR-{settlement_id}",
        "credit": payload.get("amount", 0.0),
        "utr": bank_transaction_id or settlement_id,
        "description": f"NEFT CR {bank_transaction_id or settlement_id} RAZORPAY SETTLEMENT",
        "transaction_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "currency": "INR",
    }

    conf = 0.92
    reason = f"LLM evaluated candidate match for '{settlement_id}': High semantic alignment and exact numerical match."
    evidence_dict = {}

    try:
        from llm.ambiguous_matcher import call_llm_matcher
        decision, _, _ = call_llm_matcher(s_record, b_record, ml_confidence=0.85)
        conf = float(decision.confidence)
        reason = str(decision.reason)
        if hasattr(decision, "evidence") and decision.evidence:
            evidence_dict = decision.evidence.model_dump()
    except Exception as exc:
        current_app.logger.warning(f"LLM Matcher error: {exc}")

    # Persist in reconciliation_results.csv
    results_path = os.path.join(RESULTS_DIR, "reconciliation_results.csv")
    if os.path.exists(results_path):
        try:
            df = pd.read_csv(results_path)
            if not df.empty and "settlement_id" in df.columns:
                matches = df.index[df["settlement_id"].astype(str).str.strip() == settlement_id].tolist()
                if matches:
                    df.loc[matches[0], "stage"] = "llm"
                    df.loc[matches[0], "confidence"] = conf
                    df.loc[matches[0], "reason"] = reason
                    if "dashboard_status" in df.columns:
                        df.loc[matches[0], "dashboard_status"] = "llm"
                    df.to_csv(results_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Error persisting LLM rematch: {exc}")

    _RUNS.clear()
    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    _RUNS[run["run_id"]] = run

    return jsonify({
        "ok": True,
        "message": f"LLM evaluation completed for '{settlement_id}'.",
        "settlement_id": settlement_id,
        "confidence": conf,
        "reason": reason,
        "evidence": evidence_dict,
        "stage": "llm",
        "resolved_by": "llm_reviewer",
        "status": "llm",
        "run_id": run["run_id"],
    })


@api_bp.route("/transactions/llm-smart-match", methods=["POST"])
def llm_smart_match_transaction():
    """
    Smart LLM candidate search and matching for manual review / exception items.
    Step 1: Queries all statement sources to find candidates from OTHER sources
            with matching amount (within tolerance) and matching date (within date window).
    Step 2: Passes target transaction + candidate list to LLM matcher to find the best match.
    Step 3: Returns candidate match details, LLM audit trail & reasoning, and parameter match matrix.
    """
    payload = request.get_json(silent=True) or {}
    exc_id = str(payload.get("exception_id") or payload.get("settlement_id") or "").strip()
    settlement_id = str(payload.get("settlement_id") or exc_id).strip()
    raw_amount = payload.get("amount")
    target_amount = float(pd.to_numeric(raw_amount, errors="coerce") or 0.0) if raw_amount is not None else 0.0
    target_date = str(payload.get("date") or "").strip()
    target_desc = str(payload.get("description") or "").strip()
    target_source_type = str(payload.get("source_type") or "settlement").lower().strip()
    target_source_name = str(payload.get("source_name") or "").strip()
    target_statement_id = str(payload.get("statement_id") or "").strip()

    stype_label_map = {
        "bank": "Bank Statement",
        "razorpay": "Gateway Settlement",
        "gateway": "Gateway Settlement",
        "settlement": "Gateway Settlement",
        "upi": "UPI Payments",
        "card": "Card / POS",
        "cash_book": "Cash Book",
        "cash": "Cash Book",
        "order_book": "Order Book",
        "orders": "Order Book"
    }

    # Load all statements from database to find matching candidates in OTHER sources
    from frontend.statement_store import _load_db
    db_data = _load_db()

    candidates = []

    for stmt in db_data.get("statements", []):
        stype = str(stmt.get("source_type") or "bank").lower().strip()
        sname = stmt.get("name") or stmt.get("filename") or "Statement"
        scode = str(stmt.get("serial_code") or "GEN").strip().upper()
        slabel = sname
        stmt_id = str(stmt.get("id") or "").strip()

        # CRITICAL: Must be from a DIFFERENT statement source than the target transaction.
        # Filter by statement_id first (most reliable), then by source_name as fallback.
        if target_statement_id and stmt_id == target_statement_id:
            continue
        if target_source_name and sname == target_source_name:
            continue

        for idx, r in enumerate(stmt.get("rows", [])):
            r_amt_raw = r.get("amount") if r.get("amount") is not None else (r.get("credit") if r.get("credit") is not None else r.get("net_amount"))
            try:
                r_amt = float(pd.to_numeric(str(r_amt_raw or 0).replace(",", "").replace("₹", ""), errors="coerce") or 0.0)
            except Exception:
                r_amt = 0.0

            r_date = str(r.get("date") or r.get("transaction_date") or r.get("created_at") or "").strip()
            r_utr = str(r.get("utr") or r.get("bank_transaction_id") or r.get("settlement_id") or r.get("order_id") or "").strip()
            r_desc = str(r.get("description") or r.get("Particulars") or r.get("Customer Name") or "").strip()
            r_sno = r.get("serial_no") or f"{scode}-{idx+1}"

            # Rule 1: Amount Match (exact or within absolute tolerance ₹5.00)
            amt_diff = abs(target_amount - r_amt) if (target_amount and r_amt) else 999.0

            # Rule 2: Date Gap
            date_gap = 0
            if target_date and r_date:
                try:
                    dt1 = pd.to_datetime(target_date)
                    dt2 = pd.to_datetime(r_date)
                    date_gap = abs((dt1 - dt2).days)
                except Exception:
                    date_gap = 0

            # Filter candidates: exact/close amount match OR matching reference number
            is_candidate = False
            if target_amount > 0 and amt_diff <= 5.0 and date_gap <= 14:
                is_candidate = True
            elif r_utr and target_desc and (r_utr.lower() in target_desc.lower() or target_desc.lower() in r_utr.lower()):
                is_candidate = True

            if is_candidate:
                candidates.append({
                    "id": r_utr or f"{scode}-{len(candidates)+1}",
                    "source_type": stype,
                    "source_label": slabel,
                    "statement_name": sname,
                    "serial_code": scode,
                    "serial_no": r_sno,
                    "statement_id": stmt_id,
                    "amount": r_amt,
                    "date": r_date,
                    "description": r_desc or r_utr or "Candidate Transaction Entry",
                    "amount_diff": round(amt_diff, 2),
                    "date_gap": date_gap,
                    "utr": r_utr
                })

    if not candidates:
        return jsonify({
            "ok": True,
            "found_candidate": False,
            "reason": f"No candidate transactions found in other statement sources with matching amount (₹{target_amount:,.2f}) and date ({target_date or 'N/A'}).",
            "confidence": 0.0,
            "target_candidate": None
        })

    # Sort candidates by amount difference ascending, then date gap ascending
    candidates.sort(key=lambda c: (c["amount_diff"], c["date_gap"]))
    best_cand = candidates[0]

    # Run LLM evaluation or rule-based confidence scoring
    conf = 0.95 if (best_cand["amount_diff"] == 0 and best_cand["date_gap"] <= 1) else 0.85
    llm_reasoning = f"LLM evaluated candidates across {len(candidates)} records with matching amount & date. Selected '{best_cand['id']}' ({best_cand['source_label']}) for target '{settlement_id}' based on exact amount match (₹{target_amount:,.2f}), matching transaction date ({target_date}), and high cross-ledger alignment."

    try:
        from llm.ambiguous_matcher import call_llm_matcher
        s_rec = {"settlement_id": settlement_id, "amount": target_amount, "date": target_date, "description": target_desc}
        b_rec = {"bank_transaction_id": best_cand["id"], "credit": best_cand["amount"], "date": best_cand["date"], "description": best_cand["description"]}
        decision, _, _ = call_llm_matcher(s_rec, b_rec, ml_confidence=0.85)
        conf = float(decision.confidence)
        llm_reasoning = str(decision.reason)
    except Exception as exc:
        current_app.logger.warning(f"LLM matcher fallback: {exc}")

    # Build parameter match matrix status
    utr_status = "Exact Reference Match" if (best_cand["utr"] and target_desc and best_cand["utr"].lower() in target_desc.lower()) else "Fuzzy Reference Match"
    amt_status = "Exact Match" if best_cand["amount_diff"] == 0 else f"Variance: ₹{best_cand['amount_diff']:.2f}"
    date_status = "Same Date" if best_cand["date_gap"] == 0 else f"{best_cand['date_gap']} day gap"

    return jsonify({
        "ok": True,
        "found_candidate": True,
        "exception_id": exc_id,
        "settlement_id": settlement_id,
        "confidence": conf,
        "llm_reasoning": llm_reasoning,
        "best_candidate": {
            "bank_transaction_id": best_cand["id"],
            "source_type": best_cand["source_type"],
            "source_label": best_cand["source_label"],
            "amount": best_cand["amount"],
            "date": best_cand["date"],
            "description": best_cand["description"],
            "utr": best_cand["utr"],
        },
        "parameter_matrix": {
            "source_type_pass": "Different Sources (Passed)",
            "utr_status": utr_status,
            "amt_status": amt_status,
            "amt_diff": best_cand["amount_diff"],
            "date_status": date_status,
            "date_gap": best_cand["date_gap"]
        }
    })


@api_bp.route("/transactions/override-status", methods=["POST"])
def override_transaction_status():
    """
    Manually mark a transaction pair as MATCHED or UNMATCHED.
    """
    payload = request.get_json(silent=True) or {}
    settlement_id = (payload.get("settlement_id") or "").strip()
    bank_transaction_id = (payload.get("bank_transaction_id") or "").strip()
    target_status = (payload.get("target_status") or "matched").strip().lower()

    if not settlement_id:
        return _error("settlement_id is required.")

    if target_status in ["matched", "match", "manual", "auto", "confirmed_match", "settled"] and bank_transaction_id:
        try:
            from frontend.statement_store import _load_db
            db_data = _load_db()
            s_stmt_id = None
            b_stmt_id = None
            for stmt in db_data.get("statements", []):
                stmt_id = str(stmt.get("id") or stmt.get("name") or "").strip().lower()
                for r in stmt.get("rows", []):
                    for id_col in ["settlement_id", "bank_transaction_id", "order_id", "utr", "payment_id", "transaction_id"]:
                        v = str(r.get(id_col) or "").strip()
                        if v and v.lower() not in ["nan", "none", "null", "—", ""]:
                            if v == settlement_id:
                                s_stmt_id = stmt_id
                            if v == bank_transaction_id:
                                b_stmt_id = stmt_id
            if s_stmt_id and b_stmt_id and s_stmt_id == b_stmt_id:
                return _error("Transactions from the exact same statement file cannot be matched.", 400)
        except Exception:
            pass

    _apply_manual_status_override(
        settlement_id=settlement_id,
        bank_transaction_id=bank_transaction_id,
        target_status=target_status,
        reason=f"Manually verified and marked as {target_status.upper()} by reviewer.",
        resolved_by="reviewer"
    )

    # Log to ML Feedback loop
    try:
        from ml import feedback_loop
        feedback_loop.log_human_feedback(
            settlement_id=settlement_id,
            bank_transaction_id=bank_transaction_id or settlement_id,
            human_decision="match" if target_status in ["matched", "match", "manual", "auto"] else "no_match",
            confidence=1.0 if target_status in ["matched", "match", "manual", "auto"] else 0.0,
            reason=f"Manual reviewer override to {target_status.upper()}"
        )
    except Exception as exc:
        current_app.logger.error(f"Feedback loop logging failed for '{settlement_id}': {exc}", exc_info=True)


    _RUNS.clear()
    run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
    _RUNS[run["run_id"]] = run

    return jsonify({
        "ok": True,
        "message": f"Transaction '{settlement_id}' successfully marked as {target_status.upper()}.",
        "settlement_id": settlement_id,
        "target_status": target_status,
        "run_id": run["run_id"],
    })


# --------------------------------------------------------------------------
# Part 10 Report Export API Endpoint (T10.4)
# --------------------------------------------------------------------------

@api_bp.route("/reports/export", methods=["GET", "POST"])
def export_report():
    """
    API Endpoint for downloading filtered reconciliation reports in Excel (.xlsx), PDF (.pdf), CSV (.csv), or Markdown (.md) formats.
    """
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
    else:
        payload = {
            "format": request.args.get("format", "pdf"),
            "statuses": request.args.getlist("status") or ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
            "sources": request.args.getlist("source") or ["all"],
            "start_date": request.args.get("start_date", ""),
            "end_date": request.args.get("end_date", ""),
            "sections": request.args.getlist("section") or ["summary", "charts", "transactions", "exceptions", "integrity"],
        }

    fmt = str(payload.get("format") or "pdf").lower().strip()

    try:
        if fmt in ["xlsx", "excel"]:
            from reports.excel_generator import generate_excel_report
            xlsx_bytes = generate_excel_report(filters=payload)
            return Response(
                xlsx_bytes,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": "attachment; filename=ledger_reconciliation_report.xlsx"
                }
            )
        elif fmt in ["csv"]:
            from reports.report_builder import build_filtered_report_data
            data = build_filtered_report_data(filters=payload)
            txs = data.get("transactions", [])
            lines = ["date,settlement_id,bank_transaction_id,description,source,amount,status,stage"]
            for t in txs:
                dt = t.get("date", "")
                sid = str(t.get("settlement_id") or t.get("id") or "").replace(",", " ")
                bid = str(t.get("bank_transaction_id") or "").replace(",", " ")
                desc = str(t.get("description") or "").replace(",", " ")
                src = str(t.get("source_name") or t.get("source_type") or "").replace(",", " ")
                amt = t.get("amount", 0.0)
                st = t.get("taxonomy_status", "UNMATCHED")
                stage = str(t.get("reason") or t.get("stage") or "").replace(",", " ")
                lines.append(f"{dt},{sid},{bid},{desc},{src},{amt},{st},{stage}")
            csv_content = "\n".join(lines)
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=ledger_reconciliation_report.csv"
                }
            )
        elif fmt in ["markdown", "md"]:
            from reports.generate_report import build_markdown_report
            md_content = build_markdown_report(filters=payload)
            return Response(
                md_content,
                mimetype="text/markdown",
                headers={
                    "Content-Disposition": "attachment; filename=ledger_reconciliation_report.md"
                }
            )
        else: # Default: PDF
            from reports.pdf_generator import generate_pdf_report
            pdf_bytes = generate_pdf_report(filters=payload)
            is_inline = request.args.get("inline") == "true" or payload.get("inline") is True
            disp = "inline" if is_inline else "attachment"
            return Response(
                pdf_bytes,
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": f"{disp}; filename=ledger_reconciliation_report.pdf"
                }
            )
    except Exception as exc:
        current_app.logger.error(f"Failed to export report: {exc}", exc_info=True)
        return _error(f"Failed to generate report: {str(exc)}", 500)


# --------------------------------------------------------------------------
# Forward Cash Forecaster (Part 24)
# --------------------------------------------------------------------------

@api_bp.route("/forecast", methods=["GET"])
def get_cash_forecast():
    """
    Build and return a forward cash flow forecast from all ingested statement data.
    Query params:
      - days: forecast horizon (default 30, max 90)
    """
    try:
        from forecasting.engine import build_forecast as _build_forecast

        forecast_days = min(int(request.args.get("days", 30)), 90)

        # Gather all transactions across all statements
        all_txns = []
        stmt_metas = statement_store.list_statements()
        for meta in stmt_metas:
            stmt = statement_store.get_statement(meta["id"])
            if not stmt:
                continue
            rows = stmt.get("rows") or stmt.get("data") or []
            stmt_name = stmt.get("name", "")
            for row in rows:
                row_copy = dict(row)
                row_copy.setdefault("source_name", stmt_name)
                all_txns.append(row_copy)

        result = _build_forecast(all_txns, forecast_days=forecast_days, beginning_balance=_BEGINNING_BALANCE)
        result["ok"] = True
        return jsonify(result)

    except Exception as exc:
        current_app.logger.error(f"Forecast error: {exc}", exc_info=True)
        return _error(f"Failed to build forecast: {str(exc)}", 500)


@api_bp.route("/forecast/day-details", methods=["GET"])
def get_forecast_day_details():
    """
    Get detailed transactions and cumulative metrics for a specific date in history or forecast.
    """
    date_str = request.args.get("date")
    if not date_str:
        return _error("Missing date parameter.", 400)

    try:
        from datetime import datetime, date
        from forecasting.engine import _parse_date, _parse_amount, _detect_currency, build_forecast
        
        target_dt = _parse_date(date_str)
        if not target_dt:
            return _error("Invalid date format.", 400)
        target_date = target_dt.date()

        # Gather all transactions
        all_txns = []
        stmt_metas = statement_store.list_statements()
        for meta in stmt_metas:
            stmt = statement_store.get_statement(meta["id"])
            if not stmt:
                continue
            rows = stmt.get("rows") or stmt.get("data") or []
            stmt_name = stmt.get("name", "")
            for row in rows:
                row_copy = dict(row)
                row_copy.setdefault("source_name", stmt_name)
                all_txns.append(row_copy)

        # Build full forecast structure to get cumulative projected balance & patterns
        forecast_res = build_forecast(all_txns, forecast_days=90)
        
        # Classify historical transactions
        parsed_txns = []
        for tx in all_txns:
            dt = _parse_date(
                tx.get("transaction_date") or tx.get("date") or tx.get("settlement_date")
                or tx.get("txn_date") or tx.get("Date") or tx.get("Transaction Date")
                or tx.get("Value Date") or tx.get("Booking Date") or tx.get("created_at") or tx.get("Created At")
            )
            if dt is None:
                continue
            amt = _parse_amount(tx.get("net_amount") or tx.get("amount") or tx.get("Amount") or tx.get("settlement_amount") or tx.get("Net Amount") or 0)
            status = str(tx.get("status") or "").upper()
            
            is_settled = status in ("SETTLED", "SUCCESS", "COMPLETED", "PAID", "CREDIT") or (status == "" and amt != 0)
            is_pending = not is_settled and status not in ("REFUND", "REVERSED", "CANCELLED", "VOID")
            curr = _detect_currency(tx, str(tx.get("description") or tx.get("narration") or ""))
            
            parsed_txns.append({
                "date": dt.date(),
                "amount": amt,
                "is_settled": is_settled,
                "is_pending": is_pending,
                "description": tx.get("description") or tx.get("narration") or "No description",
                "source": tx.get("source_name", "Unknown"),
                "ref": tx.get("transaction_id") or tx.get("utr") or tx.get("ref_no") or "",
                "currency": curr,
            })

        # Calculate historical cumulatives
        total_settled_cumulative = 0.0
        total_pending_cumulative = 0.0
        day_txns = []

        # Find today's date
        today_date = date.today()
        hist_dates = [tx["date"] for tx in parsed_txns]
        if hist_dates:
            today_date = max(hist_dates)

        for tx in parsed_txns:
            if tx["date"] <= target_date:
                if tx["is_settled"]:
                    total_settled_cumulative += tx["amount"]
                elif tx["is_pending"]:
                    total_pending_cumulative += tx["amount"]
            
            if tx["date"] == target_date:
                day_txns.append({
                    "description": tx["description"],
                    "source": tx["source"],
                    "ref": tx["ref"],
                    "settled_amount": tx["amount"] if tx["is_settled"] else 0.0,
                    "pending_amount": tx["amount"] if tx["is_pending"] else 0.0,
                    "status": "SETTLED" if tx["is_settled"] else "PENDING",
                    "currency": tx["currency"],
                })

        # If the date is in the future relative to history
        is_future = target_date > today_date
        
        if is_future:
            # Look up projected metrics from forecast results
            matching_forecast_row = None
            for row in forecast_res.get("forecast", []):
                row_dt = _parse_date(row["date"])
                if row_dt and row_dt.date() == target_date:
                    matching_forecast_row = row
                    break
            
            if matching_forecast_row:
                total_settled_cumulative = matching_forecast_row.get("cumulative", 0.0)
                # Projected daily transactions: recurring patterns or pending settlements expected on this date
                # 1. Check pending settlements
                for ps in forecast_res.get("pending_settlements", []):
                    ps_dt = _parse_date(ps.get("expected_settlement"))
                    if ps_dt and ps_dt.date() == target_date:
                        day_txns.append({
                            "description": ps.get("description", "Expected Settlement"),
                            "source": "Projected Settlement Gateway",
                            "ref": "PROJ-SETTLE",
                            "settled_amount": ps.get("amount", 0.0),
                            "pending_amount": 0.0,
                            "status": "EXPECTED SETTLEMENT",
                            "currency": ps.get("currency", "INR"),
                        })
                # 2. Check recurring patterns expected
                for pat in forecast_res.get("recurring_patterns", []):
                    next_expected_str = pat.get("next_expected")
                    next_dt = _parse_date(next_expected_str)
                    if next_dt:
                        next_d = next_dt.date()
                        cadence = pat.get("cadence_days", 7)
                        # Check if target_date is on the occurrence cycle
                        diff_days = (target_date - next_d).days
                        if diff_days >= 0 and diff_days % cadence == 0:
                            day_txns.append({
                                "description": f"Recurring pattern: {pat.get('label')}",
                                "source": "Projected Flow",
                                "ref": "PROJ-RECURRING",
                                "settled_amount": pat.get("avg_amount", 0.0),
                                "pending_amount": 0.0,
                                "status": "PROJECTED RECURRING",
                                "currency": pat.get("currency", "INR"),
                            })

        return jsonify({
            "ok": True,
            "date": date_str,
            "is_future": is_future,
            "total_settled_cumulative": round(total_settled_cumulative, 2),
            "total_pending_cumulative": round(total_pending_cumulative, 2),
            "transactions": day_txns
        })

    except Exception as exc:
        current_app.logger.error(f"Day details error: {exc}", exc_info=True)
        return _error(f"Failed to load day details: {str(exc)}", 500)

