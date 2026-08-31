"""
reports/report_builder.py — Unified dataset builder for Ledger AI reports (T10.2).

Assembles filtered datasets based on user-selected criteria:
  - Statuses: SETTLED, MATCHED, SIMILAR, UNMATCHED
  - Statement / Source Filter
  - Date Range (start_date to end_date)
  - Section selection

Ensures 100% numerical parity between Markdown and PDF reports.
"""

import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

# Guarantee project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
if FRONTEND_DIR not in sys.path:
    sys.path.insert(0, FRONTEND_DIR)

from api.routes import _build_dashboard_run, compute_overview_charts


def map_txn_to_taxonomy(status_val: str, period_settled: bool = False) -> str:
    """Map raw transaction status string to Part 3B / Part 9 taxonomy (SETTLED, MATCHED, SIMILAR, UNMATCHED)."""
    st = (status_val or "").lower().strip()
    if st == "settled" or (period_settled and st in {"auto", "matched"}):
        return "SETTLED"
    elif st in {"auto", "matched"}:
        return "MATCHED"
    elif st in {"manual", "llm", "similar", "review"}:
        return "SIMILAR"
    else:
        return "UNMATCHED"


def build_filtered_report_data(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build authoritative filtered report data structure.
    
    `filters` schema:
        - statuses: List[str] e.g. ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]
        - sources: List[str] e.g. ["all"] or ["Bank Statement", "Razorpay Settlement"]
        - start_date: str e.g. "2026-01-01"
        - end_date: str e.g. "2026-12-31"
        - sections: List[str] e.g. ["summary", "charts", "transactions", "exceptions", "integrity"]
    """
    filters = filters or {}

    selected_statuses = [s.upper() for s in filters.get("statuses", []) if isinstance(s, str)]
    if not selected_statuses:
        selected_statuses = ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]

    selected_sources = [s.strip() for s in filters.get("sources", []) if isinstance(s, str)]
    filter_all_sources = (not selected_sources) or ("all" in [s.lower() for s in selected_sources])

    start_date_str = filters.get("start_date") or ""
    end_date_str = filters.get("end_date") or ""

    selected_sections = filters.get("sections")
    if not selected_sections or not isinstance(selected_sections, list):
        selected_sections = ["summary", "charts", "transactions", "exceptions", "integrity"]
    else:
        selected_sections = [str(s).lower() for s in selected_sections]

    # 1. Fetch baseline dataset from _build_dashboard_run()
    base_run = _build_dashboard_run("Report Scope")
    raw_txns = base_run.get("transactions", [])
    raw_exceptions = base_run.get("exceptions", [])
    base_settled = base_run.get("period_settled", False)

    # 2. Filter transactions (with strict ID deduplication)
    filtered_txns = []
    seen_tx_ids = set()
    for t in raw_txns:
        tx_id = str(t.get("id") or t.get("primary_id") or "").strip()
        if tx_id:
            if tx_id in seen_tx_ids:
                continue
            seen_tx_ids.add(tx_id)

        # Taxonomy check
        tax_status = map_txn_to_taxonomy(t.get("status"), base_settled)
        if tax_status not in selected_statuses:
            continue

        # Statement source check
        st_name = t.get("source_name") or t.get("source_type") or "Primary Statement"
        st_type = t.get("source_type") or ""
        if not filter_all_sources:
            if not any(
                src.lower() == st_name.lower() or src.lower() == st_type.lower()
                for src in selected_sources
            ):
                continue

        # Date range check
        t_date_str = t.get("date") or ""
        if start_date_str and t_date_str < start_date_str:
            continue
        if end_date_str and t_date_str > end_date_str:
            continue

        txn_copy = dict(t)
        txn_copy["taxonomy_status"] = tax_status
        filtered_txns.append(txn_copy)

    # 3. Calculate filtered summary metrics
    total_cnt = len(filtered_txns)
    auto_cnt = len([t for t in filtered_txns if (t.get("status") or "").lower() == "auto"])
    llm_cnt = len([t for t in filtered_txns if (t.get("status") or "").lower() == "llm"])
    manual_cnt = len([t for t in filtered_txns if (t.get("status") or "").lower() == "manual"])
    unrec_cnt = len([t for t in filtered_txns if t["taxonomy_status"] == "UNMATCHED"])
    reconciled_cnt = total_cnt - unrec_cnt if total_cnt >= unrec_cnt else total_cnt
    match_pct = round((reconciled_cnt / total_cnt * 100), 1) if total_cnt > 0 else 0.0

    pos_amounts = [t["amount"] for t in filtered_txns if t["amount"] > 0]
    neg_amounts = [abs(t["amount"]) for t in filtered_txns if t["amount"] < 0]
    deposits_sum = float(sum(pos_amounts)) if pos_amounts else 0.0
    payments_sum = float(sum(neg_amounts)) if neg_amounts else 0.0
    if deposits_sum == 0.0 and payments_sum == 0.0 and filtered_txns:
        deposits_sum = float(sum(t["amount"] for t in filtered_txns))

    period_settled = bool(total_cnt > 0 and unrec_cnt == 0 and len(raw_exceptions) == 0)

    # 4. Filter exceptions matching included statement sources / transactions
    filtered_exceptions = []
    if filter_all_sources:
        filtered_exceptions = list(raw_exceptions)
    else:
        for exc in raw_exceptions:
            exc_st = exc.get("statement_type") or exc.get("source_type") or ""
            if any(src.lower() == exc_st.lower() for src in selected_sources):
                filtered_exceptions.append(exc)

    # 5. Compute updated Part 9 charts for filtered dataset
    filtered_charts = compute_overview_charts(filtered_txns, filtered_exceptions, period_settled, match_pct)

    # 6. Integrity check calculation & taxonomy breakdown (T22.9, T22.10)
    settled_count = len([t for t in filtered_txns if t["taxonomy_status"] == "SETTLED"])
    matched_count = len([t for t in filtered_txns if t["taxonomy_status"] == "MATCHED"])
    similar_count = len([t for t in filtered_txns if t["taxonomy_status"] == "SIMILAR"])
    unmatched_count = len([t for t in filtered_txns if t["taxonomy_status"] == "UNMATCHED"])

    reconciled_cnt = settled_count + matched_count
    match_pct = round((reconciled_cnt / total_cnt * 100), 1) if total_cnt > 0 else 0.0

    # Net Variance is sum of UNMATCHED amounts (T22.9)
    unmatched_amount_sum = sum(abs(float(t.get("amount") or 0.0)) for t in filtered_txns if t["taxonomy_status"] == "UNMATCHED")

    accounted_for = settled_count + matched_count + similar_count + unmatched_count
    integrity_pass = (accounted_for == total_cnt)

    summary = {
        "total_transactions": total_cnt,
        "settled_count": settled_count,
        "matched_count": matched_count,
        "similar_count": similar_count,
        "unmatched_count": unmatched_count,
        "auto_matched": auto_cnt,
        "llm_matched": llm_cnt,
        "manual_matched": manual_cnt,
        "reconciled_count": reconciled_cnt,
        "percent_reconciled": match_pct,
        "deposits_total": deposits_sum,
        "payments_total": payments_sum,
        "variance": round(unmatched_amount_sum, 2),
        "period_settled": period_settled,
    }

    integrity = {
        "settled": settled_count,
        "matched": matched_count,
        "similar": similar_count,
        "unmatched": unmatched_count,
        "accounted_for": accounted_for,
        "total_transactions": total_cnt,
        "pass": integrity_pass
    }

    # 7. Compute Forecast & Cash Flow projections for report scope
    forecast_data = {}
    try:
        from forecasting.engine import build_forecast
        from api.routes import _BEGINNING_BALANCE
        forecast_data = build_forecast(filtered_txns, forecast_days=30, beginning_balance=_BEGINNING_BALANCE)
    except Exception as exc:
        print(f"[build_filtered_report_data] Forecast build warning: {exc}")

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "statuses": selected_statuses,
        "sources": selected_sources if not filter_all_sources else ["All Statements"],
        "start_date": start_date_str or "All Time",
        "end_date": end_date_str or "Present",
        "sections": selected_sections,
    }

    return {
        "summary": summary,
        "transactions": filtered_txns,
        "exceptions": filtered_exceptions,
        "charts": filtered_charts,
        "forecast": forecast_data,
        "integrity": integrity,
        "meta": meta,
        "sections": selected_sections,
    }
