"""
reports/pdf_generator.py — Premium Branded PDF Generator for Ledger AI.

Features:
  - Executive-grade light theme layout suited for printing/auditing.
  - Clean currency formatting using 'Rs.' for universal Helvetica compatibility.
  - Visual KPI Summary Cards with status pill indicators.
  - Page-break-aware table formatting with sticky headers and alternating row fills.
  - Matplotlib charts rendered as high-DPI image cards.
  - Dynamic two-pass NumberedCanvas for header/footer and page numbering.
"""

import io
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak, HRFlowable
)

from reports.report_builder import build_filtered_report_data


import json
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def _load_report_config() -> dict:
    """Loads PDF report design and styling constants from config/report_config.json."""
    cfg_file = Path(__file__).resolve().parent.parent / "config" / "report_config.json"
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _setup_pdf_fonts() -> tuple[str, str, str]:
    """Register Inter brand fonts for ReportLab if available, with fallback to system Arial/Helvetica."""
    report_cfg = _load_report_config()
    fonts_cfg = report_cfg.get("font_families", {})

    font_name = fonts_cfg.get("fallback_name", "Helvetica")
    font_bold = fonts_cfg.get("fallback_bold", "Helvetica-Bold")
    font_mono = fonts_cfg.get("fallback_mono", "Courier")

    candidate_regular = fonts_cfg.get("regular", [
        "reports/fonts/Inter-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf"
    ])
    candidate_bold = fonts_cfg.get("bold", [
        "reports/fonts/Inter-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf"
    ])

    reg_path = next((p for p in candidate_regular if os.path.exists(p)), None)
    bold_path = next((p for p in candidate_bold if os.path.exists(p)), None)

    if reg_path and bold_path:
        try:
            pdfmetrics.registerFont(TTFont("Inter", reg_path))
            pdfmetrics.registerFont(TTFont("Inter-Bold", bold_path))
            font_name = "Inter"
            font_bold = "Inter-Bold"
        except Exception:
            pass

    return font_name, font_bold, font_mono


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for adding Ledger AI running headers, subtle diagonal watermark, and page numbers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_and_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_and_footer(self, page_count: int):
        self.saveState()

        font_name, font_bold, _ = _setup_pdf_fonts()
        report_cfg = _load_report_config()

        # Watermark parameters loaded from config/report_config.json
        wm_text = report_cfg.get("watermark_text", "CONFIDENTIAL — LEDGER AI AUDIT")
        wm_opacity = float(report_cfg.get("watermark_opacity", 0.06))
        wm_size = int(report_cfg.get("watermark_font_size", 8))
        wm_step_y = int(report_cfg.get("watermark_step_y", 160))
        wm_angle = int(report_cfg.get("watermark_angle", 35))

        self.saveState()
        self.setFont(font_bold, wm_size)
        self.setFillColor(colors.Color(0.58, 0.64, 0.72, alpha=wm_opacity))
        
        for y_pos in range(100, 750, wm_step_y):
            for x_pos in range(40, 580, 200):
                self.saveState()
                self.translate(x_pos, y_pos)
                self.rotate(wm_angle)
                self.drawString(0, 0, wm_text)
                self.restoreState()
        self.restoreState()

        # Running Header on page 2+
        if self._pageNumber > 1:
            self.setFont(font_bold, 8)
            self.setFillColor(colors.HexColor("#0f172a"))
            self.drawString(36, 11 * inch - 28, "Ledger")
            self.setFillColor(colors.HexColor("#2563eb"))
            self.drawString(66, 11 * inch - 28, "AI")
            self.setFont(font_name, 8)
            self.setFillColor(colors.HexColor("#64748b"))
            self.drawString(80, 11 * inch - 28, "— Financial Reconciliation Audit Report")

            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.75)
            self.line(36, 11 * inch - 34, 8.5 * inch - 36, 11 * inch - 34)

        # Running Footer on all pages
        self.setFont(font_name, 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(36, 24, "Confidential — Generated by Ledger AI Reconciliation Engine")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 36, 24, page_str)
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.75)
        self.line(36, 36, 8.5 * inch - 36, 36)
        self.restoreState()


