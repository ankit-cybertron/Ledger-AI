"""
statement_store.py — Persistent local store & DB manager for user-imported statements.

Handles metadata, raw statement rows, renaming, deletion, and incremental appending.
"""

import json
import os
import time
import pandas as pd

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DB_FILE = os.path.join(DATA_DIR, "statements_db.json")

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({"statements": []}, f, indent=2)

def parse_pdf_statement(file_path):
    """
    Extracts tabular or text line transactions from PDF statements using pdfplumber / pypdf.
    Handles bank statements, payment provider PDFs, and order reports.
    """
    rows = []
    headers = None

    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    if headers is None:
                        headers = [str(c or "").strip() for c in table[0]]
                        for row in table[1:]:
                            if any(row):
                                rows.append([str(c or "").strip() for c in row])
                    else:
                        for row in table:
                            if row and row != table[0] and any(row):
                                rows.append([str(c or "").strip() for c in row])
        if headers and rows:
            return pd.DataFrame(rows, columns=headers)
    except Exception:
        pass

    try:
        import pypdf
        import re
        reader = pypdf.PdfReader(file_path)
        text_lines = []
        for page in reader.pages:
            t = page.extract_text() or ""
            text_lines.extend(t.splitlines())

        extracted = []
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4}|\d{2}-\w{3}-\d{4})')
        amt_pattern = re.compile(r'₹?\s*([0-9,]+\.\d{2})')

        for line in text_lines:
            line = line.strip()
            if not line:
                continue
            d_match = date_pattern.search(line)
            a_matches = amt_pattern.findall(line)
            if d_match or a_matches:
                dt = d_match.group(1) if d_match else ""
                amt = a_matches[-1] if a_matches else ""
                desc = date_pattern.sub("", line)
                desc = amt_pattern.sub("", desc).strip()
                extracted.append({"date": dt, "description": desc, "amount": amt})
        if extracted:
            return pd.DataFrame(extracted)
    except Exception:
        pass

    return pd.DataFrame()

def _load_db():
    _ensure_data_dir()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"statements": []}

def _save_db(data):
    _ensure_data_dir()
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def list_statements():
    """List all imported statements metadata without full row payload."""
    db = _load_db()
    results = []
    for s in db.get("statements", []):
        stype = s.get("source_type", "bank")
        def_color = "#f04f4f" if stype == "razorpay" else ("#e0b054" if stype == "orders" else "#6f89ff")
        results.append({
            "id": s["id"],
            "name": s["name"],
            "source_type": stype,
            "statement_type_label": s.get("statement_type_label", stype.title()),
            "color": s.get("color", def_color),
            "filename": s["filename"],
            "row_count": s["row_count"],
            "created_at": s["created_at"],
            "updated_at": s.get("updated_at", s["created_at"]),
        })
    return results

def get_statement(statement_id):
    """Retrieve full statement details including row data."""
    db = _load_db()
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            return s
    return None

DEFAULT_HEADERS = {
    "bank": ["bank_transaction_id", "date", "utr", "amount", "description"],
    "razorpay": ["settlement_id", "order_id", "payment_id", "utr", "amount", "status", "created_at"],
    "orders": ["order_id", "payment_id", "amount", "status", "created_at"],
}

def ensure_all_generated_csvs():
    """Ensure all required generated CSV files exist with headers for matcher engine compatibility."""
    gen_dir = os.path.join(DATA_DIR, "generated")
    os.makedirs(gen_dir, exist_ok=True)
    target_csv_map = {
        "bank": os.path.join(gen_dir, "bank_statement.csv"),
        "razorpay": os.path.join(gen_dir, "razorpay_settlements.csv"),
        "orders": os.path.join(gen_dir, "internal_orders.csv"),
    }
    for stype, path in target_csv_map.items():
        if not os.path.exists(path):
            df = pd.DataFrame(columns=DEFAULT_HEADERS[stype])
            df.to_csv(path, index=False)


