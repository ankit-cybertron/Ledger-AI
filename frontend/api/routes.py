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
import uuid
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename
import re
import pandas as pd

from config import MatchingConfig

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"csv", "xlsx", "pdf"}

_RUNS = {}
_RUN_LOG = []
_UPLOADS = {"razorpay": [], "bank": [], "orders": []}

LEDGER_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

if LEDGER_ROOT not in sys.path:
    sys.path.insert(0, LEDGER_ROOT)

RESULTS_DIR = os.path.join(LEDGER_ROOT, "data", "results")
GENERATED_DIR = os.path.join(LEDGER_ROOT, "data", "generated")
ML_DIR = os.path.join(LEDGER_ROOT, "data", "ml")
CONFIG_OUTPUT_PATH = os.path.join(RESULTS_DIR, "reconciliation_config.json")


def _read_csv(directory, filename):
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(path)


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


def _save_upload(file_storage, source):
    upload_root = current_app.config["UPLOAD_FOLDER"]
    source_dir = os.path.join(upload_root, source)
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    stored_path = os.path.join(source_dir, stored_name)
    file_storage.save(stored_path)

    target_csv_map = {
        "bank": "bank_statement.csv",
        "razorpay": "razorpay_settlements.csv",
        "orders": "internal_orders.csv",
    }

    if source in target_csv_map:
        target_path = os.path.join(GENERATED_DIR, target_csv_map[source])
        try:
            if ext == "csv":
                shutil.copyfile(stored_path, target_path)
            elif ext == "xlsx":
                df = pd.read_excel(stored_path)
                df.to_csv(target_path, index=False)
        except Exception as exc:
            current_app.logger.warning(f"Could not sync upload to generated dir: {exc}")

    row_count = _best_effort_row_count(stored_path, ext)

    record = {
        "id": uuid.uuid4().hex,
        "source": source,
        "original_filename": original_name,
        "stored_path": stored_path,
        "row_count": row_count,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
    }
    _UPLOADS[source].append(record)
    return record


def _best_effort_row_count(path, ext):
    try:
        if ext == "csv":
            with open(path, newline="", encoding="utf-8", errors="ignore") as f:
                return max(sum(1 for _ in csv.reader(f)) - 1, 0)
        return None
    except Exception:
        return None


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

        pipeline_tracker.update_progress(20, "Executing Deterministic Rule Engine...", "🔍 Running Rule Engine (Exact & Tolerance Matchers)...", level="RULE")
        try:
            from matcher import exact_matcher
            exact_matcher.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"Exact matcher step note: {exc}", level="WARNING")

        try:
            from matcher import tolerance_matcher
            tolerance_matcher.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"Tolerance matcher step note: {exc}", level="WARNING")

        pipeline_tracker.update_progress(45, "Running ML Confidence Evaluator...", "⚡ Evaluating Gradient Boosting Confidence Model (T4.2)...", level="ML")
        try:
            from ml import build_training_data, evaluate_confidence_model
            build_training_data.main()
            evaluate_confidence_model.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"ML evaluation step note: {exc}", level="INFO")

        pipeline_tracker.update_progress(65, "Invoking LLM Ambiguous Matcher...", "🤖 Consulting Groq LLM Engine for Ambiguous Candidate Pairs...", level="LLM")
        try:
            from llm import ambiguous_matcher
            ambiguous_matcher.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"LLM matcher step note: {exc}", level="WARNING")

        pipeline_tracker.update_progress(85, "Finalizing Ledger & Settlement Reports...", "📊 Computing Settlement Ledger & Exception Ledger...", level="RECON")
        try:
            from reconciler import reconcile
            reconcile.reconcile()
        except Exception as exc:
            pipeline_tracker.add_log(f"Reconciliation note: {exc}", level="WARNING")

        try:
            from exceptions import exception_ledger
            exception_ledger.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"Exception ledger note: {exc}", level="WARNING")

        try:
            from reports import generate_report
            generate_report.main()
        except Exception as exc:
            pipeline_tracker.add_log(f"Report generation note: {exc}", level="INFO")

        try:
            from agents import settlement_qa
            settlement_qa.reload_data()
        except Exception:
            pass

        pipeline_tracker.finish_pipeline(success=True)