def format_engine_decision(t: Dict[str, Any]) -> str:
    """Format human-readable engine decision string showing stage/rule that produced the match call."""
    tax = (t.get("taxonomy_status") or "").upper().strip()
    status = (t.get("status") or "").lower().strip()
    stage = (t.get("stage") or "").lower().strip()
    decision = (t.get("decision") or "").lower().strip()
    reason = str(t.get("reason") or "").strip()
    rule_name = str(t.get("rule_name") or t.get("rule") or "").strip()

    if rule_name and rule_name.lower() not in {"none", "n/a", ""}:
        return f"Rule: {rule_name[:24]}"
    elif stage == "exact" or status in {"auto", "exact"} or decision in {"exact", "auto"}:
        return "Rule Engine: Exact UTR Match"
    elif stage == "tolerance" or status == "tolerance" or decision == "tolerance":
        return "Rule Engine: Tolerance Match"
    elif stage == "split" or status == "split":
        return "Rule Engine: Split Settlement"
    elif stage == "ml" or status == "ml":
        conf = t.get("confidence")
        conf_str = f" ({conf:.2f})" if isinstance(conf, (int, float)) and conf > 0 else ""
        return f"ML Model{conf_str}"
    elif stage == "llm" or status == "llm":
        return "Groq LLM Agent"
    elif stage == "manual" or status in {"manual", "manual_review"}:
        return "Manual Review Override"
    elif tax == "SETTLED":
        return "Automated Settlement"
    elif tax == "MATCHED":
        return "Rule Engine: Parity Match"
    elif tax == "SIMILAR":
        return "Similarity Engine Review"
    elif reason and reason.lower() not in {"none", "unmatched exception", "n/a", ""}:
        return reason[:26]
    else:
        return "Unmatched Exception"


