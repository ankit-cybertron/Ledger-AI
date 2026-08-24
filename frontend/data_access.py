"""
data_access.py — reads from the `data/` folder your reconciliation
pipeline (generate_data.py + the matching engine) produces.

Expected layout (as given):

    data/
    ├── generated/           bank_statement.csv, internal_orders.csv, razorpay_settlements.csv
    ├── ground_truth/        relationships.csv
    ├── ml/                  confidence_predictions.csv, matching_training_data.csv
    ├── raw/                 razorpay_*.json, test_order*.json
    └── results/             exact_matches.csv, tolerance_matches.csv, llm_matches.csv,
                              exception_ledger.csv, reconciliation_results.csv,
                              reconciliation_report.md, llm_evaluation.csv

Set LEDGER_DATA_DIR if your `data/` folder doesn't live at the project
root (sibling to app.py). Every read function fails soft — a missing
file returns an empty list / None rather than raising, so pages render
sensibly before data exists yet.
"""

import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("LEDGER_DATA_DIR", os.path.abspath(os.path.join(BASE_DIR, "..", "data")))


def _path(relative_path):
    return os.path.join(DATA_DIR, *relative_path.split("/"))


def read_csv_rows(relative_path):
    """Return a list of dict rows for a CSV under data/, or [] if missing/unreadable."""
    path = _path(relative_path)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def read_text(relative_path):
    """Return the raw text of a file under data/, or None if missing/unreadable."""
    path = _path(relative_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def file_exists(relative_path):
    return os.path.isfile(_path(relative_path))
