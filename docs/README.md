# Ledger AI — Architectural & Technical Documentation Directory

Welcome to the canonical technical documentation suite for **Ledger AI**, an automated financial reconciliation and transaction matching platform.

Below is the complete index of dedicated documentation files detailing every core component, status taxonomy rule, ingestion stage, matching algorithm, ML classifier, and LLM agent.

---

## 📚 Technical Documentation Index

### 1. Taxonomy Status Specifications
Detailed high-level algorithms, classification rules, criteria, formulas, and UI badges for each outcome status:

- 🟢 **[SETTLED Status Specification](status_settled.md)**  
  Exact UTR/reference matching, zero amount variance, 1-to-N batch fee equations, and settlement criteria.

- 🔵 **[MATCHED Status Specification](status_matched.md)**  
  Composite weighted scoring engine ($S \ge 0.85$), amount/date tolerance parameters, and auto-approval thresholds.

- 🟡 **[SIMILAR Status Specification](status_similar.md)**  
  Candidate similarity scoring ($0.50 \le \text{Score} < 0.85$), description keyword tokenization, and candidate drawer logic.

- 🔴 **[UNMATCHED Status Specification](status_unmatched.md)**  
  Discrepancy detection, isolated transaction handling, exception ledger routing, and LLM fallback trigger.

---

### 2. Core Engine & Subsystem Specifications

- 🤖 **[LLM Matching Agent Specification](llm_matching_agent.md)**  
  Google Gemini API agent architecture, prompt construction, structured JSON payloads, and reasoning output schemas.

- 📥 **[Statement Ingestion Pipeline Specification](ingestion_pipeline.md)**  
  Full 5-stage ingestion process: file reading (CSV/XLSX/PDF), duplicate column resolution, 3-stage column mapping, locale normalizer, clean fallback ID generation (`BNK-TXN-0004`), and SHA-256 deduplication.

- ⚡ **[Multi-Pass Reconciliation Engine Specification](reconciliation_engine.md)**  
  Sequential 3-pass matching cascade, primary vs. counterpart statement pool separation, and symmetric mirror-pair deduplication (`seen_matched_ids`).

---

### 3. Guides & Core Specifications

- 🛠️ **[Developer Reconciliation & Status Guide](developer_reconciliation_guide.md)**  
  Comprehensive developer guide summarizing file mappings, code references, deduplication rules, and keyword extraction.

- 📐 **[Canonical Reconciliation Mechanism Specification](reconciliation_matching_mechanism.md)**  
  Full mathematical specifications, scoring equations, ML feature vector schema, and system architecture.

---

## 🛠️ Quick Verification Commands

Run the full pytest suite to validate all pipeline logic, API contracts, and ingestion normalizers:

```bash
PYTHONPATH=. pytest --ignore=tests/test_pipeline.py
```
