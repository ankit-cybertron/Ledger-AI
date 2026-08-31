# Ledger AI — Architectural & Technical Documentation Directory

Welcome to the canonical technical documentation suite for **Ledger AI**, an automated financial reconciliation, multi-source ingestion, transaction matching, cash flow forecasting, and audit reporting platform.

Below is the complete index of dedicated documentation files detailing every core component, status taxonomy rule, ingestion stage, matching algorithm, ML classifier, LLM agent, and reporting system implemented in the codebase.

---

## 📚 Technical Documentation Index

### 1. Taxonomy Status Specifications
Detailed algorithms, classification rules, criteria, formulas, and UI badges for each implemented outcome status:

- 🟢 **[SETTLED Status Specification](status_settled.md)**  
  Primary vs Counterpart rule, exact UTR/reference matching, zero amount variance, 1-to-N batch fee equations, and settlement criteria.

- 🔵 **[MATCHED Status Specification](status_matched.md)**  
  Counterpart-to-Counterpart reconciliation, composite weighted scoring engine ($S \ge 0.85$), amount/date tolerance parameters, and auto-approval thresholds.

- 🟡 **[SIMILAR Status Specification](status_similar.md)**  
  Candidate similarity scoring ($0.50 \le \text{Score} < 0.85$), tokenized description keyword extraction, candidate drawer, and shared keyword UI badges.

- 🔴 **[UNMATCHED Status Specification](status_unmatched.md)**  
  Discrepancy detection, isolated transaction handling, exception ledger routing, and on-demand LLM match triggers.

---

### 2. Core Engine & Subsystem Specifications

- 🤖 **[LLM Matching Agent Specification](llm_matching_agent.md)**  
  Groq API integration (`llm/query_llm.py`) with multi-key failover (`GROQ_API_KEY` rotation), fallback models (`openai/gpt-oss-120b`, `qwen/qwen3.6-27b`), prompt construction, and JSON reasoning output schemas.

- 📥 **[Statement Ingestion Pipeline Specification](ingestion_pipeline.md)**  
  Full 5-stage ingestion process: file reading (CSV/XLSX/PDF), duplicate column resolution, 3-stage column mapping (exact, fuzzy, AI smart import), locale normalizer, clean fallback ID generation (`BNK-TXN-0004`), and SHA-256 content deduplication.

- ⚡ **[Multi-Pass Reconciliation Engine Specification](reconciliation_engine.md)**  
  Sequential 6-step reconciliation pipeline (`reconciler/pipeline_runner.py`), primary vs. counterpart statement pool separation, and symmetric mirror-pair deduplication (`seen_matched_ids`).

- 📈 **[Forward Cash Forecaster Specification](forecasting_logic.md)**  
  Rules-first financial projection engine: seasonal decomposition, moving-average trend analysis, pending settlement estimation, recurring pattern overlay, and beginning balance cascade propagation.

- 📄 **[Reports & PDF Generation Specification](reports_and_pdf_generation.md)**  
  Filtered dataset builder (`reports/report_builder.py`), branded ReportLab PDF compilation (`reports/pdf_generator.py`), Matplotlib chart rendering, and audit integrity verification.

---

### 3. Guides & System Specifications

- 🛠️ **[Developer Reconciliation & Status Guide](developer_reconciliation_guide.md)**  
  Comprehensive developer guide summarizing file mappings, code references, deduplication algorithms, master source table views, report generation pipelines, and UI keyword comparison logic.

- 📐 **[Canonical Reconciliation Mechanism Specification](reconciliation_matching_mechanism.md)**  
  Full mathematical specifications, scoring equations, 12-dimensional ML feature vector schema, subset-sum fee equation solver, and four-status taxonomy rules.

---

## 🛠️ Verification & Test Suite

Run the full pytest suite across all test modules to validate pipeline logic, API contracts, closed period vault flows, forecasting engines, and ingestion normalizers:

```bash
PYTHONPATH=. ./.venv/bin/pytest -q
```