def rebuild_generated_csv(source_type):
    """
    Combines all active statements of a given source_type and updates
    data/generated/<target_csv> for the reconciliation engine.
    """
    target_csv_map = {
        "bank": os.path.join(DATA_DIR, "generated", "bank_statement.csv"),
        "razorpay": os.path.join(DATA_DIR, "generated", "razorpay_settlements.csv"),
        "orders": os.path.join(DATA_DIR, "generated", "internal_orders.csv"),
    }
    if source_type not in target_csv_map:
        return

    target_path = target_csv_map[source_type]
    db = _load_db()

    all_rows = []
    for s in db.get("statements", []):
        if s.get("source_type") == source_type and s.get("rows"):
            all_rows.extend(s["rows"])

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    if all_rows:
        combined_df = pd.DataFrame(all_rows)
        combined_df.to_csv(target_path, index=False)
    else:
        headers = DEFAULT_HEADERS.get(source_type, [])
        empty_df = pd.DataFrame(columns=headers)
        empty_df.to_csv(target_path, index=False)


def normalize_statement_columns(df, source_type):
    """
    Normalizes column names and values of an uploaded statement DataFrame to match standard schema.
    """
    df = df.copy()

    # Drop summary / total rows from Excel files
    if not df.empty:
        summary_mask = pd.Series(False, index=df.index)
        for col in df.columns:
            s_col = df[col].astype(str).str.strip().str.lower()
            summary_mask |= s_col.isin(["total", "grand total", "subtotal", "total amount", "summary"])
            summary_mask |= s_col.str.startswith("total ")
        df = df[~summary_mask].copy()

    lower_cols = {str(c).strip().lower(): c for c in df.columns}

    # Handle Credit (INR) / Debit (INR) for bank statement if amount column is missing
    if "amount" not in lower_cols and not any("amount" in k for k in lower_cols.keys()):
        credit_col = next((c for k, c in lower_cols.items() if "credit" in k), None)
        debit_col = next((c for k, c in lower_cols.items() if "debit" in k), None)
        if credit_col or debit_col:
            cr = pd.to_numeric(df[credit_col].astype(str).str.replace(",", "").str.replace("₹", ""), errors="coerce").fillna(0.0) if credit_col else 0.0
            db = pd.to_numeric(df[debit_col].astype(str).str.replace(",", "").str.replace("₹", ""), errors="coerce").fillna(0.0) if debit_col else 0.0
            df["amount"] = cr - db

    col_map = {}
    for col in df.columns:
        if col == "amount":
            continue
        clean_col = str(col).strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")

        if any(a in clean_col for a in ["amount", "inr"]) and "amount" not in col_map.values() and "amount" not in df.columns:
            col_map[col] = "amount"
        elif any(d in clean_col for d in ["date", "time"]) and "date" not in col_map.values() and "date" not in df.columns:
            col_map[col] = "date"
        elif any(u in clean_col for u in ["utr", "rrn", "ref", "gateway_ref"]) and "utr" not in col_map.values() and "utr" not in df.columns:
            col_map[col] = "utr"
        elif any(x in clean_col for x in ["description", "particulars", "narration", "vpa", "customer"]) and "description" not in col_map.values() and "description" not in df.columns:
            col_map[col] = "description"
        elif any(o in clean_col for o in ["order_id", "ord_id", "order_no"]) and "order_id" not in col_map.values():
            col_map[col] = "order_id"
        elif any(s in clean_col for s in ["settlement_id", "setl_id", "upi_txn_id", "voucher", "voucher_no"]) and "settlement_id" not in col_map.values():
            col_map[col] = "settlement_id"

    if col_map:
        df = df.rename(columns=col_map)

    # Clean amount numeric values
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(
            df["amount"].astype(str).str.replace(",", "").str.replace("₹", "").str.strip(),
            errors="coerce"
        ).fillna(0.0)

    # Guarantee primary ID column exists
    if source_type == "bank":
        if "bank_transaction_id" not in df.columns:
            if "utr" in df.columns and not df["utr"].dropna().empty:
                df["bank_transaction_id"] = df["utr"].astype(str)
            else:
                df["bank_transaction_id"] = [f"bank_{i+1:04d}" for i in range(len(df))]
    elif source_type == "razorpay":
        if "settlement_id" not in df.columns:
            if "utr" in df.columns and not df["utr"].dropna().empty:
                df["settlement_id"] = df["utr"].astype(str)
            else:
                df["settlement_id"] = [f"setl_{i+1:04d}" for i in range(len(df))]
    elif source_type == "orders":
        if "order_id" not in df.columns:
            df["order_id"] = [f"order_{i+1:04d}" for i in range(len(df))]

    return df