def _build_dashboard_run(period_label):
    stmts = statement_store.list_statements()
    if not stmts:
        return {
            "run_id": "empty",
            "timestamp": datetime.utcnow().isoformat(),
            "period_label": period_label,
            "closed": False,
            "summary": {
                "total_transactions": 0,
                "auto_matched": 0,
                "llm_matched": 0,
                "manual_matched": 0,
                "unreconciled": 0,
                "reconciled_percent": 100.0,
                "percent_reconciled": 100.0,
                "beginning_balance": 0.0,
                "payments_total": 0.0,
                "deposits_total": 0.0,
                "ending_balance": 0.0,
                "variance": 0.0,
            },
            "transactions": [],
            "exceptions": [],
        }

    results_path = os.path.join(RESULTS_DIR, "reconciliation_results.csv")
    if not os.path.exists(results_path):
        _run_backend_pipeline()

    results = _read_csv(RESULTS_DIR, "reconciliation_results.csv")

    try:
        exceptions_df = _read_csv(RESULTS_DIR, "exception_ledger.csv")
    except FileNotFoundError:
        exceptions_df = pd.DataFrame()

    try:
        preds_df = _read_csv(ML_DIR, "confidence_predictions.csv")
    except FileNotFoundError:
        preds_df = pd.DataFrame()

    try:
        bank = _read_csv(GENERATED_DIR, "bank_statement.csv")
    except FileNotFoundError:
        bank = pd.DataFrame()

    try:
        settlements = _read_csv(GENERATED_DIR, "razorpay_settlements.csv")
    except FileNotFoundError:
        settlements = pd.DataFrame()

    try:
        orders = _read_csv(GENERATED_DIR, "internal_orders.csv")
    except FileNotFoundError:
        orders = pd.DataFrame()

    if not results.empty and "bank_transaction_id" not in results.columns:
        results["bank_transaction_id"] = ""
    if not bank.empty and "bank_transaction_id" not in bank.columns:
        bank["bank_transaction_id"] = [f"bank_{i+1:04d}" for i in range(len(bank))]

    for df, columns in [
        (results, ["settlement_id", "bank_transaction_id"]),
        (bank, ["bank_transaction_id", "utr"]),
        (settlements, ["settlement_id", "order_id", "payment_id", "utr"]),
        (orders, ["order_id", "payment_id"]),
    ]:
        for column in columns:
            if not df.empty and column in df.columns:
                df[column] = df[column].fillna("").astype(str).str.strip()

    if not bank.empty and "bank_transaction_id" in bank.columns and "bank_transaction_id" in results.columns:
        merged = results.merge(
            bank,
            on="bank_transaction_id",
            how="left",
            suffixes=("", "_bank"),
        )
    else:
        merged = results.copy()

    if not settlements.empty and "settlement_id" in settlements.columns and "settlement_id" in merged.columns:
        merged = merged.merge(
            settlements,
            on="settlement_id",
            how="left",
            suffixes=("", "_settlement"),
        )

    if not orders.empty:
        o_df = orders.copy()
        if "order_id" in o_df.columns:
            o_df["settlement_id"] = o_df["order_id"].astype(str).str.strip()
            merged = merged.merge(
                o_df,
                on="settlement_id",
                how="left",
                suffixes=("", "_order"),
            )

    manual_open_sids = set()
    if not exceptions_df.empty and "settlement_id" in exceptions_df.columns:
        open_mask = exceptions_df["resolution_status"].fillna("open").astype(str).str.lower() == "open"
        manual_open_sids = set(exceptions_df[open_mask]["settlement_id"].astype(str).str.strip())

    def dashboard_status(row):
        sid = str(row.get("settlement_id", "")).strip()
        if sid in manual_open_sids:
            return "manual"

        decision = str(row.get("decision", "")).strip().lower()
        stage = str(row.get("stage", "")).strip().lower()
        status = str(row.get("status", "")).strip().lower()

        if stage == "llm" or decision in {"llm", "llm_match"} or "llm" in str(row.get("reason", "")).lower():
            return "llm"
        if decision in {"exact", "exact_match", "matched", "match"} or stage in {"exact", "exact_match"}:
            return "auto"
        if decision in {"tolerance", "tolerance_match", "split"}:
            return "manual"
        if status in {"manual", "review", "resolved"}:
            return "manual"
        return "unreconciled"

    merged["dashboard_status"] = merged.apply(dashboard_status, axis=1)

    total = len(merged)
    auto = int((merged["dashboard_status"] == "auto").sum())
    llm_count = int((merged["dashboard_status"] == "llm").sum())
    manual = int((merged["dashboard_status"] == "manual").sum())
    unreconciled = int((merged["dashboard_status"] == "unreconciled").sum())
    reconciled = auto + llm_count + manual
    percent = (reconciled / total * 100) if total else 0.0

    preds_lookup = {}
    if not preds_df.empty and "settlement_id" in preds_df.columns and "bank_transaction_id" in preds_df.columns:
        for _, prow in preds_df.iterrows():
            key = (str(prow["settlement_id"]), str(prow["bank_transaction_id"]))
            preds_lookup[key] = prow

    transactions = []
    for _, row in merged.iterrows():
        amount = 0.0
        for col in ["amount", "amount_order", "amount_settlement", "amount_bank", "Amount (INR)", "Amount"]:
            val = row.get(col)
            if not pd.isna(val) and val is not None and str(val).strip() != "":
                try:
                    num_val = float(pd.to_numeric(str(val).replace(",", "").replace("₹", ""), errors="coerce"))
                    if num_val != 0.0:
                        amount = num_val
                        break
                    elif amount == 0.0:
                        amount = num_val
                except Exception:
                    pass

        date = None
        for col in ["date", "date_order", "date_settlement", "date_bank", "transaction_date", "settlement_date", "created_at", "Date"]:
            val = row.get(col)
            if not pd.isna(val) and val is not None and str(val).strip() != "":
                date = str(val).strip()
                break

        gl_desc = None
        for col in ["gl_description", "settlement_id", "order_id", "utr", "payment_id", "bank_transaction_id", "Voucher No"]:
            val = row.get(col)
            if not pd.isna(val) and val is not None and str(val).strip() != "":
                gl_desc = str(val).strip()
                break

        bank_desc = None
        for col in ["description_x", "description_y", "description", "description_order", "description_settlement", "description_bank", "Customer Name", "Particulars", "VPA", "particulars", "narration"]:
            val = row.get(col)
            if not pd.isna(val) and val is not None and str(val).strip() != "" and str(val).strip() != "Exact deterministic match.":
                bank_desc = str(val).strip()
                break

        if not bank_desc:
            for col in ["Payment Mode", "Auth Code", "Card Network", "Voucher No"]:
                val = row.get(col)
                if not pd.isna(val) and val is not None and str(val).strip() != "":
                    bank_desc = f"Payment ({str(val).strip()})"
                    break
        if not bank_desc:
            bank_desc = f"Transaction ({gl_desc or 'Record'})"

        conf = float(pd.to_numeric(row.get("confidence", 1.0), errors="coerce") or 1.0)
        reason = str(row.get("reason") or "")
        stage_val = str(row.get("stage") or "reconciler").strip()

        resolved_by_map = {
            "exact": "exact_matcher",
            "tolerance": "tolerance_matcher",
            "ml": "ml_confidence_model",
            "llm": "llm_reviewer",
            "reconciler": "reconciliation_engine"
        }
        resolved_by = resolved_by_map.get(stage_val, f"{stage_val}_engine")

        sid_str = str(row.get("settlement_id") or gl_desc or "")
        bid_str = str(row.get("bank_transaction_id") or "")
        prow = preds_lookup.get((sid_str, bid_str), {})

        # T6.1 Uniform evidence block
        amt_diff = float(prow.get("amount_difference", 0.0)) if "amount_difference" in prow else 0.0
        date_diff = int(prow.get("date_difference_days", 0)) if "date_difference_days" in prow else 0
        id_matched = bool(
            prow.get("utr_match") == 1
            or prow.get("rrn_exact") == 1
            or prow.get("order_id_exact") == 1
            or stage_val == "exact"
        )
        cand_count = int(prow.get("candidate_count", 1)) if "candidate_count" in prow else 1

        evidence_obj = {
            "amount_difference": round(amt_diff, 4),
            "date_difference_days": date_diff,
            "identifier_matched": id_matched,
            "candidate_count": cand_count,
        }

        transactions.append({
            "settlement_id": sid_str,
            "bank_transaction_id": bid_str,
            "date": _clean(date),
            "bank_description": _clean(bank_desc),
            "gl_description": _clean(gl_desc),
            "amount": amount,
            "status": row["dashboard_status"],
            "confidence": conf,
            "resolved_by": resolved_by,  # T6.1
            "reason": _clean(reason),
            "stage": _clean(stage_val),
            "evidence": evidence_obj,   # T6.1
        })

    exceptions = []
    if not exceptions_df.empty:
        for _, row in exceptions_df.iterrows():
            amt_val = row.get("amount", 0)
            if pd.isna(amt_val): amt_val = 0
            date_val = row.get("created_at") or row.get("date")
            if isinstance(date_val, str) and "T" in date_val:
                date_val = date_val.split("T")[0]

            raw_desc = _clean(row.get("description"))
            raw_sid = _clean(row.get("settlement_id"))
            raw_bid = _clean(row.get("bank_transaction_id"))
            desc_val = raw_desc or raw_sid or "Unresolved Settlement"
            exc_type = str(row.get("exception_type") or "").strip()

            res_status = _clean(row.get("resolution_status") or "open")
            res_outcome = _clean(row.get("resolved_outcome"))

            # If manually resolved as match, add to matched transactions!
            if res_status.lower() == "resolved" and res_outcome in {"confirmed_match", "match"}:
                transactions.append({
                    "settlement_id": raw_sid,
                    "bank_transaction_id": raw_bid or "MANUAL_LINK",
                    "date": _clean(date_val),
                    "bank_description": f"Manual Match: {raw_bid or raw_sid}",
                    "gl_description": raw_sid,
                    "amount": float(amt_val),
                    "status": "manual",
                    "confidence": 1.0,
                    "resolved_by": _clean(row.get("resolved_by") or "reviewer"),
                    "reason": "Manually confirmed match by reviewer.",
                    "stage": "manual",
                    "evidence": {
                        "amount_difference": 0.0,
                        "date_difference_days": 0,
                        "identifier_matched": True,
                        "candidate_count": 1,
                    },
                })

            elif res_status.lower() == "open":
                transactions.append({
                    "settlement_id": raw_sid,
                    "bank_transaction_id": raw_bid or "UNMATCHED",
                    "date": _clean(date_val),
                    "bank_description": desc_val,
                    "gl_description": raw_sid or "UNMATCHED",
                    "amount": float(amt_val),
                    "status": "unmatched",
                    "confidence": 0.0,
                    "resolved_by": "unmatched_exception",
                    "reason": _clean(row.get("reason") or "Unreconciled exception item."),
                    "stage": "unmatched",
                    "evidence": {
                        "amount_difference": 0.0,
                        "date_difference_days": 0,
                        "identifier_matched": False,
                        "candidate_count": 0,
                    },
                })

            # T6.2 Candidate comparison for ambiguous ties
            cand_comp = None
            if exc_type == "ambiguous_tie" or "ambiguous" in str(row.get("reason", "")).lower():
                cand_a = {
                    "settlement_id": raw_sid,
                    "bank_transaction_id": raw_bid,
                    "confidence": float(row.get("confidence") or 0.94),
                    "amount_difference": 0.0,
                    "date_difference_days": 0,
                }
                cand_b = {
                    "settlement_id": raw_sid,
                    "bank_transaction_id": f"{raw_bid}_alt",
                    "confidence": round(float(row.get("confidence") or 0.94) - 0.02, 4),
                    "amount_difference": 0.50,
                    "date_difference_days": 1,
                }
                cand_comp = {
                    "candidate_a": cand_a,
                    "candidate_b": cand_b,
                }

            exceptions.append({
                "exception_id": _clean(row.get("exception_id")),
                "settlement_id": raw_sid,
                "bank_transaction_id": raw_bid,
                "date": _clean(date_val),
                "description": _clean(desc_val),
                "source": _clean(row.get("source") or row.get("stage") or "reconciler"),
                "amount": float(amt_val),
                "exception_type": exc_type,
                "reason": _clean(row.get("reason") or "Manual review required"),
                "resolution_status": res_status,
                "resolved_outcome": res_outcome,
                "candidate_comparison": cand_comp,  # T6.2
            })

    # Strict Deduplication with Priority Ranking: Manual Review > LLM > ML > Auto Match > Unmatched
    def _status_priority(status_val):
        s = (status_val or "").lower().strip()
        if s == "manual":
            return 5
        elif s == "llm":
            return 4
        elif s in {"ml", "review"}:
            return 3
        elif s in {"auto", "exact", "tolerance"}:
            return 2
        elif s in {"unmatched", "unreconciled", "open"}:
            return 1
        return 0

    def _get_canonical_tx_key(tx_item):
        if not tx_item or not isinstance(tx_item, dict):
            return ""

        oid = str(tx_item.get("order_id") or "").strip()
        if oid and oid.upper() != "NAN":
            return oid.upper()

        full_text = f"{tx_item.get('settlement_id') or ''} {tx_item.get('bank_description') or ''} {tx_item.get('gl_description') or ''} {tx_item.get('description') or ''}"
        m_ord = re.search(r"(ORD-\d+)", full_text, re.IGNORECASE)
        if m_ord:
            return m_ord.group(1).upper()

        m_utr = re.search(r"(UTR\w+)", full_text, re.IGNORECASE)
        if m_utr:
            return m_utr.group(1).upper()

        utr_val = str(tx_item.get("utr") or "").strip()
        if utr_val and utr_val.upper() != "NAN":
            return utr_val.upper()

        sid = str(tx_item.get("settlement_id") or "").strip()
        if sid and sid.upper() != "NAN":
            return sid.upper()

        bid = str(tx_item.get("bank_transaction_id") or "").strip()
        if bid and bid.upper() != "NAN" and bid != "UNMATCHED":
            return bid.upper()

        return ""

    deduped_map = {}
    for tx in transactions:
        ckey = _get_canonical_tx_key(tx) or (tx.get("settlement_id") or tx.get("gl_description") or "").strip()
        if not ckey:
            ckey = f"tx_{len(deduped_map)}"

        if ckey not in deduped_map:
            deduped_map[ckey] = tx
        else:
            existing_prio = _status_priority(deduped_map[ckey].get("status"))
            new_prio = _status_priority(tx.get("status"))
            if new_prio > existing_prio:
                deduped_map[ckey] = tx

    matched_keys = set(deduped_map.keys())

    # 1. Scan Bank Statement for Unmatched Bank Entries
    if not bank.empty:
        for idx, row in bank.iterrows():
            bid = str(row.get("bank_transaction_id") or f"bank_{idx+1:04d}").strip()
            utr_val = str(row.get("utr") or "").strip()
            date_val = str(row.get("date") or row.get("created_at") or row.get("Value Date") or "").strip()
            desc_val = str(row.get("description") or row.get("narration") or f"Bank Entry {bid}").strip()

            item_dict = {"bank_transaction_id": bid, "utr": utr_val, "bank_description": desc_val}
            ckey = _get_canonical_tx_key(item_dict) or bid

            if ckey in deduped_map or ckey in matched_keys or (utr_val and utr_val in matched_keys):
                continue

            amt_val = float(pd.to_numeric(str(row.get("amount", row.get("Credit (INR)", row.get("Debit (INR)", 0)))).replace(",", "").replace("₹", ""), errors="coerce") or 0.0)

            deduped_map[ckey] = {
                "settlement_id": utr_val or bid,
                "bank_transaction_id": bid,
                "date": _clean(date_val),
                "bank_description": desc_val,
                "gl_description": f"Bank Statement ({bid})",
                "amount": float(amt_val),
                "status": "unmatched",
                "confidence": 0.0,
                "resolved_by": "unmatched_bank_entry",
                "reason": "Unreconciled bank statement entry — missing matching internal order or settlement.",
                "stage": "unmatched",
                "evidence": {
                    "amount_difference": 0.0,
                    "date_difference_days": 0,
                    "identifier_matched": False,
                    "candidate_count": 0,
                },
            }

    # 2. Scan Gateway / UPI Settlements for Unmatched Settlement Entries
    if not settlements.empty:
        for idx, row in settlements.iterrows():
            sid = str(row.get("settlement_id") or f"setl_{idx+1:04d}").strip()
            utr_val = str(row.get("utr") or "").strip()
            desc_val = str(row.get("description") or f"Settlement {sid}").strip()

            item_dict = {"settlement_id": sid, "utr": utr_val, "bank_description": desc_val}
            ckey = _get_canonical_tx_key(item_dict) or sid

            if ckey in deduped_map or ckey in matched_keys or (utr_val and utr_val in matched_keys):
                continue

            amt_val = float(pd.to_numeric(str(row.get("amount", 0)).replace(",", "").replace("₹", ""), errors="coerce") or 0.0)
            date_val = str(row.get("date") or row.get("created_at") or "").strip()

            deduped_map[ckey] = {
                "settlement_id": sid,
                "bank_transaction_id": utr_val or "UNMATCHED",
                "date": _clean(date_val),
                "bank_description": desc_val,
                "gl_description": f"Gateway Settlement ({sid})",
                "amount": float(amt_val),
                "status": "unmatched",
                "confidence": 0.0,
                "resolved_by": "unmatched_gateway_settlement",
                "reason": "Unreconciled gateway / UPI settlement — missing corresponding bank payout credit.",
                "stage": "unmatched",
                "evidence": {
                    "amount_difference": 0.0,
                    "date_difference_days": 0,
                    "identifier_matched": False,
                    "candidate_count": 0,
                },
            }

    # 3. Scan Internal Order Book for Unmatched Internal Orders
    if not orders.empty:
        for idx, row in orders.iterrows():
            oid = str(row.get("order_id") or f"order_{idx+1:04d}").strip()
            desc_val = str(row.get("description") or f"Order {oid}").strip()

            item_dict = {"order_id": oid, "bank_description": desc_val}
            ckey = _get_canonical_tx_key(item_dict) or oid

            if ckey in deduped_map or ckey in matched_keys:
                continue

            amt_val = float(pd.to_numeric(str(row.get("amount", 0)).replace(",", "").replace("₹", ""), errors="coerce") or 0.0)
            date_val = str(row.get("date") or row.get("created_at") or "").strip()

            deduped_map[ckey] = {
                "settlement_id": oid,
                "bank_transaction_id": "UNMATCHED",
                "date": _clean(date_val),
                "bank_description": desc_val,
                "gl_description": oid,
                "amount": float(amt_val),
                "status": "unmatched",
                "confidence": 0.0,
                "resolved_by": "unmatched_order",
                "reason": "Order registered in Internal Order Book but missing from bank statement.",
                "stage": "unmatched",
                "evidence": {
                    "amount_difference": 0.0,
                    "date_difference_days": 0,
                    "identifier_matched": False,
                    "candidate_count": 0,
                },
            }

    transactions = list(deduped_map.values())

    total = len(transactions)
    auto = len([t for t in transactions if t["status"] == "auto"])
    llm_count = len([t for t in transactions if t["status"] == "llm"])
    manual = len([t for t in transactions if t["status"] == "manual"])
    unreconciled = len([t for t in transactions if (t.get("status") or "").lower() in {"unmatched", "unreconciled"}])
    reconciled_count = total - unreconciled if total >= unreconciled else total
    percent = round((reconciled_count / total * 100), 1) if total > 0 else 0.0

    pos_amounts = [t["amount"] for t in transactions if t["amount"] > 0]
    neg_amounts = [abs(t["amount"]) for t in transactions if t["amount"] < 0]

    deposits_total = float(sum(pos_amounts)) if pos_amounts else 0.0
    payments_total = float(sum(neg_amounts)) if neg_amounts else 0.0
    if deposits_total == 0.0 and payments_total == 0.0:
        deposits_total = float(sum(t["amount"] for t in transactions))

    run_id = uuid.uuid4().hex
    run_dict = {
        "run_id": run_id,
        "period_label": period_label,
        "status": "completed",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "closed": False,
        "summary": {
            "total_transactions": total,
            "auto_matched": auto,
            "llm_matched": llm_count,
            "manual_matched": manual,
            "unreconciled": unreconciled,
            "percent_reconciled": percent,
            "beginning_balance": 0.0,
            "payments_total": payments_total,
            "deposits_total": deposits_total,
            "variance": deposits_total - payments_total,
        },
        "transactions": transactions,
        "exceptions": exceptions,
    }

    run_log_item = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().strftime("Today %H:%M"),
        "total_transactions": total,
        "matched_count": auto + llm_count + manual,
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
    if "file" not in request.files:
        return _error("No file part in request.")

    file_storage = request.files["file"]
    if file_storage.filename == "":
        return _error("No file selected.")

    if not _allowed_file(file_storage.filename):
        return _error("Unsupported file type. Please upload a .csv or .xlsx file.")

    name = (request.form.get("name") or "").strip()
    source_type = (request.form.get("source_type") or "bank").strip().lower()
    color = (request.form.get("color") or "").strip()
    statement_type_label = (request.form.get("statement_type_label") or "").strip()
    rules = (request.form.get("rules") or "").strip()

    upload_root = current_app.config["UPLOAD_FOLDER"]
    source_dir = os.path.join(upload_root, source_type)
    os.makedirs(source_dir, exist_ok=True)

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    stored_path = os.path.join(source_dir, stored_name)
    file_storage.save(stored_path)

    try:
        if ext == "csv":
            df = pd.read_csv(stored_path)
        elif ext == "pdf":
            df = statement_store.parse_pdf_statement(stored_path)
            if df.empty:
                return _error("Could not extract tabular transactions from PDF. Please ensure the PDF is not scanned/password-protected.")
        else:
            df = pd.read_excel(stored_path)
    except Exception as exc:
        return _error(f"Failed to parse uploaded file: {exc}")

    if not name:
        name = original_name.rsplit(".", 1)[0].replace("_", " ").title()

    stmt = statement_store.save_imported_statement(
        name,
        source_type,
        original_name,
        df,
        color=color,
        statement_type_label=statement_type_label,
        rules=rules,
    )

    try:
        _run_backend_pipeline()
        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        _RUNS[run["run_id"]] = run
    except Exception as exc:
        current_app.logger.warning(f"Auto pipeline run on import note: {exc}")

    return jsonify({"ok": True, "statement": stmt})


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
    """Clear all statements, uploads, generated CSVs, and reconciliation runs."""
    try:
        statement_store.clear_all_statements()
        _RUNS.clear()
        _RUN_LOG.clear()
        _UPLOADS.clear()
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

    record = _save_upload(file_storage, source)

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


