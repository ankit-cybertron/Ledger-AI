"""
pages/overview.py — assembles the context dict for templates/overview.html.

NOTE: Kept as a standalone SSR overview page fallback for direct route navigation (/overview) alongside the SPA dashboard view.

Reads real reconciliation output from data/results/*.csv (see
data_access.py). Column names in reconciliation_results.csv weren't
specified when this was built, so `_find_status_column` tries a few
common candidates — if your engine uses a different header, add it to
STATUS_COLUMNS below and the rest of this file needs no changes.
"""


from data_access import file_exists


def get_context():
    """
    Assembles context for templates/overview.html using canonical reconciliation pipeline output (T9.1).
    Returns total transactions, counts, percentages, and pre-computed data structures for all 6 Overview charts.
    """
    try:
        from api.routes import _build_dashboard_run
        from datetime import datetime
        run = _build_dashboard_run(datetime.utcnow().strftime("%B %Y"))
        s = run.get("summary", {})
        total = s.get("total_transactions", 0)
        auto = s.get("auto_matched", 0)
        manual = s.get("manual_matched", 0) + s.get("llm_matched", 0)
        exceptions = run.get("exceptions", [])
        charts = run.get("charts", {})

        return {
            "data_available": total > 0,
            "results_file_found": file_exists("results/reconciliation_results.csv"),
            "exceptions_file_found": file_exists("results/exception_ledger.csv"),
            "total_transactions": total,
            "auto_matched": auto,
            "manual_matched": manual,
            "open_exceptions": len(exceptions),
            "percent_reconciled": s.get("percent_reconciled", 0.0),
            "percent_auto_matched": round((auto / total * 100), 1) if total > 0 else 0.0,
            "run": run,
            "charts": charts,
        }
    except Exception as exc:
        return {
            "data_available": False,
            "results_file_found": False,
            "exceptions_file_found": False,
            "total_transactions": 0,
            "auto_matched": 0,
            "manual_matched": 0,
            "open_exceptions": 0,
            "percent_reconciled": 0.0,
            "percent_auto_matched": 0.0,
            "run": {},
            "charts": {},
            "error": str(exc),
        }