def detect_source_type(name, filename, df=None, fallback="bank"):
    n = (name or "").lower()
    f = (filename or "").lower()
    cols = [str(c).lower() for c in (df.columns if df is not None else [])]

    if "order" in n or "order" in f or "order_id" in cols or "payment_mode" in cols:
        return "orders"
    if any(k in n or k in f for k in ["upi", "card", "cash", "razorpay", "settlement"]) or any(c in cols for c in ["auth_code", "card_network", "settlement_id"]):
        return "razorpay"
    if "bank" in n or "bank" in f or "narration" in cols or "particulars" in cols:
        return "bank"
    return fallback


def save_imported_statement(name, source_type, filename, df, color=None, statement_type_label=None, rules=None):
    """
    Save a new imported statement with custom color, type label, and processing rules.
    Converts DataFrame to records JSON format and updates generated CSVs.
    """
    _ensure_data_dir()
    db = _load_db()

    # Intelligently detect true source_type if generic or wrong
    detected_source = detect_source_type(name, filename, df, fallback=source_type)

    df = normalize_statement_columns(df, detected_source)

    stmt_id = f"stmt_{int(time.time() * 1000)}"
    records = df.fillna("").to_dict(orient="records")
    
    default_color = "#6f89ff"
    if detected_source == "razorpay":
        default_color = "#f04f4f"
    elif detected_source == "orders":
        default_color = "#e0b054"

    new_stmt = {
        "id": stmt_id,
        "name": name or f"Statement {len(db['statements']) + 1}",
        "source_type": detected_source,
        "statement_type_label": statement_type_label or (source_type.title() if source_type else "Bank"),
        "color": color or default_color,
        "rules": rules or "",
        "filename": filename,
        "row_count": len(records),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": records
    }
    
    db["statements"].insert(0, new_stmt)
    _save_db(db)
    
    # Sync combined generated CSV for backend matcher engine
    rebuild_generated_csv(detected_source)

    return new_stmt


def rename_statement(statement_id, new_name):
    """Rename an existing statement."""
    db = _load_db()
    for s in db.get("statements", []):
        if s["id"] == statement_id:
            s["name"] = new_name.strip()
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
        rebuild_generated_csv(deleted_stmt.get("source_type"))
        return True
    return False

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

    new_df = normalize_statement_columns(new_df, stmt.get("source_type", "bank"))
    last_row = stmt["rows"][-1]
    new_records = new_df.fillna("").to_dict(orient="records")
    
    # Find matching index of last row in new data
    append_start_idx = 0
    match_found = False
    
    for idx, row in enumerate(new_records):
        # Compare key fields or exact dict match
        is_match = True
        for key in list(last_row.keys())[:3]: # Compare first 3 columns
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
    
    # Rebuild combined generated CSV for matcher engine
    rebuild_generated_csv(stmt["source_type"])

    return {
        "success": True,
        "match_found": match_found,
        "appended_count": len(rows_to_add),
        "total_count": stmt["row_count"],
        "message": f"Successfully appended {len(rows_to_add)} new records."
    }