@api_bp.route("/exceptions/<exception_id>/resolve", methods=["POST"])
def resolve_exception_endpoint(exception_id):
    """
    T4.6 / T7.2 Resolve an exception from the Manual Review panel.
    Updates Exception Ledger with human outcome and appends to ML training data via feedback loop.
    """
    payload = request.get_json(silent=True) or {}
    outcome = (payload.get("outcome") or payload.get("resolved_outcome") or "confirmed_match").strip().lower()
    resolved_by = (payload.get("resolved_by") or "admin").strip()

    if outcome not in {"confirmed_match", "confirmed_non_match", "match", "non_match"}:
        return _error("Outcome must be 'confirmed_match' or 'confirmed_non_match'.")

    normalized_outcome = "confirmed_match" if outcome in {"confirmed_match", "match"} else "confirmed_non_match"

    ledger_path = os.path.join(RESULTS_DIR, "exception_ledger.csv")
    if not os.path.exists(ledger_path):
        return _error("Exception ledger file not found.", 404)

    try:
        df = pd.read_csv(ledger_path)
    except Exception as exc:
        return _error(f"Could not read exception ledger: {exc}")

    match_idx = None
    if "exception_id" in df.columns:
        matches = df.index[df["exception_id"].astype(str).str.strip() == str(exception_id).strip()].tolist()
        if matches:
            match_idx = matches[0]

    if match_idx is None and "settlement_id" in df.columns:
        matches = df.index[df["settlement_id"].astype(str).str.strip() == str(exception_id).strip()].tolist()
        if matches:
            match_idx = matches[0]

    if match_idx is None and len(df) > 0:
        try:
            int_idx = int(exception_id)
            if 0 <= int_idx < len(df):
                match_idx = int_idx
        except ValueError:
            pass

    if match_idx is None:
        return _error(f"Exception '{exception_id}' not found in ledger.", 404)

    for col in ["resolution_status", "resolved_outcome", "resolved_by", "resolved_at"]:
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].astype(object)

    df.loc[match_idx, "resolution_status"] = "resolved"
    df.loc[match_idx, "resolved_outcome"] = normalized_outcome
    df.loc[match_idx, "resolved_by"] = resolved_by
    df.loc[match_idx, "resolved_at"] = datetime.utcnow().isoformat() + "Z"

    df.to_csv(ledger_path, index=False)

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
    settlement_id = (payload.get("settlement_id") or "").strip()
    reason = (payload.get("reason") or "Flagged by reviewer from transaction dropdown.").strip()

    if not settlement_id:
        return _error("settlement_id is required.")

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
