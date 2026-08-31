# Ledger AI — Reports & PDF Generation Subsystem Specification

> **Subsystem**: `reports/report_builder.py`, `reports/pdf_generator.py`, & `config/report_config.json`  
> **Core Purpose**: Filtered report aggregation, dynamic ReportLab PDF compilation, executive chart rendering, and period closure vaulting.

---

## 1. Executive Summary

The **Reports Subsystem** generates executive-grade financial audit reports and downloadable PDFs for the Ledger AI platform. It provides filtered dataset extraction, dynamic multi-status metrics, chart generation via Matplotlib, 30-day forward cash flow forecasts, and zero-loss audit integrity verification.

---

## 2. Core Architectural Components

### 2.1 Dataset Builder (`reports/report_builder.py`)
- **Function**: `build_filtered_report_data(filters)`
- **Responsibilities**:
  - Filters transaction records by status (`SETTLED`, `MATCHED`, `SIMILAR`, `UNMATCHED`), source statements (`Bank Statement`, `Razorpay`, etc.), and date ranges.
  - Injects global `_BEGINNING_BALANCE` and recalculates cumulative balances.
  - Computes 30-day forward cash flow forecasts (`build_forecast`).
  - Assembles overview metrics, exception breakdown tables, and audit logs.

### 2.2 Branded PDF Generator (`reports/pdf_generator.py`)
- **Function**: `generate_pdf_report(filters)`
- **Responsibilities**:
  - Uses ReportLab to generate print-ready PDF documents (`letter` size).
  - Implements `NumberedCanvas` for dynamic two-pass page numbering ("Page X of Y") and headers/footers.
  - Renders Matplotlib charts (Status composition pie, Amount variance bar, 30D forecast trend) as high-DPI image cards.
  - Renders styled transaction tables with alternating row fills, status badge pills, and sticky column headers.

### 2.3 Report Styling Configuration (`config/report_config.json`)
- Houses design constants, color tokens (`#0f172a`, `#10b981`, `#3b82f6`, `#f59e0b`, `#ef4444`), page margins, font sizes, and header layout parameters.

---

## 3. End-to-End Report Generation Workflow

```
  ┌──────────────────────────────────────────────────────────┐
  │      User Applies Filters in UI (#sub-reports)           │
  │  Statuses, Statement Sources, Date Range, Section Toggles│
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │   Report Dataset Builder (`reports/report_builder.py`)   │
  │ Apply filters -> Map Taxonomy -> Add Forecast -> Integrity│
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │  Matplotlib Chart Compilation (`reports/pdf_generator.py`)│
  │ Generate Status Pie, Source Bar & 30D Forecast Trend PNGs│
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │     ReportLab Document Flowable Assembly                 │
  │ Title Block -> KPI Cards -> Charts -> Tables -> Audit    │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │      Two-Pass NumberedCanvas Output Stream               │
  │ Returns binary PDF buffer for browser download (`/report/pdf`)│
  └──────────────────────────────────────────────────────────┘
```

---

## 4. API Endpoints

### 4.1 POST `/api/reports/build`
Returns filtered report dataset in JSON format for web dashboard preview.

### 4.2 GET `/report/pdf`
Compiles and streams the branded PDF report file to the client for immediate download or print preview.

**Query Parameters**:
- `statuses`: Comma-separated status string (e.g. `SETTLED,MATCHED,SIMILAR,UNMATCHED`).
- `sources`: Comma-separated statement source list or `all`.
- `start_date`: Start date (`YYYY-MM-DD`).
- `end_date`: End date (`YYYY-MM-DD`).
- `sections`: Sections to include (`summary`, `charts`, `transactions`, `exceptions`, `forecast`).

---

## 5. Key Files & Code Reference

| File Path | Responsible Class / Function | Purpose |
|---|---|---|
| `reports/report_builder.py` | `build_filtered_report_data()` | Authoritative filtered report dataset aggregator. |
| `reports/pdf_generator.py` | `generate_pdf_report()`, `NumberedCanvas` | ReportLab PDF compilation and chart generation. |
| `config/report_config.json` | JSON configuration | Layout tokens, colors, and typography settings. |
| `frontend/api/routes.py` | `/api/reports/build`, `/report/pdf` | Flask HTTP endpoints for report preview and PDF download. |
| `frontend/static/js/dashboard.js` | `refreshReportsView()`, `downloadPDFReport()` | Client UI controller for report filtering and download. |
