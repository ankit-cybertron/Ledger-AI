"""
pages/overview.py — assembles the context dict for templates/overview.html.

Reads real reconciliation output from data/results/*.csv (see
data_access.py). Column names in reconciliation_results.csv weren't
specified when this was built, so `_find_status_column` tries a few
common candidates — if your engine uses a different header, add it to
STATUS_COLUMNS below and the rest of this file needs no changes.

Nothing here is fabricated: if a file is missing or a status column
can't be found, the corresponding stat is returned as None and the
template shows "—" instead of guessing.
"""

from data_access import read_csv_rows, file_exists

# TODO: confirm the actual column name your engine writes and move it
# to the front of this list.
STATUS_COLUMNS = ["status", "match_status", "match_stage", "stage", "decision"]

AUTO_VALUES = {"exact", "tolerance", "ml", "auto", "matched", "auto_matched"}
MANUAL_VALUES = {"manual", "manual_review", "llm", "llm_reviewed", "llm_matched"}
EXCEPTION_VALUES = {"exception", "unmatched", "unresolved", "no_match", "open"}


def _find_status_column(rows):
    if not rows:
        return None
    keys = set(rows[0].keys())
    for col in STATUS_COLUMNS:
        if col in keys:
            return col
    return None


def get_context():
    results = read_csv_rows("results/reconciliation_results.csv")
    exceptions = read_csv_rows("results/exception_ledger.csv")

    total = len(results)
    status_col = _find_status_column(results)

    auto = manual = 0
    latest_match_row = None

    if status_col:
        for row in results:
            value = (row.get(status_col) or "").strip().lower()
            if value in AUTO_VALUES:
                auto += 1
                latest_match_row = row
            elif value in MANUAL_VALUES:
                manual += 1
                latest_match_row = row

    exception_count = len(exceptions)

    percent_reconciled = round(((total - exception_count) / total) * 100, 1) if total else None
    percent_auto_matched = round((auto / total) * 100, 1) if total and status_col else None

    return {
        "data_available": total > 0,
        "results_file_found": file_exists("results/reconciliation_results.csv"),
        "exceptions_file_found": file_exists("results/exception_ledger.csv"),
        "total_transactions": total,
        "auto_matched": auto if status_col else None,
        "manual_matched": manual if status_col else None,
        "open_exceptions": exception_count,
        "percent_reconciled": percent_reconciled,
        "percent_auto_matched": percent_auto_matched,
        # Shown in the "Reconciliation Engine" live card — whatever
        # columns the row actually has, rendered generically since the
        # real schema wasn't provided.
        "latest_match_row": latest_match_row,
    }
