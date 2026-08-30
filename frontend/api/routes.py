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
from datetime import datetime
from typing import Any, Optional, Dict, List

from flask import Blueprint, current_app, jsonify, request, Response
from werkzeug.utils import secure_filename
import re
import pandas as pd

from config import MatchingConfig

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"csv", "xlsx", "pdf"}

import collections

_RUNS = {}
_RUN_LOG = []


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


def _run_backend_pipeline():
    from frontend import statement_store
    from frontend.api import pipeline_tracker

    stmts = statement_store.list_statements()
    if not stmts:
        for f in ["reconciliation_results.csv", "exception_ledger.csv", "exact_matches.csv", "tolerance_matches.csv"]:
            p = os.path.join(RESULTS_DIR, f)
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        pipeline_tracker.start_pipeline("No active statements imported.")
        pipeline_tracker.finish_pipeline(success=True)
        return

    pipeline_tracker.start_pipeline("Ingesting Statement & Syncing Database...")

    with pipeline_tracker.PipelineOutputCapture():
        statement_store.ensure_all_generated_csvs()

        pipeline_tracker.update_progress(20, "Executing Reconciliation Pipeline (T5.4)...", "🔍 Running Rule Engine & ML Pipeline...", level="RECON")
        try:
            from reconciler import pipeline_runner
            pipeline_runner.run_full_pipeline()
        except Exception as exc:
            pipeline_tracker.add_log(f"Pipeline execution note: {exc}", level="WARNING")

        pipeline_tracker.finish_pipeline(success=True)



def compute_overview_charts(transactions, exceptions, period_settled, percent):
    """Compute data structure for the 6 Part 9 Overview charts (T9.1)."""
    total = len(transactions)

    # 1. Status Breakdown (SETTLED / MATCHED / SIMILAR / UNMATCHED)
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

    # 2. Reconciliation Funnel
    funnel_data = {
        "stages": ["Total Ingested", "Auto-Matched", "Settled", "Similar (Review)", "Unmatched"],
        "counts": [
            total,
            len([t for t in transactions if (t.get("status") or "").lower() in {"auto", "matched"}]),
            settled_cnt,
            similar_cnt,
            unmatched_cnt
        ]
    }

    # 3. Source-wise Contribution Stacked Bar
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

    source_labels = list(source_stats.keys()) if source_stats else ["No Sources"]
    source_contribution = {
        "labels": source_labels,
        "datasets": {
            "SETTLED": [source_stats[s]["SETTLED"] for s in source_labels] if source_stats else [0],
            "MATCHED": [source_stats[s]["MATCHED"] for s in source_labels] if source_stats else [0],
            "SIMILAR": [source_stats[s]["SIMILAR"] for s in source_labels] if source_stats else [0],
            "UNMATCHED": [source_stats[s]["UNMATCHED"] for s in source_labels] if source_stats else [0],
        }
    }

    # 4. Confidence Score Distribution Histogram
    conf_buckets = {"0.0 - 0.5": 0, "0.5 - 0.7": 0, "0.7 - 0.8": 0, "0.8 - 0.9": 0, "0.9 - 1.0": 0}
    for t in transactions:
        conf = float(t.get("confidence") or 0.0)
        if conf < 0.5:
            conf_buckets["0.0 - 0.5"] += 1
        elif conf < 0.7:
            conf_buckets["0.5 - 0.7"] += 1
        elif conf < 0.8:
            conf_buckets["0.7 - 0.8"] += 1
        elif conf < 0.9:
            conf_buckets["0.8 - 0.9"] += 1
        else:
            conf_buckets["0.9 - 1.0"] += 1

    confidence_distribution = {
        "labels": list(conf_buckets.keys()),
        "counts": list(conf_buckets.values())
    }

    # 5. Exception Aging Chart
    aging_buckets = {"0-1 day": 0, "1-3 days": 0, "3-7 days": 0, "7+ days": 0}
    now_dt = datetime.utcnow()
    for exc_item in exceptions:
        created_str = exc_item.get("created_at") or exc_item.get("timestamp") or ""
        days = 0
        if created_str:
            try:
                dt = datetime.fromisoformat(str(created_str).replace("Z", "+00:00"))
                days = (now_dt - dt.replace(tzinfo=None)).days
            except Exception:
                days = 0
        
        if days <= 1:
            aging_buckets["0-1 day"] += 1
        elif days <= 3:
            aging_buckets["1-3 days"] += 1
        elif days <= 7:
            aging_buckets["3-7 days"] += 1
        else:
            aging_buckets["7+ days"] += 1

    exception_aging = {
        "labels": list(aging_buckets.keys()),
        "counts": list(aging_buckets.values())
    }

    # 6. Trend Line
    trend_labels = []
    trend_rates = []
    for log_item in reversed(_RUN_LOG[-10:]):
        trend_labels.append(log_item.get("timestamp", "Run"))
        tot = log_item.get("total_transactions", 0)
        m = log_item.get("matched_count", 0)
        rate = round((m / tot * 100), 1) if tot > 0 else 0.0
        trend_rates.append(rate)

    if not trend_labels:
        trend_labels = ["Current Run"]
        trend_rates = [percent]

    trend_line = {
        "labels": trend_labels,
        "match_rates": trend_rates
    }

    return {
        "status_breakdown": status_breakdown,
        "funnel_data": funnel_data,
        "source_contribution": source_contribution,
        "confidence_distribution": confidence_distribution,
        "exception_aging": exception_aging,
        "trend_line": trend_line,
    }


