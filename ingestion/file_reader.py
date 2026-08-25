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
        # T1.5 Follow-up Stub: PDF text extraction -> table extraction -> OCR fallback
        # Deferred until scanned PDF bank statements need active support.
        raise NotImplementedError(
            "PDF statement parsing requires tabular text extraction (T1.5 deferred stub). "
            "Please upload a .csv or .xlsx file."
        )
    elif ext == ".csv":
        return _read_csv_table(path, filename, summary_keywords)
    elif ext in (".xlsx", ".xls"):
        return _read_excel_tables(path, filename, summary_keywords)
    else:
        raise ValueError(f"Unsupported file extension '{ext}'. Supported formats: .csv, .xlsx, .xls, .pdf")


def _read_csv_table(path: Path, filename: str, summary_keywords: List[str]) -> List[RawTable]:
    df = pd.read_csv(path)
    if df.empty:
        return [RawTable(name=filename, source_file=filename, source_sheet=None, headers=[], rows=[], row_count=0)]

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
