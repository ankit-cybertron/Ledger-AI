"""
file_reader.py — Ingestion Engine Stage 1 (File & Table Detection) for Ledger AI v2.

Reads .csv, .xls, .xlsx files (all sheets), filtering summary/total rows using a case-insensitive,
configurable keyword list. Tags every extracted row with provenance attributes (source_file,
source_sheet, source_row_number). Raises a clean NotImplementedError for .pdf files.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "ingestion_rules.json"


@dataclass
class RawTable:
    """
    Standardized container for an un-mapped, raw extracted table from an input file.
    """
    name: str
    source_file: str
    source_sheet: Optional[str]
    headers: List[str]
    rows: List[Dict[str, Any]]
    row_count: int = 0

    def __post_init__(self):
        if not self.row_count:
            self.row_count = len(self.rows)


def _load_summary_keywords() -> List[str]:
    """
    Loads configurable summary row filter keywords.
    """
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [k.strip().lower() for k in data.get("summary_row_keywords", []) if k]
        except Exception:
            pass
    return ["total", "grand total", "subtotal", "total amount", "summary"]


def _is_summary_row(row_series: pd.Series, keywords: List[str]) -> bool:
    """
    Performs a case-insensitive check across all cell values in a row
    to identify and strip summary/footer rows.
    """
    for val in row_series.dropna():
        s_val = str(val).strip().lower()
        if any(kw == s_val or s_val.startswith(f"{kw} ") for kw in keywords):
            return True
    return False


def read_source_file(file_path: str) -> List[RawTable]:
    """
    Reads a source file (.csv, .xlsx, .xls) and returns a list of RawTable instances
    (one per CSV file or one per Excel sheet).

    Raises:
        NotImplementedError: For .pdf files.
        ValueError: For unsupported file formats or missing files.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    filename = path.name
    ext = path.suffix.lower()
    summary_keywords = _load_summary_keywords()

    if ext == ".pdf":
        return _read_pdf_tables(path, filename, summary_keywords)
    elif ext == ".csv":
        return _read_csv_table(path, filename, summary_keywords)
    elif ext in (".xlsx", ".xls"):
        return _read_excel_tables(path, filename, summary_keywords)
    else:
        raise ValueError(f"Unsupported file extension '{ext}'. Supported formats: .csv, .xlsx, .xls, .pdf")


def _is_summary_row_dict(row_dict: Dict[str, Any], keywords: List[str]) -> bool:
    for val in row_dict.values():
        if val is None:
            continue
        s_val = str(val).strip().lower()
        if any(kw == s_val or s_val.startswith(f"{kw} ") for kw in keywords):
            return True
    return False


def _read_pdf_tables(path: Path, filename: str, summary_keywords: List[str]) -> List[RawTable]:
    """
    Extracts tabular or text line transactions from PDF statements using pdfplumber / pypdf.
    Tags every extracted row with provenance attributes (source_file, source_sheet=None, source_page, source_row_number).
    Concatenates all pages into RawTable instances.
    """
    filtered_rows: List[Dict[str, Any]] = []
    headers: List[str] = []

    # 1. Try pdfplumber table extraction
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            row_counter = 2
            for page_idx, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    # Extract headers if not set
                    if not headers and table[0]:
                        headers = [str(c or "").strip() for c in table[0] if str(c or "").strip()]

                    start_idx = 1 if table[0] and [str(c or "").strip() for c in table[0]] == headers else 0
                    for row in table[start_idx:]:
                        if not row or not any(row):
                            continue

                        row_dict = {}
                        for c_idx, cell in enumerate(row):
                            cell_val = str(cell or "").strip()
                            key = headers[c_idx] if c_idx < len(headers) else f"col_{c_idx}"
                            row_dict[key] = cell_val

                        if _is_summary_row_dict(row_dict, summary_keywords):
                            continue

                        row_dict["source_file"] = filename
                        row_dict["source_sheet"] = None
                        row_dict["source_page"] = page_idx
                        row_dict["source_row_number"] = row_counter
                        row_counter += 1
                        filtered_rows.append(row_dict)
    except Exception:
        pass

    # 2. Fallback to text line regex parsing if table extraction yielded no rows
    if not filtered_rows:
        try:
            import pypdf
            import re
            reader = pypdf.PdfReader(path)
            row_counter = 2
            date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4}|\d{2}-\w{3}-\d{4})')
            amt_pattern = re.compile(r'₹?\s*([0-9,]+\.\d{2})')

            headers = ["date", "description", "amount"]

            for page_idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                lines = text.splitlines()
                for line in lines:
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
                        row_dict = {
                            "date": dt,
                            "description": desc,
                            "amount": amt,
                            "source_file": filename,
                            "source_sheet": None,
                            "source_page": page_idx,
                            "source_row_number": row_counter,
                        }
                        row_counter += 1
                        filtered_rows.append(row_dict)
        except Exception:
            pass

    return [
        RawTable(
            name=filename,
            source_file=filename,
            source_sheet=None,
            headers=headers or ["date", "description", "amount"],
            rows=filtered_rows,
            row_count=len(filtered_rows)
        )
    ]



