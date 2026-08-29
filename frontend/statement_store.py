"""
statement_store.py — Persistent local store & DB manager for user-imported statements.

Handles metadata, raw statement rows, renaming, deletion, and incremental appending.
Delegates all file reading, column mapping, numeric parsing, normalization, and deduplication
to ingestion/*.py engines (single source of truth).
"""

import json
import os
import random
import shutil
import string
import threading
import time
from typing import List, Dict, Any, Tuple
import pandas as pd

from ingestion.file_reader import read_source_file, RawTable, _detect_and_promote_header_row
from ingestion.column_mapper import map_columns, ColumnMapping
from ingestion.normalizer import normalize_row, parse_numeric, _generate_clean_fallback_tx_id
from ingestion.dedupe import detect_duplicates
from ingestion.duplicate_columns import detect_duplicate_columns
from schema import CanonicalTransaction

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DB_FILE = os.path.join(DATA_DIR, "statements_db.json")

def generate_unique_serial_code(existing_codes=None):
    """Generate a random 3-letter uppercase code (e.g. ABC, XYZ) guaranteed unique across statements."""
    if existing_codes is None:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                existing_codes = {s.get("serial_code") for s in d.get("statements", []) if s.get("serial_code")}
        except Exception:
            existing_codes = set()
    for _ in range(1000):
        code = "".join(random.choices(string.ascii_uppercase, k=3))
        if code not in existing_codes:
            return code
    return "".join(random.choices(string.ascii_uppercase, k=3))

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({"statements": []}, f, indent=2)

def parse_pdf_statement(file_path):
    """
    Delegates PDF statement parsing to ingestion.file_reader for unified ingestion pipeline.
    Returns DataFrame matching table layout.
    """
    tables = read_source_file(file_path)
    if tables and tables[0].rows:
        return pd.DataFrame(tables[0].rows)
    return pd.DataFrame()


def _sanitize_statement_row(r, stmt_name=""):
    """
    Sanitizes a row dictionary using ingestion.normalizer.parse_numeric and cleans up legacy synthetic fallback IDs.
    """
    if not isinstance(r, dict):
        return r

    tx_id = str(r.get("transaction_id") or r.get("bank_transaction_id") or "").strip()
    if tx_id.startswith("TX_RW_") or ".XLSX_" in tx_id or ".CSV_" in tx_id or tx_id.startswith("TX_"):
        src_file = r.get("source_file") or stmt_name or "bank"
        row_num = r.get("source_row_number") or 1
        clean_id = _generate_clean_fallback_tx_id(src_file, row_num)
        r["transaction_id"] = clean_id
        r["bank_transaction_id"] = clean_id

    raw_amt = r.get("amount") or r.get("net_amount")
    cr_amt = parse_numeric(r.get("credit") or r.get("credit_amount"))
    dr_amt = parse_numeric(r.get("debit") or r.get("debit_amount"))

    amt_val = parse_numeric(raw_amt)
    if amt_val is None:
        if cr_amt is not None or dr_amt is not None:
            c = cr_amt or 0.0
            d = dr_amt or 0.0
            amt_val = round(c - d, 2)

    r["amount"] = amt_val if amt_val is not None else 0.0
    return r


_DB_LOCK = threading.Lock()


def _load_db():
    _ensure_data_dir()
    seed_file = DB_FILE.replace(".json", "_seed.json")
    if not os.path.exists(DB_FILE) and os.path.exists(seed_file):
        try:
            shutil.copy(seed_file, DB_FILE)
        except Exception:
            pass

    with _DB_LOCK:
        for attempt in range(5):
            try:
                if not os.path.exists(DB_FILE):
                    return {"statements": []}
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                existing_codes = {s.get("serial_code") for s in data.get("statements", []) if s.get("serial_code")}
                needs_save = False
                for stmt in data.get("statements", []):
                    if not stmt.get("serial_code"):
                        stmt["serial_code"] = generate_unique_serial_code(existing_codes)
                        existing_codes.add(stmt["serial_code"])
                        needs_save = True
                    scode = stmt["serial_code"]
                    if "rows" in stmt and isinstance(stmt["rows"], list):
                        sanitized = []
                        for idx, r in enumerate(stmt["rows"]):
                            sr = _sanitize_statement_row(r, stmt.get("name"))
                            if isinstance(sr, dict):
                                expected_serial = f"{scode}-{idx + 1}"
                                if sr.get("serial_no") != expected_serial or sr.get("serial_code") != scode:
                                    sr["serial_no"] = expected_serial
                                    sr["serial_code"] = scode
                                    needs_save = True
                            sanitized.append(sr)
                        stmt["rows"] = sanitized
                if needs_save:
                    _save_db_unlocked(data)
                return data
            except (json.JSONDecodeError, OSError):
                time.sleep(0.05)
        return {"statements": []}