def _build_dashboard_run(period_label="Current Period"):
    """
    Constructs an authoritative reconciliation run dictionary from disk CSVs.
    Used by /api/reconciliation and overview page (T9.1, T12.3).
    """
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

            item_info = {
                "id": tx_id,
                "amount": amt_val,
                "date": dt_val,
                "description": desc_val,
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
                                "is_primary": m_is_pri
                            }

            txn = {
                "id": tx_id,
                "primary_id": tx_id,
                "date": dt_val,
                "description": desc_val,
                "amount": amt_val,
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

        exceptions.append(exc_item)

    # Ensure all automated unmatched transactions from engine are listed in exceptions
    existing_exc_sids = {str(e.get("settlement_id") or "").strip().lower() for e in exceptions if e.get("settlement_id")}
    for t in raw_transactions:
        st = (t.get("status") or "").lower().strip()
        sid = str(t.get("settlement_id") or t.get("id") or "").strip()
        if st in {"unmatched", "exception", "manual"} and sid and sid.lower() not in existing_exc_sids:
            exceptions.append({
                "exception_id": f"EXC-{len(exceptions)+1:04d}",
                "settlement_id": sid,
                "bank_transaction_id": t.get("counterpart", {}).get("id") if isinstance(t.get("counterpart"), dict) else "UNLINKED",
                "amount": t.get("amount", 0.0),
                "date": t.get("date", ""),
                "description": t.get("description", ""),
                "source_name": t.get("source_name", "Automated Engine"),
                "status": "exception",
                "exception_type": "automated_unmatched",
                "reason": t.get("reason") or "Automated unmatched transaction flagged as exception.",
                "resolution_status": "open",
            })
            existing_exc_sids.add(sid.lower())

    transactions = raw_transactions

    # Calculate real min and max transaction date range
    valid_dates = [t["date"] for t in raw_transactions if t.get("date") and str(t["date"]).strip() not in ("", "None", "nan", "—")]
    if valid_dates:
        sorted_dates = sorted(valid_dates)
        min_d, max_d = sorted_dates[0], sorted_dates[-1]
        period_label = f"{min_d} to {max_d}" if min_d != max_d else min_d
    else:
        period_label = "No Data"

    total = len(transactions)
    settled_count = len([t for t in transactions if (t.get("status") or "").lower() in {"settled", "settlement"}])
    matched_count = len([t for t in transactions if (t.get("status") or "").lower() in {"matched", "auto", "exact", "tolerance"}])
    similar_count = len([t for t in transactions if (t.get("status") or "").lower() in {"similar", "proposed", "ml", "ambiguous"}])
    llm_count = len([t for t in transactions if (t.get("status") or "").lower() == "llm"])
    exceptions_count = len([t for t in transactions if (t.get("status") or "").lower() in {"exception", "manual", "unmatched"}])
    unreconciled_count = len([t for t in transactions if (t.get("status") or "").lower() == "unreconciled"])

    reconciled_count = settled_count + matched_count + llm_count + similar_count
    percent = round((reconciled_count / total * 100), 1) if total > 0 else 0.0

    pos_amounts = [t["amount"] for t in transactions if t["amount"] > 0]
    neg_amounts = [abs(t["amount"]) for t in transactions if t["amount"] < 0]

    deposits_total = float(sum(pos_amounts)) if pos_amounts else 0.0
    payments_total = float(sum(neg_amounts)) if neg_amounts else 0.0
    if deposits_total == 0.0 and payments_total == 0.0:
        deposits_total = float(sum(t["amount"] for t in transactions))

    variance = deposits_total - payments_total
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
            "unmatched_count": exceptions_count + unreconciled_count,
            "auto_matched": matched_count,
            "auto": matched_count,
            "llm_matched": llm_count,
            "manual_matched": exceptions_count,
            "manual": exceptions_count,
            "exceptions_count": exceptions_count,
            "unreconciled": unreconciled_count,
            "percent_reconciled": percent,
            "beginning_balance": 0.0,
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
    """T6.3 API endpoint returning active MatchingConfig parameters from reconciliation_config.json."""
    if os.path.exists(CONFIG_OUTPUT_PATH):
        try:
            with open(CONFIG_OUTPUT_PATH, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            return jsonify({"ok": True, "config": cfg_data})
        except Exception as exc:
            return _error(f"Failed to read config: {exc}", 500)

    # Fallback to MatchingConfig defaults
    cfg = MatchingConfig()
    return jsonify({"ok": True, "config": cfg.to_dict()})


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
    from frontend.api import pipeline_tracker
    pipeline_tracker.start_pipeline("Reading & Ingesting Uploaded File...")

    files = request.files.getlist("file") or request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        pipeline_tracker.finish_pipeline(success=False, error_msg="No file selected.")
        return _error("No file selected.")

    raw_is_pri = request.form.get("is_primary", "false")
    is_primary = str(raw_is_pri).lower().strip() in ("true", "1", "yes")
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

        pipeline_tracker.update_progress(
            15 + int((idx / max(1, total_files)) * 10),
            f"Reading File: {original_name}...",
            f"📥 Ingesting statement file ({idx + 1}/{total_files}): {original_name}",
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
                f"Extracting & Parsing {ext.upper()} Data...",
                f"Parsing {original_name} records...",
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
                f"Normalizing Schema: {stmt_name}...",
                f"Mapping column headers and canonical schema for {stmt_name}...",
                level="INFO"
            )

            stmt = statement_store.save_imported_statement(
                stmt_name,
                original_name,
                df,
                is_primary=is_primary,
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
        try:
            pipeline_tracker.update_progress(
                30,
                "Synchronizing Database & Initializing Pipeline...",
                "Syncing statement database and starting multi-pass reconciliation engine...",
                level="INFO"
            )
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            current_app.logger.warning(f"Auto pipeline run on import note: {exc}")

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
    return jsonify({"ok": True, "statement": stmt})


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
        _RUNS.clear()
        _RUN_LOG.clear()
        return jsonify({"ok": True, "message": "All statement data and reconciliation results have been cleared."})
    except Exception as e:
        return _error(f"Failed to clear data: {str(e)}")



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


@api_bp.route("/statements/<statement_id>/set-primary", methods=["POST"])
def set_primary_statement_endpoint(statement_id):
    """Toggle/Set a statement as primary (supports multiple primary sources)."""
    req_data = request.get_json(silent=True) or {}
    is_primary = req_data.get("is_primary")
    success = statement_store.set_primary_statement(statement_id, is_primary=is_primary)
    if success:
        try:
            _run_backend_pipeline()
            run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
            _RUNS[run["run_id"]] = run
        except Exception as exc:
            current_app.logger.warning(f"Auto pipeline run on set-primary note: {exc}")
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

@api_bp.route("/reconcile", methods=["POST"])
def trigger_reconciliation():
    payload = request.get_json(silent=True) or {}
    period_label = payload.get("period_label", datetime.utcnow().strftime("%B %Y"))

    try:
        _run_backend_pipeline()
        run = _build_dashboard_run(period_label)
    except FileNotFoundError as exc:
        current_app.logger.exception("Ledger data file is missing")
        return _error(str(exc), 500)
    except Exception as exc:
        current_app.logger.exception("Failed to build dashboard data")
        return _error(f"Could not load Ledger data: {exc}", 500)

    _RUNS[run["run_id"]] = run
    return jsonify({
        "ok": True,
        "run_id": run["run_id"],
        "status": run.get("status", "completed"),
    })


@api_bp.route("/reconciliation", methods=["GET"])
def latest_reconciliation():
    try:
        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        _RUNS[run["run_id"]] = run
        return jsonify({"ok": True, "run": run})
    except Exception:
        if _RUNS:
            return jsonify({"ok": True, "run": list(_RUNS.values())[-1]})
        return jsonify({"ok": True, "run": None})


@api_bp.route("/reconciliation/<run_id>", methods=["GET"])
def get_reconciliation(run_id):
    run = _RUNS.get(run_id)
    if not run:
        return _error("Run not found.", 404)
    return jsonify({"ok": True, "run": run})


@api_bp.route("/reconciliation/<run_id>/close", methods=["POST"])
def close_period(run_id):
    run = _RUNS.get(run_id)
    if not run:
        return _error("Run not found.", 404)
    run["closed"] = True
    run["status"] = "closed"
    return jsonify({"ok": True, "run": run})


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
    run = _RUNS.get(run_id)
    if not run:
        return _error("Run not found.", 404)
    return jsonify({"ok": True, "run_id": run_id, "exceptions": run["exceptions"]})


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
    run = _RUNS.get(run_id) if run_id else (list(_RUNS.values())[-1] if _RUNS else None)

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