def render_chart_images(charts_data: Dict[str, Any]) -> Dict[str, io.BytesIO]:
    """Render high-DPI corporate visualizations to in-memory PNG images using Matplotlib."""
    plt.style.use("default")
    images = {}

    primary_color = "#2563eb"
    success_color = "#10b981"
    warning_color = "#f59e0b"
    danger_color = "#ef4444"
    indigo_color = "#6366f1"
    sky_color = "#0284c7"

    def apply_clean_spines(ax):
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color("#cbd5e1")
        ax.spines['bottom'].set_color("#cbd5e1")
        ax.tick_params(colors="#475569", labelsize=8)
        ax.grid(True, linestyle="--", alpha=0.3, color="#cbd5e1")

    # 1. Status Breakdown Donut
    sb = charts_data.get("status_breakdown", {})
    counts = sb.get("counts", [0, 0, 0, 0])
    labels = sb.get("labels", ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"])
    chart_colors = [success_color, primary_color, warning_color, danger_color]

    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    total_val = sum(counts)
    if total_val > 0:
        wedges, texts, autotexts = ax.pie(
            counts, labels=None, autopct=lambda pct: f"{pct:.1f}%" if pct > 4 else "", startangle=140,
            colors=chart_colors, wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2.5),
            pctdistance=0.72
        )
        for t in autotexts:
            t.set_fontsize(8)
            t.set_weight("bold")
            t.set_color("#0f172a")

        legend_labels = [f"{l}: {c}" for l, c in zip(labels, counts)]
        ax.legend(wedges, legend_labels, loc="lower center", bbox_to_anchor=(0.5, -0.28), ncol=2, fontsize=7.5, frameon=False)
    else:
        ax.text(0.5, 0.5, "No Data Available", horizontalalignment="center", verticalalignment="center", fontsize=9, color="#64748b")
        ax.axis("off")
    ax.set_title("Status Breakdown", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["status_breakdown"] = buf
    plt.close(fig)

    # 2. Reconciliation Funnel
    fn = charts_data.get("funnel_data", {})
    fn_stages = fn.get("stages", ["Total", "Auto", "Settled", "Similar", "Unmatched"])
    fn_counts = fn.get("counts", [0, 0, 0, 0, 0])
    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    apply_clean_spines(ax)
    y_pos = range(len(fn_stages))
    ax.barh(y_pos, fn_counts, color=indigo_color, height=0.5, edgecolor="none", alpha=0.9)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(fn_stages, fontsize=8, color="#0f172a", fontweight="500")
    ax.invert_yaxis()
    ax.set_xlabel("Records Count", fontsize=8, color="#475569")
    ax.set_title("Reconciliation Stage Funnel", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    max_c = max(fn_counts) if fn_counts else 1
    for i, v in enumerate(fn_counts):
        ax.text(v + max_c * 0.02, i, f"{v:,}", va="center", fontsize=8, fontweight="bold", color="#1e293b")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["funnel"] = buf
    plt.close(fig)

    # 3. Source Contribution Stacked Bar
    sc = charts_data.get("source_contribution", {})
    s_labels = sc.get("labels", ["Default"])
    s_datasets = sc.get("datasets", {})
    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    apply_clean_spines(ax)
    bottom = [0] * len(s_labels)
    tax_keys = ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]
    tax_cols = [success_color, primary_color, warning_color, danger_color]

    formatted_x_labels = []
    for lbl in s_labels:
        s_lbl = str(lbl)
        if len(s_lbl) > 12 and " " in s_lbl:
            words = s_lbl.split(" ")
            mid = len(words) // 2
            formatted_x_labels.append("\n".join([" ".join(words[:mid]), " ".join(words[mid:])]))
        elif len(s_lbl) > 14:
            formatted_x_labels.append(s_lbl[:12] + "…")
        else:
            formatted_x_labels.append(s_lbl)

    for key, col in zip(tax_keys, tax_cols):
        vals = s_datasets.get(key, [0] * len(s_labels))
        ax.bar(formatted_x_labels, vals, bottom=bottom, label=key, color=col, width=0.45)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_title("Source Contribution Breakdown", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    ax.legend(fontsize=7, loc="upper right", frameon=False)
    plt.xticks(rotation=0, fontsize=7.5)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["source_contribution"] = buf
    plt.close(fig)

    # 4. Confidence Distribution Histogram
    cd = charts_data.get("confidence_distribution", {})
    c_labels = cd.get("labels", ["0.0-0.5", "0.5-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"])
    c_counts = cd.get("counts", [0, 0, 0, 0, 0])
    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    apply_clean_spines(ax)
    ax.bar(c_labels, c_counts, color=sky_color, width=0.5, alpha=0.9)
    ax.set_title("ML Model Confidence Distribution", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    ax.set_xlabel("Confidence Score Range", fontsize=8, color="#475569")
    ax.set_ylabel("Transactions", fontsize=8, color="#475569")
    plt.xticks(fontsize=7.5)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["confidence_dist"] = buf
    plt.close(fig)

    # 5. Exception Aging Bar
    ea = charts_data.get("exception_aging", {})
    e_labels = ea.get("labels", ["0-1 day", "1-3 days", "3-7 days", "7+ days"])
    e_counts = ea.get("counts", [0, 0, 0, 0])
    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    apply_clean_spines(ax)
    ax.bar(e_labels, e_counts, color=danger_color, width=0.5, alpha=0.85)
    ax.set_title("Exception Aging Analysis", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    ax.set_xlabel("Age Bracket", fontsize=8, color="#475569")
    ax.set_ylabel("Open Exceptions", fontsize=8, color="#475569")
    plt.xticks(fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["exception_aging"] = buf
    plt.close(fig)

    # 6. Match Rate Trend Line with Gradient Fill
    tl = charts_data.get("trend_line", {})
    t_labels = tl.get("labels", ["Run 1"])
    t_rates = tl.get("match_rates", [0.0])
    fig, ax = plt.subplots(figsize=(4.5, 3.0), dpi=300)
    apply_clean_spines(ax)
    ax.plot(t_labels, t_rates, marker="o", color=success_color, linewidth=2.5, markersize=6, markerfacecolor="white", markeredgewidth=2)
    ax.fill_between(t_labels, t_rates, color=success_color, alpha=0.12)
    ax.set_title("Historical Match Rate Trend", fontsize=10, fontweight="bold", pad=10, color="#0f172a")
    ax.set_ylabel("Parity Match Rate (%)", fontsize=8, color="#475569")
    ax.set_ylim(0, 105)
    plt.xticks(rotation=15, fontsize=7.5)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    images["trend_line"] = buf
    plt.close(fig)

    return images


def generate_pdf_report(data: Optional[Dict[str, Any]] = None, filters: Optional[Dict[str, Any]] = None) -> bytes:
    """Generate professional branded PDF report binary stream."""
    if data is None:
        data = build_filtered_report_data(filters)

    summary = data.get("summary", {})
    transactions = data.get("transactions", [])
    exceptions = data.get("exceptions", [])
    charts_data = data.get("charts", {})
    integrity = data.get("integrity", {})
    meta = data.get("meta", {})
    sections = data.get("sections", ["summary", "charts", "transactions", "exceptions", "integrity"])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=44,
        bottomMargin=44
    )

    styles = getSampleStyleSheet()
    font_name, font_bold, _ = _setup_pdf_fonts()

    # Premium Typography Styles matching product design system
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0f172a")
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#64748b")
    )
    h1_style = ParagraphStyle(
        "SectionH1",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=14,
        spaceAfter=6
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#334155")
    )
    cell_right_style = ParagraphStyle(
        "TableCellRight",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=7.5,
        leading=10,
        alignment=2,  # Right align
        textColor=colors.HexColor("#334155")
    )
    cell_bold_style = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0f172a")
    )
    header_cell_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=8,
        leading=11,
        textColor=colors.white
    )
    header_cell_right = ParagraphStyle(
        "HeaderCellRight",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=8,
        leading=11,
        alignment=2,
        textColor=colors.white
    )

    story = []

    # 1. Header Title Block with Branded Badge & Divider Line
    story.append(Paragraph('<font color="#0f172a"><b>Ledger</b></font><font color="#2563eb"><b>AI</b></font>', title_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Automated Financial Reconciliation & Audit Report", subtitle_style))
    story.append(Spacer(1, 6))

    meta_str = f"<b>Generated:</b> {meta.get('generated_at', 'N/A')} &nbsp;|&nbsp; <b>Statuses:</b> {', '.join(meta.get('statuses', []))} &nbsp;|&nbsp; <b>Sources:</b> {', '.join(meta.get('sources', []))}"
    story.append(Paragraph(meta_str, subtitle_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563eb"), spaceAfter=12))

    # 2. Executive Summary Cards & Metrics Block
    if "summary" in sections:
        story.append(Paragraph("Executive Summary & Operational KPIs", h1_style))

        # KPI Summary Table using clean 'Rs.' currency representation for Helvetica compatibility
        dep_val = f"Rs. {summary.get('deposits_total', 0.0):,.2f}"
        pay_val = f"Rs. {summary.get('payments_total', 0.0):,.2f}"
        var_val = f"Rs. {summary.get('variance', 0.0):,.2f}"

        summary_rows = [
            [
                Paragraph("Metric", header_cell_style),
                Paragraph("Value", header_cell_right),
                Paragraph("Taxonomy Status", header_cell_style),
                Paragraph("Count", header_cell_right)
            ],
            [
                Paragraph("Total Transactions", cell_bold_style),
                Paragraph(str(summary.get("total_transactions", 0)), cell_right_style),
                Paragraph('<font color="#15803d"><b>SETTLED</b></font>', cell_style),
                Paragraph(str(summary.get("settled_count", 0)), cell_right_style)
            ],
            [
                Paragraph("Reconciled %", cell_bold_style),
                Paragraph(f"{summary.get('percent_reconciled', 0.0):.1f}%", cell_right_style),
                Paragraph('<font color="#1d4ed8"><b>MATCHED</b></font>', cell_style),
                Paragraph(str(summary.get("matched_count", 0)), cell_right_style)
            ],
            [
                Paragraph("Total Deposits", cell_bold_style),
                Paragraph(dep_val, cell_right_style),
                Paragraph('<font color="#b45309"><b>SIMILAR</b></font>', cell_style),
                Paragraph(str(summary.get("similar_count", 0)), cell_right_style)
            ],
            [
                Paragraph("Total Payments", cell_bold_style),
                Paragraph(pay_val, cell_right_style),
                Paragraph('<font color="#b91c1c"><b>UNMATCHED</b></font>', cell_style),
                Paragraph(str(summary.get("unmatched_count", 0)), cell_right_style)
            ],
            [
                Paragraph("Net Variance", cell_bold_style),
                Paragraph(var_val, cell_right_style),
                Paragraph("Period Settled", cell_bold_style),
                Paragraph("YES" if summary.get("period_settled") else "NO", cell_right_style)
            ],
        ]
        sum_table = Table(summary_rows, colWidths=[2.0 * inch, 1.75 * inch, 2.0 * inch, 1.75 * inch])
        sum_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(sum_table)
        story.append(Spacer(1, 12))

    # 3. Analytics Visualizations Section
    if "charts" in sections and charts_data:
        story.append(Paragraph("Reconciliation Analytics Visualizations", h1_style))
        img_bufs = render_chart_images(charts_data)

        c1 = Image(img_bufs["status_breakdown"], width=3.6 * inch, height=2.4 * inch)
        c2 = Image(img_bufs["funnel"], width=3.6 * inch, height=2.4 * inch)
        c3 = Image(img_bufs["source_contribution"], width=3.6 * inch, height=2.4 * inch)
        c4 = Image(img_bufs["confidence_dist"], width=3.6 * inch, height=2.4 * inch)
        c5 = Image(img_bufs["exception_aging"], width=3.6 * inch, height=2.4 * inch)
        c6 = Image(img_bufs["trend_line"], width=3.6 * inch, height=2.4 * inch)

        grid1 = Table([[c1, c2]], colWidths=[3.75 * inch, 3.75 * inch])
        grid1.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))

        grid2 = Table([[c3, c4]], colWidths=[3.75 * inch, 3.75 * inch])
        grid2.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))

        grid3 = Table([[c5, c6]], colWidths=[3.75 * inch, 3.75 * inch])
        grid3.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))

        story.append(grid1)
        story.append(Spacer(1, 6))
        story.append(grid2)
        story.append(Spacer(1, 6))
        story.append(grid3)
        story.append(Spacer(1, 12))

    # 4. Exception Audit Section
    if "exceptions" in sections:
        story.append(Paragraph("Exception Audit & Review Ledger", h1_style))
        if not exceptions:
            story.append(Paragraph("No exceptions recorded for the selected filter scope.", cell_style))
        else:
            exc_table_data = [
                [
                    Paragraph("ID", header_cell_style),
                    Paragraph("Settlement ID", header_cell_style),
                    Paragraph("Bank Txn ID", header_cell_style),
                    Paragraph("Type", header_cell_style),
                    Paragraph("Priority", header_cell_style),
                    Paragraph("Conf.", header_cell_right),
                    Paragraph("Status", header_cell_style)
                ]
            ]
            for exc in exceptions:
                eid = Paragraph(str(exc.get("exception_id") or exc.get("id") or "EXC-1"), cell_bold_style)
                sid = Paragraph(str(exc.get("settlement_id") or "N/A"), cell_style)
                btid = Paragraph(str(exc.get("bank_transaction_id") or "N/A"), cell_style)
                etype = Paragraph(str(exc.get("exception_type") or "review"), cell_style)
                pri = Paragraph(str(exc.get("priority") or "medium").upper(), cell_style)
                conf = Paragraph(f"{float(exc.get('confidence') or 0.0):.2f}", cell_right_style)
                st = Paragraph(str(exc.get("resolution_status") or "open").upper(), cell_bold_style)
                exc_table_data.append([eid, sid, btid, etype, pri, conf, st])

            t_exc = Table(exc_table_data, colWidths=[0.9 * inch, 1.4 * inch, 1.4 * inch, 1.2 * inch, 0.8 * inch, 0.6 * inch, 1.2 * inch], repeatRows=1)
            t_exc.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t_exc)
        story.append(Spacer(1, 12))

    # 5. Transactions Detail Section (Separated into Distinct Status Tables)
    if "transactions" in sections:
        story.append(Paragraph("Transaction Detail Audit Tables", h1_style))
        if not transactions:
            story.append(Paragraph("No transaction records match the current filter selection.", cell_style))
        else:
            status_groups = [
                ("SETTLED", "Settled Transactions Ledger", "#15803d"),
                ("MATCHED", "Matched Transactions Ledger", "#1d4ed8"),
                ("SIMILAR", "Similar Review Transactions Ledger", "#b45309"),
                ("UNMATCHED", "Exception / Unmatched Transactions Ledger", "#b91c1c")
            ]

            h2_style = ParagraphStyle(
                "SubSectionH2",
                parent=styles["Heading2"],
                fontName=font_bold,
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor("#0f172a"),
                spaceBefore=10,
                spaceAfter=4
            )

            # Group transactions into map
            grouped = {"SETTLED": [], "MATCHED": [], "SIMILAR": [], "UNMATCHED": []}
            for t in transactions:
                st_key = str(t.get("taxonomy_status") or "UNMATCHED").upper().strip()
                if st_key in grouped:
                    grouped[st_key].append(t)
                else:
                    grouped["UNMATCHED"].append(t)

            for st_code, st_title, badge_color in status_groups:
                group_items = grouped[st_code]
                if not group_items:
                    continue

                subtotal = sum(float(t.get("amount") or 0.0) for t in group_items)
                header_p = Paragraph(f"<font color='{badge_color}'><b>{st_title}</b></font> &nbsp;—&nbsp; Total: <b>{len(group_items)} records</b> (Rs. {subtotal:,.2f})", h2_style)
                story.append(header_p)

                txn_rows = [
                    [
                        Paragraph("Date", header_cell_style),
                        Paragraph("Description", header_cell_style),
                        Paragraph("Source", header_cell_style),
                        Paragraph("Amount", header_cell_right),
                        Paragraph("Status", header_cell_style),
                        Paragraph("Engine Decision", header_cell_style)
                    ]
                ]

                for t in group_items[:100]:  # Cap per status table for printable document layout
                    dt = Paragraph(str(t.get("date", "")), cell_style)
                    desc = Paragraph(str(t.get("description", ""))[:32], cell_style)
                    src = Paragraph(str(t.get("source_name") or t.get("source_type") or "Primary")[:18], cell_style)
                    
                    amt_num = float(t.get("amount") or 0.0)
                    amt_str = f"Rs. {amt_num:,.2f}"
                    amt = Paragraph(amt_str, cell_right_style)
                    
                    tax_p = Paragraph(f"<font color='{badge_color}'><b>{st_code}</b></font>", cell_style)
                    decision_text = format_engine_decision(t)
                    dec = Paragraph(decision_text, cell_style)
                    txn_rows.append([dt, desc, src, amt, tax_p, dec])

                t_sub = Table(txn_rows, colWidths=[0.85 * inch, 2.1 * inch, 1.1 * inch, 1.15 * inch, 0.95 * inch, 1.35 * inch], repeatRows=1)
                t_sub.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(t_sub)
                story.append(Spacer(1, 8))

        story.append(Spacer(1, 10))

    # 6. Integrity Verification Section
    if "integrity" in sections:
        story.append(Paragraph("System Integrity Verification", h1_style))
        pass_text = "<font color='#15803d'><b>PASS — 100% Transactions Accounted For</b></font>" if integrity.get("pass") else "<font color='#b91c1c'><b>FAIL — Discrepancies Detected</b></font>"
        
        integ_rows = [
            [Paragraph("Verification Metric", header_cell_style), Paragraph("Count / Result", header_cell_style)],
            [Paragraph("SETTLED Transactions", cell_bold_style), Paragraph(str(integrity.get("settled", 0)), cell_style)],
            [Paragraph("MATCHED Transactions", cell_bold_style), Paragraph(str(integrity.get("matched", 0)), cell_style)],
            [Paragraph("SIMILAR Review Transactions", cell_bold_style), Paragraph(str(integrity.get("similar", 0)), cell_style)],
            [Paragraph("UNMATCHED Transactions", cell_bold_style), Paragraph(str(integrity.get("unmatched", 0)), cell_style)],
            [Paragraph("Accounted Transactions", cell_bold_style), Paragraph(f"{integrity.get('accounted_for', 0)} / {integrity.get('total_transactions', 0)}", cell_style)],
            [Paragraph("Audit Integrity Status", cell_bold_style), Paragraph(pass_text, cell_style)],
        ]
        t_integ = Table(integ_rows, colWidths=[3.75 * inch, 3.75 * inch])
        t_integ.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_integ)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()