def _save_db_unlocked(data):
    _ensure_data_dir()
    tmp_file = DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_file, DB_FILE)


def _save_db(data):
    with _DB_LOCK:
        _save_db_unlocked(data)

STATEMENT_COLOR_PALETTE = [
    "#3b82f6",  # Vibrant Blue
    "#10b981",  # Emerald Green
    "#8b5cf6",  # Purple Accent
    "#f59e0b",  # Amber Gold
    "#ec4899",  # Bright Pink
    "#06b6d4",  # Cyan / Teal
    "#f97316",  # Warm Orange
    "#6366f1",  # Indigo
    "#14b8a6",  # Mint / Jade
    "#e11d48",  # Rose Red
]

def list_statements():
    """List all imported statements metadata without full row payload."""
    db = _load_db()
    results = []
    statements = db.get("statements", [])
    for idx, s in enumerate(statements):
        is_pri = s.get("is_primary", False)
        palette_color = STATEMENT_COLOR_PALETTE[idx % len(STATEMENT_COLOR_PALETTE)]
        saved_color = s.get("color")
        if not saved_color or saved_color in ("#6f89ff", "#f04f4f", "#3b82f6", "#4C8DFF"):
            color_val = palette_color
        else:
            color_val = saved_color

        results.append({
            "id": s["id"],
            "name": s["name"],
            "serial_code": s.get("serial_code", "GEN"),
            "is_primary": is_pri,
            "color": color_val,
            "filename": s["filename"],
            "row_count": s["row_count"],
            "created_at": s["created_at"],
            "updated_at": s.get("updated_at", s["created_at"]),
        })
    return results

def get_statement(statement_id):
    """Retrieve full statement details including row data."""
    db = _load_db()
    statements = db.get("statements", [])
    for idx, s in enumerate(statements):
        if s["id"] == statement_id:
            res = dict(s)
            palette_color = STATEMENT_COLOR_PALETTE[idx % len(STATEMENT_COLOR_PALETTE)]
            saved_color = s.get("color")
            if not saved_color or saved_color in ("#6f89ff", "#f04f4f", "#3b82f6", "#4C8DFF"):
                res["color"] = palette_color
            return res
    return None

DEFAULT_HEADERS = {
    "primary": ["transaction_id", "transaction_date", "net_amount", "gross_amount", "credit_amount", "debit_amount", "utr", "description", "customer_name", "status", "is_primary"],
    "counterpart": ["transaction_id", "transaction_date", "net_amount", "gross_amount", "credit_amount", "debit_amount", "utr", "order_id", "settlement_id", "auth_code", "description", "customer_name", "status", "is_primary"],
}

def ensure_all_generated_csvs():
    """Ensure all required generated CSV files exist with headers for matcher engine compatibility."""
    gen_dir = os.path.join(DATA_DIR, "generated")
    os.makedirs(gen_dir, exist_ok=True)
    target_csv_map = {
        "primary_records": os.path.join(gen_dir, "primary_records.csv"),
        "counterpart_records": os.path.join(gen_dir, "counterpart_records.csv"),
        "primary": os.path.join(gen_dir, "bank_statement.csv"),
        "razorpay": os.path.join(gen_dir, "razorpay_settlements.csv"),
        "orders": os.path.join(gen_dir, "internal_orders.csv"),
    }
    for key, path in target_csv_map.items():
        if not os.path.exists(path):
            headers = DEFAULT_HEADERS["primary"] if key in ("primary_records", "primary") else DEFAULT_HEADERS["counterpart"]
            df = pd.DataFrame(columns=headers)
            df.to_csv(path, index=False)


