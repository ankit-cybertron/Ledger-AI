"""
reports/generate_report.py — Markdown report generator for Ledger AI.

Pulls from reports.report_builder.build_filtered_report_data() to guarantee
100% numerical parity with the PDF report (T10.2 / T10.3).
"""

from pathlib import Path
from typing import Dict, Any, Optional

from reports.report_builder import build_filtered_report_data

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"
OUTPUT_PATH = RESULTS_DIR / "reconciliation_report.md"


def build_markdown_report(data: Optional[Dict[str, Any]] = None, filters: Optional[Dict[str, Any]] = None) -> str:
    """Generate Markdown report string using unified report data structure."""
    if data is None:
        data = build_filtered_report_data(filters)

    summary = data.get("summary", {})
    transactions = data.get("transactions", [])
    exceptions = data.get("exceptions", [])
    integrity = data.get("integrity", {})
    meta = data.get("meta", {})
    sections = data.get("sections", ["summary", "charts", "transactions", "exceptions", "integrity"])

    total = summary.get("total_transactions", 0)
    matched = summary.get("settled_count", 0) + summary.get("matched_count", 0)
    review = summary.get("similar_count", 0)
    unmatched = summary.get("unmatched_count", 0)
    match_rate = (summary.get("percent_reconciled", 0.0) / 100.0)

    lines = []
    lines.append("# Ledger Reconciliation Report")
    lines.append("")
    lines.append("> Automated reconciliation, matching-stage analysis, and exception audit.")
    lines.append("")
    lines.append(f"**Generated:** {meta.get('generated_at', 'N/A')}  ")
    lines.append(f"**Filter Scope:** Statuses: {', '.join(meta.get('statuses', []))} | Sources: {', '.join(meta.get('sources', []))}")
    lines.append("")

    # 1. Executive Summary
    if "summary" in sections:
        lines.append("## Executive Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Transactions Processed | {total} |")
        lines.append(f"| Settled / Auto-Matched | {matched} |")
        lines.append(f"| Manual / Similar Review | {review} |")
        lines.append(f"| Unmatched Transactions | {unmatched} |")
        lines.append(f"| Match Rate | {match_rate:.2%} |")
        lines.append(f"| Deposits Total | ₹{summary.get('deposits_total', 0.0):,.2f} |")
        lines.append(f"| Payments Total | ₹{summary.get('payments_total', 0.0):,.2f} |")
        lines.append(f"| Net Variance | ₹{summary.get('variance', 0.0):,.2f} |")
        lines.append("")

        lines.append("## Settlement Outcomes Taxonomy")
        lines.append("")
        lines.append("| Taxonomy Status | Count |")
        lines.append("|---|---:|")
        lines.append(f"| SETTLED | {summary.get('settled_count', 0)} |")
        lines.append(f"| MATCHED | {summary.get('matched_count', 0)} |")
        lines.append(f"| SIMILAR | {summary.get('similar_count', 0)} |")
        lines.append(f"| UNMATCHED | {summary.get('unmatched_count', 0)} |")
        lines.append("")

    # 2. Charts Section (Markdown text summary fallback)
    if "charts" in sections:
        charts_data = data.get("charts", {})
        sb = charts_data.get("status_breakdown", {})
        lines.append("## Visual Analytics Data Summary")
        lines.append("")
        lines.append("| Category | Count | Percentage |")
        lines.append("|---|---:|---:|")
        labels = sb.get("labels", [])
        counts = sb.get("counts", [])
        pcts = sb.get("percentages", [])
        for l, c, p in zip(labels, counts, pcts):
            lines.append(f"| {l} | {c} | {p:.1f}% |")
        lines.append("")

    # 3. Exception Summary
    if "exceptions" in sections:
        open_exc = len([e for e in exceptions if (e.get("resolution_status") or "").lower() == "open"])
        high_pri = len([e for e in exceptions if (e.get("priority") or "").lower() == "high"])
        lines.append("## Exception Summary")
        lines.append("")
        lines.append(f"- Total Exceptions: **{len(exceptions)}**")
        lines.append(f"- Open Exceptions: **{open_exc}**")
        lines.append(f"- High-Priority Exceptions: **{high_pri}**")
        lines.append("")

        if exceptions:
            lines.append("### Open Exceptions Detail")
            lines.append("")
            lines.append("| ID | Settlement | Bank Transaction | Type | Priority | Confidence | Status |")
            lines.append("|---|---|---|---|---|---:|---|")
            for exc in exceptions:
                eid = exc.get("exception_id") or exc.get("id") or "EXC-001"
                sid = exc.get("settlement_id") or "N/A"
                btid = exc.get("bank_transaction_id") or "N/A"
                etype = exc.get("exception_type") or "manual_review"
                pri = exc.get("priority") or "medium"
                conf = float(exc.get("confidence") or 0.0)
                st = exc.get("resolution_status") or "open"
                lines.append(f"| {eid} | {sid} | {btid} | {etype} | {pri} | {conf:.4f} | {st} |")
            lines.append("")

    # 4. Transactions Detail Table
    if "transactions" in sections:
        lines.append("## Transaction Records Detail")
        lines.append("")
        if not transactions:
            lines.append("No transaction records match the current filter selection.")
        else:
            from reports.pdf_generator import format_engine_decision
            lines.append("| Date | Description | Source | Amount | Taxonomy | Engine Decision |")
            lines.append("|---|---|---|---:|---|---|")
            for t in transactions[:100]: # Cap table at 100 rows for readability in markdown
                dt = t.get("date", "N/A")
                desc = str(t.get("description", ""))[:30]
                src = t.get("source_name") or t.get("source_type") or "Primary"
                amt = float(t.get("amount") or 0.0)
                tax = t.get("taxonomy_status", "UNMATCHED")
                dec = format_engine_decision(t)
                lines.append(f"| {dt} | {desc} | {src} | ₹{amt:,.2f} | {tax} | {dec} |")
            if len(transactions) > 100:
                lines.append(f"*... and {len(transactions) - 100} additional records.*")
        lines.append("")

    # 5. Integrity Check
    if "integrity" in sections:
        lines.append("## Integrity Verification Audit")
        lines.append("")
        lines.append(f"- SETTLED: **{integrity.get('settled', 0)}**")
        lines.append(f"- MATCHED: **{integrity.get('matched', 0)}**")
        lines.append(f"- SIMILAR: **{integrity.get('similar', 0)}**")
        lines.append(f"- UNMATCHED: **{integrity.get('unmatched', 0)}**")
        lines.append(f"- Accounted Records: **{integrity.get('accounted_for', 0)}/{integrity.get('total_transactions', 0)}**")
        lines.append(f"- Result: **{'PASS' if integrity.get('pass') else 'FAIL'}**")
        lines.append("")

    lines.append("---")
    lines.append("Generated by Ledger AI.")
    return "\n".join(lines)


# Backwards compatibility function wrapper
def build_report(reconciliation=None, exceptions=None) -> str:
    return build_markdown_report()


def main():
    report_text = build_markdown_report()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report_text, encoding="utf-8")
    print(report_text)
    print(f"\nSaved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()