COMMON_HEADER_KEYWORDS = [
    "date", "transaction", "order", "ref", "reference", "utr", "amount",
    "debit", "credit", "withdrawal", "deposit", "description", "narration",
    "status", "customer", "name", "id", "particulars", "vpa", "card", "type", "method"
]


def _detect_and_promote_header_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detects if initial rows of a DataFrame contain banner/title metadata
    and promotes the true column header row.
    """
    if df is None or df.empty:
        return df

    def score_headers(col_names):
        score = 0
        for c in col_names:
            c_str = str(c).strip().lower()
            if not c_str or c_str.startswith("unnamed:") or c_str == "nan":
                continue
            if any(kw in c_str for kw in COMMON_HEADER_KEYWORDS):
                score += 3
            else:
                score += 1
        return score

    default_score = score_headers(df.columns)
    best_row_idx = -1
    best_score = default_score

    for r_idx in range(min(10, len(df))):
        row_vals = df.iloc[r_idx].values
        row_score = score_headers(row_vals)
        if row_score > best_score and row_score >= 3:
            best_score = row_score
            best_row_idx = r_idx

    if best_row_idx != -1:
        new_headers = [str(c).strip() for c in df.iloc[best_row_idx].values]
        df = df.iloc[best_row_idx + 1:].reset_index(drop=True)
        df.columns = new_headers

    return df


def _read_csv_table(path: Path, filename: str, summary_keywords: List[str]) -> List[RawTable]:
    df = pd.read_csv(path)
    if df.empty:
        return [RawTable(name=filename, source_file=filename, source_sheet=None, headers=[], rows=[], row_count=0)]

    df = _detect_and_promote_header_row(df)
    headers = [str(c).strip() for c in df.columns]

    filtered_rows: List[Dict[str, Any]] = []
    # 1-indexed: row 1 is header, data starts at Excel/CSV line 2
    for idx, (_, row) in enumerate(df.iterrows(), start=2):
        if _is_summary_row(row, summary_keywords):
            continue

        row_dict = row.to_dict()
        row_dict["source_file"] = filename
        row_dict["source_sheet"] = None
        row_dict["source_row_number"] = idx
        filtered_rows.append(row_dict)

    return [
        RawTable(
            name=filename,
            source_file=filename,
            source_sheet=None,
            headers=headers,
            rows=filtered_rows,
            row_count=len(filtered_rows)
        )
    ]


def _read_excel_tables(path: Path, filename: str, summary_keywords: List[str]) -> List[RawTable]:
    # sheet_name=None reads ALL sheets into a dict of {sheet_name: DataFrame}
    excel_sheets = pd.read_excel(path, sheet_name=None)
    tables: List[RawTable] = []

    for sheet_name, df in excel_sheets.items():
        if df.empty:
            tables.append(
                RawTable(
                    name=f"{filename} [{sheet_name}]",
                    source_file=filename,
                    source_sheet=str(sheet_name),
                    headers=[],
                    rows=[],
                    row_count=0
                )
            )
            continue

        df = _detect_and_promote_header_row(df)
        headers = [str(c).strip() for c in df.columns]

        filtered_rows: List[Dict[str, Any]] = []
        for idx, (_, row) in enumerate(df.iterrows(), start=2):
            if _is_summary_row(row, summary_keywords):
                continue

            row_dict = row.to_dict()
            row_dict["source_file"] = filename
            row_dict["source_sheet"] = str(sheet_name)
            row_dict["source_row_number"] = idx
            filtered_rows.append(row_dict)

        tables.append(
            RawTable(
                name=f"{filename} [{sheet_name}]",
                source_file=filename,
                source_sheet=str(sheet_name),
                headers=headers,
                rows=filtered_rows,
                row_count=len(filtered_rows)
            )
        )

    return tables