def rebuild_generated_csv():
    """
    Combines all active statements split into two pools per T2.6:
    Primary pool (is_primary==True) -> primary_records.csv (& bank_statement.csv)
    Counterpart pool (is_primary==False) -> counterpart_records.csv (& razorpay_settlements.csv, internal_orders.csv)
    """
    db = _load_db()

    gen_dir = os.path.join(DATA_DIR, "generated")
    os.makedirs(gen_dir, exist_ok=True)

    primary_records_path = os.path.join(gen_dir, "primary_records.csv")
    counterpart_records_path = os.path.join(gen_dir, "counterpart_records.csv")

    primary_bank_path = os.path.join(gen_dir, "bank_statement.csv")
    settlements_path = os.path.join(gen_dir, "razorpay_settlements.csv")
    orders_path = os.path.join(gen_dir, "internal_orders.csv")

    primary_rows = []
    counterpart_rows = []

    for s in db.get("statements", []):
        is_pri = s.get("is_primary", False)
        rows = s.get("rows", [])
        if not rows:
            continue
        clean_rows = [r for r in rows if not _is_summary_dict_row(r)]
        if is_pri:
            primary_rows.extend(clean_rows)
        else:
            counterpart_rows.extend(clean_rows)

    # Save Primary CSVs
    if primary_rows:
        df_pri = pd.DataFrame(primary_rows)
        df_pri.to_csv(primary_records_path, index=False)
        df_pri.to_csv(primary_bank_path, index=False)
    else:
        df_empty = pd.DataFrame(columns=DEFAULT_HEADERS["primary"])
        df_empty.to_csv(primary_records_path, index=False)
        df_empty.to_csv(primary_bank_path, index=False)

    # Save Counterpart CSVs
    if counterpart_rows:
        df_cnt = pd.DataFrame(counterpart_rows)
        df_cnt.to_csv(counterpart_records_path, index=False)
        df_cnt.to_csv(settlements_path, index=False)
        df_cnt.to_csv(orders_path, index=False)
    else:
        df_empty = pd.DataFrame(columns=DEFAULT_HEADERS["counterpart"])
        df_empty.to_csv(counterpart_records_path, index=False)
        df_empty.to_csv(settlements_path, index=False)
        df_empty.to_csv(orders_path, index=False)


SUMMARY_ROW_KEYWORDS = [
    "total", "grand total", "subtotal", "total amount", "summary",
    "closing balance", "opening balance", "balance b/f", "balance c/f",
    "total:", "sub-total", "total count"
]

def _is_summary_dict_row(r: dict) -> bool:
    for v in r.values():
        if v is None or pd.isna(v):
            continue
        s_val = str(v).strip().lower()
        if not s_val:
            continue
        for kw in SUMMARY_ROW_KEYWORDS:
            if s_val == kw or s_val.startswith(f"{kw} ") or s_val.startswith(f"{kw}:") or s_val == f"{kw}:":
                return True
    return False

def normalize_statement_columns(df, is_primary=False, source_file="uploaded_file"):
    """
    Delegates column mapping, duplicate column detection (T2.7), and row normalization
    entirely to ingestion/*.py pipeline (column_mapper, duplicate_columns, normalizer).
    Returns tuple of (normalized DataFrame, dropped_columns list, explanations list).
    """
    if df is None or df.empty:
        return pd.DataFrame(), [], []

    df = _detect_and_promote_header_row(df)

    # Filter summary/total rows from raw DataFrame
    clean_df_rows = []
    for _, r_series in df.iterrows():
        r_dict = r_series.to_dict()
        if not _is_summary_dict_row(r_dict):
            clean_df_rows.append(r_dict)
    
    if clean_df_rows:
        df = pd.DataFrame(clean_df_rows)
    else:
        df = pd.DataFrame(columns=df.columns)

    # Convert DataFrame to RawTable for ingestion pipeline
    headers = [str(c).strip() for c in df.columns]
    rows = df.to_dict(orient="records")
    raw_table = RawTable(
        name=source_file,
        source_file=source_file,
        source_sheet=None,
        headers=headers,
        rows=rows,
        row_count=len(rows)
    )

    # 1. Map columns via ingestion.column_mapper (T2.2)
    mappings = map_columns(raw_table)
    col_mapping_dict = {m.source_column: m.field for m in mappings}

    # 2. Detect duplicate columns via ingestion.duplicate_columns (T2.7)
    dropped_cols, explanations = detect_duplicate_columns(rows, col_mapping_dict)

    # 3. Filter out dropped duplicate columns from mappings
    active_mappings = [m for m in mappings if m.source_column not in dropped_cols]

    # 4. Normalize rows via ingestion.normalizer (T2.3)
    canonical_txs: List[CanonicalTransaction] = []
    for idx, r in enumerate(rows, start=2):
        if _is_summary_dict_row(r):
            continue
        prov = {
            "source_file": source_file,
            "source_row_number": idx,
            "is_primary": is_primary
        }
        tx = normalize_row(r, active_mappings, provenance=prov)
        canonical_txs.append(tx)

    # 5. Deduplicate canonical rows via ingestion.dedupe (T2.4)
    dedupe_report = detect_duplicates(canonical_txs)
    unique_txs = dedupe_report.unique_rows

    record_dicts = [tx.to_dict() for tx in unique_txs]
    norm_df = pd.DataFrame(record_dicts) if record_dicts else pd.DataFrame()

    return norm_df, dropped_cols, explanations


def _clean_dataframe_for_json(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
        else:
            df[col] = df[col].apply(lambda v: v.isoformat() if hasattr(v, "isoformat") else (str(v) if pd.notna(v) and not isinstance(v, (int, float, str, bool, type(None))) else v))
    return df


def save_imported_statement(name, filename, df, is_primary=False, color=None, rules=None, use_llm=False):
    """
    Save a new imported statement using the unified ingestion pipeline.
    If use_llm is True, uses AI to extract samples, detect canonical field mappings,
    and persist new aliases to config/column_aliases.json before normalization.
    """
    _ensure_data_dir()
    db = _load_db()

    if df is not None and not df.empty:
        df = _clean_dataframe_for_json(df)

    if use_llm and df is not None and not df.empty:
        try:
            df_raw = _detect_and_promote_header_row(df)
            headers = [c for c in df_raw.columns if str(c).strip() and c not in ("is_primary", "source_file", "source_sheet", "source_name", "source_color", "source_type", "source_row_number")]
            col_samples = {}
            for h in headers:
                samples = [str(val) for val in df_raw[h].dropna().unique()[:3] if str(val).strip() and str(val).lower() not in ("nan", "none", "null")]
                col_samples[str(h).strip()] = samples

            mappings_learned = _llm_analyze_columns(col_samples)
            _update_column_aliases_config(mappings_learned)
        except Exception as exc:
            print(f"[save_imported_statement] LLM column analysis exception: {exc}")

    norm_df, dropped_cols, explanations = normalize_statement_columns(df, is_primary=is_primary, source_file=filename)

    existing_codes = {s.get("serial_code") for s in db.get("statements", []) if s.get("serial_code")}
    serial_code = generate_unique_serial_code(existing_codes)

    stmt_id = f"stmt_{int(time.time() * 1000)}"

    clean_filename_name = (
        filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
        if filename else None
    )
    stmt_name = name or clean_filename_name or f"Statement {len(db['statements']) + 1}"
    palette_color = STATEMENT_COLOR_PALETTE[len(db['statements']) % len(STATEMENT_COLOR_PALETTE)]
    stmt_color = color or palette_color

    records = norm_df.fillna("").to_dict(orient="records") if not norm_df.empty else []

    for idx, r in enumerate(records):
        r["serial_no"] = f"{serial_code}-{idx + 1}"
        r["serial_code"] = serial_code
        r["statement_id"] = stmt_id
        r["source_name"] = stmt_name
        r["source_color"] = stmt_color
        r["is_primary"] = bool(is_primary)

    raw_records = df.fillna("").to_dict(orient="records") if df is not None and not df.empty else []

    new_stmt = {
        "id": stmt_id,
        "name": stmt_name,
        "serial_code": serial_code,
        "is_primary": bool(is_primary),
        "color": stmt_color,
        "rules": rules or "",
        "filename": filename,
        "row_count": len(records),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": records,
        "raw_rows": raw_records,
        "dropped_columns": dropped_cols,
        "explanations": explanations
    }
    
    db["statements"].insert(0, new_stmt)
    _save_db(db)
    
    rebuild_generated_csv()

    return new_stmt



def set_primary_statement(statement_id, is_primary=None):
    """
    Toggle or set a specific statement as primary (is_primary=True/False).
    Supports MULTIPLE primary statements simultaneously.
    Rebuilds generated CSVs so primary_records.csv and counterpart_records.csv are updated.
    """
    db = _load_db()
    found = False
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            if is_primary is None:
                new_pri = not bool(s.get("is_primary", False))
            else:
                new_pri = bool(is_primary)
            s["is_primary"] = new_pri
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            for r in s.get("rows", []):
                r["is_primary"] = new_pri
            found = True
            break
    if found:
        _save_db(db)
        rebuild_generated_csv()
        return True
    return False


def rename_statement(statement_id, new_name):
    """Rename an existing statement."""
    db = _load_db()
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            name_val = new_name.strip()
            s["name"] = name_val
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            for r in s.get("rows", []):
                r["source_name"] = name_val
            _save_db(db)
            rebuild_generated_csv()
            return True
    return False


def update_statement_color(statement_id, new_color):
    """Update color for an existing statement."""
    db = _load_db()
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            s["color"] = new_color.strip()
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_db(db)
            return True
    return False



def delete_statement(statement_id):
    """Delete a statement from the store and rebuild generated CSVs."""
    db = _load_db()
    deleted_stmt = None
    new_stmts = []
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            deleted_stmt = s
        else:
            new_stmts.append(s)

    if deleted_stmt:
        db["statements"] = new_stmts
        _save_db(db)
        rebuild_generated_csv()
        return True
    return False

def clear_all_statements():
    """Wipe all statements, uploaded raw files, generated CSVs, ML predictions, and reconciliation results (T12.2)."""
    _save_db({"statements": []})

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_uploads_dir = os.path.join(base_dir, "data", "uploads")
    frontend_uploads_dir = os.path.join(base_dir, "frontend", "uploads")
    results_dir = os.path.join(base_dir, "data", "results")
    ml_dir = os.path.join(base_dir, "data", "ml")
    raw_dir = os.path.join(base_dir, "data", "raw")
    generated_dir = os.path.join(base_dir, "data", "generated")

    # Clear uploads (both data/uploads and frontend/uploads subfolders)
    upload_folders = [data_uploads_dir]
    if os.path.exists(frontend_uploads_dir):
        for sub in os.listdir(frontend_uploads_dir):
            subpath = os.path.join(frontend_uploads_dir, sub)
            if os.path.isdir(subpath):
                upload_folders.append(subpath)

    for folder in upload_folders + [results_dir, ml_dir, raw_dir]:
        if os.path.exists(folder):
            for fname in os.listdir(folder):
                if fname == ".gitkeep":
                    continue
                fpath = os.path.join(folder, fname)
                try:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.unlink(fpath)
                    elif os.path.isdir(fpath):
                        shutil.rmtree(fpath)
                except Exception:
                    pass

    # Reset all generated CSVs to empty DataFrames with headers
    os.makedirs(generated_dir, exist_ok=True)
    target_csv_map = {
        "primary": os.path.join(generated_dir, "bank_statement.csv"),
        "primary_records": os.path.join(generated_dir, "primary_records.csv"),
        "counterpart_records": os.path.join(generated_dir, "counterpart_records.csv"),
        "razorpay": os.path.join(generated_dir, "razorpay_settlements.csv"),
        "orders": os.path.join(generated_dir, "internal_orders.csv"),
    }
    for key, target_path in target_csv_map.items():
        headers = DEFAULT_HEADERS["primary"] if "primary" in key else DEFAULT_HEADERS["counterpart"]
        df = pd.DataFrame(columns=headers)
        df.to_csv(target_path, index=False)

    return True

def append_statement_data(statement_id, new_df):
    """
    Incremental update: checks last row of current statement,
    finds match in new_df if present, and appends all subsequent rows.
    """
    db = _load_db()
    stmt = None
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            stmt = s
            break
            
    if not stmt or not stmt["rows"]:
        return {"success": False, "message": "Original statement is empty or not found."}

    norm_df, _, _ = normalize_statement_columns(new_df, is_primary=stmt.get("is_primary", False))
    last_row = stmt["rows"][-1]
    new_records = norm_df.fillna("").to_dict(orient="records") if not norm_df.empty else []

    
    append_start_idx = 0
    match_found = False
    
    for idx, row in enumerate(new_records):
        is_match = True
        for key in list(last_row.keys())[:3]:
            if str(last_row.get(key, "")).strip() != str(row.get(key, "")).strip():
                is_match = False
                break
        if is_match:
            append_start_idx = idx + 1
            match_found = True
            break
            
    rows_to_add = new_records[append_start_idx:]
    if not rows_to_add:
        return {
            "success": True,
            "appended_count": 0,
            "message": "No new entries found to append (already up to date)."
        }
        
    stmt["rows"].extend(rows_to_add)
    stmt["row_count"] = len(stmt["rows"])
    stmt["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_db(db)
    
    rebuild_generated_csv()

    return {
        "success": True,
        "match_found": match_found,
        "appended_count": len(rows_to_add),
        "total_count": stmt["row_count"],
        "message": f"Successfully appended {len(rows_to_add)} new records."
    }


def update_statement_data(statement_id, new_rows):
    """
    Update row data for an existing statement.
    Sanitizes updated rows, persists changes, and rebuilds generated CSVs.
    """
    db = _load_db()
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            sanitized_rows = [_sanitize_statement_row(r) for r in new_rows]
            s["rows"] = sanitized_rows
            s["row_count"] = len(sanitized_rows)
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_db(db)
            rebuild_generated_csv()
            return True
    return False


def delete_statement_columns(statement_id, columns_to_delete):
    """
    Deletes specified columns/features from all rows in a statement.
    """
    db = _load_db()
    cols_set = set(columns_to_delete)
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            updated_rows = []
            for row in s.get("rows", []):
                cleaned_row = {k: v for k, v in row.items() if k not in cols_set}
                updated_rows.append(cleaned_row)
            s["rows"] = updated_rows
            _save_db(db)
            rebuild_generated_csv()
            return True
    return False


def _update_column_aliases_config(mappings_learned: Dict[str, str]):
    """
    Persists newly learned column aliases to config/column_aliases.json
    so future statement uploads automatically recognize them.
    """
    if not mappings_learned:
        return

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "column_aliases.json")
    aliases = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                aliases = json.load(f)
        except Exception:
            pass

    updated = False
    for raw_col, canonical_field in mappings_learned.items():
        if not canonical_field or canonical_field == "ignore":
            continue
        clean_alias = str(raw_col).strip().lower()
        if canonical_field in aliases:
            if clean_alias not in [a.lower() for a in aliases[canonical_field]]:
                aliases[canonical_field].append(raw_col.strip())
                updated = True
        else:
            aliases[canonical_field] = [raw_col.strip()]
            updated = True

    if updated:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(aliases, f, indent=2)
        except Exception:
            pass


def _llm_analyze_columns(col_samples: Dict[str, List[str]]) -> Dict[str, str]:
    """
    Uses LLM / Semantic Rule Engine with 2-3 sample entries per column
    to accurately map each input column to a canonical schema field.
    """
    learned_mappings = {}

    try:
        from llm import query_llm
        prompt = (
            "You are an expert financial ledger data analyst. Match each input table column name and sample values "
            "to ONE of the following canonical field names:\n"
            "['transaction_id', 'gross_amount', 'net_amount', 'credit_amount', 'debit_amount', 'fee_amount', 'tax_amount', "
            "'transaction_date', 'value_date', 'utr', 'order_id', 'settlement_id', 'description', 'customer_name', 'channel', 'status', 'auth_code', 'card_network', 'ignore']\n\n"
            f"Columns and Sample Values:\n{json.dumps(col_samples, indent=2, default=str)}\n\n"
            "Return ONLY a valid JSON object mapping each raw column name to its canonical field name. Format: {\"raw_col_name\": \"canonical_field\"}"
        )
        response_text = query_llm(prompt)
        if response_text:
            clean_json = re.sub(r"```json|```", "", response_text).strip()
            parsed = json.loads(clean_json)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass

    for raw_col, samples in col_samples.items():
        col_lower = str(raw_col).strip().lower()
        sample_str = " ".join(samples).lower()

        if any(k in col_lower for k in ("date", "time", "created_at", "post_date")):
            if "val" in col_lower or "settle" in col_lower or "expected" in col_lower:
                learned_mappings[raw_col] = "value_date"
            else:
                learned_mappings[raw_col] = "transaction_date"
        elif any(k in col_lower for k in ("utr", "ref", "rrn", "reference")):
            learned_mappings[raw_col] = "utr"
        elif "order" in col_lower or "inv" in col_lower or "invoice" in col_lower:
            learned_mappings[raw_col] = "order_id"
        elif "settle" in col_lower or "batch" in col_lower or "payout" in col_lower or "voucher" in col_lower:
            learned_mappings[raw_col] = "settlement_id"
        elif any(k in col_lower for k in ("txn_id", "tx_id", "transaction_id")) and not any(k in col_lower for k in ("count", "#", "num")):
            learned_mappings[raw_col] = "transaction_id"
        elif "net" in col_lower or "payout" in col_lower or "paid" in col_lower or "received" in col_lower:
            learned_mappings[raw_col] = "net_amount"
        elif "gross" in col_lower or "total" in col_lower:
            learned_mappings[raw_col] = "gross_amount"
        elif "credit" in col_lower or "deposit" in col_lower or "in" in col_lower:
            learned_mappings[raw_col] = "credit_amount"
        elif "debit" in col_lower or "withdraw" in col_lower or "out" in col_lower:
            learned_mappings[raw_col] = "debit_amount"
        elif "fee" in col_lower or "charge" in col_lower or "commission" in col_lower:
            learned_mappings[raw_col] = "fee_amount"
        elif "tax" in col_lower or "gst" in col_lower or "vat" in col_lower:
            learned_mappings[raw_col] = "tax_amount"
        elif any(k in col_lower for k in ("customer", "payer", "vendor", "employee", "name", "vpa", "remitter")):
            learned_mappings[raw_col] = "customer_name"
        elif any(k in col_lower for k in ("mode", "channel", "method", "source type", "type")):
            learned_mappings[raw_col] = "channel"
        elif any(k in col_lower for k in ("status", "state")):
            learned_mappings[raw_col] = "status"
        elif "card" in col_lower or "reason" in col_lower or "memo" in col_lower or "particular" in col_lower or "remark" in col_lower or "desc" in col_lower:
            learned_mappings[raw_col] = "description"

    return learned_mappings


def realign_statement_columns_llm(statement_id):
    """
    Uses LLM / Intelligent Semantic Mapping to align unmapped or misaligned columns for a statement.
    Learns new column aliases and updates config/column_aliases.json for future automatic imports.
    Re-normalizes and saves all rows in the statement.
    """
    db = _load_db()
    stmt = None
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            stmt = s
            break
    if not stmt:
        return False, "Statement not found.", {}

    raw_records = stmt.get("raw_rows")
    if raw_records:
        df_raw = pd.DataFrame(raw_records)
    else:
        rows = stmt.get("rows", [])
        if not rows:
            return False, "No data rows in statement.", {}
        df_raw = pd.DataFrame(rows)

    if df_raw.empty:
        return False, "No data rows in statement.", {}

    df_raw = _clean_dataframe_for_json(df_raw)
    df_raw = _detect_and_promote_header_row(df_raw)

    internal_keys = {"is_primary", "source_file", "source_sheet", "source_name", "source_color", "source_type", "source_row_number", "statement_id", "serial_no", "serial_code", "amount", "date", "bank_transaction_id", "content_hash"}
    headers = [c for c in df_raw.columns if str(c).strip() and c not in internal_keys]

    col_samples = {}
    for h in headers:
        samples = [str(val) for val in df_raw[h].dropna().unique()[:3] if str(val).strip() and str(val).lower() not in ("nan", "none", "null")]
        col_samples[str(h).strip()] = samples

    mappings_learned = _llm_analyze_columns(col_samples)
    _update_column_aliases_config(mappings_learned)

    source_filename = stmt.get("filename") or stmt.get("name", "statement")
    is_primary = bool(stmt.get("is_primary", False))
    norm_df, dropped, expl = normalize_statement_columns(df_raw, is_primary=is_primary, source_file=source_filename)
    
    res_rows = norm_df.fillna("").to_dict(orient="records") if not norm_df.empty else stmt.get("rows", [])

    serial_code = stmt.get("serial_code") or generate_unique_serial_code()
    stmt_id = stmt["id"]
    stmt_name = stmt.get("name", "Statement")
    stmt_color = stmt.get("color", "#4C8DFF")

    for idx, r in enumerate(res_rows):
        r["serial_no"] = f"{serial_code}-{idx + 1}"
        r["serial_code"] = serial_code
        r["statement_id"] = stmt_id
        r["source_name"] = stmt_name
        r["source_color"] = stmt_color
        r["is_primary"] = is_primary

    stmt["rows"] = res_rows
    stmt["row_count"] = len(res_rows)
    stmt["dropped_columns"] = dropped
    stmt["explanations"] = expl
    stmt["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_db(db)
    rebuild_generated_csv()

    return True, f"Successfully aligned {len(mappings_learned)} columns using AI.", mappings_learned


