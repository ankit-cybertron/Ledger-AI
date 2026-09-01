# Ledger AI — Architectural & Technical Documentation Directory

Welcome to the canonical technical documentation suite for **Ledger AI**, an autonomous financial reconciliation, multi-source ingestion, transaction matching, cash flow forecasting, and audit reporting platform.

The documentation is organized into clear, sequential, numbered text (`.txt`) files across logical subdirectories:

---

## Technical Documentation Index

### 1. Product Features (`docs/01_features/`)
- **`01_features_overview.txt`**: Standard Import, Smart Import (Groq AI header mapping & alias registry), Load Pre-configured Test Benchmark Data, and advantages of preloaded benchmark feeds.
- **`02_forward_cash_forecasting.txt`**: Technical and mathematical specification of the 30-to-90 day Forward Cash Forecaster.
- **`03_side_by_side_record_comparison_and_keyword_analytics.txt`**: Executive 1160px grid comparison modal, adaptive unmatched compact mode (760px), multi-parameter Chart.js visuals (Radar/Bar/Scatter), and cross-record keyword token overlap intelligence.

### 2. Pipeline Layers (`docs/02_pipeline_layers/`)
- **`01_ingestion/`**: Multi-format parser, numeric/currency normalizer, schema AI mapper, SHA-256 deduplication, and Primary/Counterpart separator.
- **`02_layer1_exact_matching/`**: Exact UTR/RRN identifier matcher and amount parity date window validation.
- **`03_layer2_settlement_lag_fee_solver/`**: 1-to-N batch payout solver, MDR fee & GST reconciliation, and channel lag estimation.
- **`04_layer3_ml_composite_scorer/`**: 12D feature vector matrix, fuzzy narration Levenshtein matching, and weekend/holiday business day offset.
- **`05_layer4_groq_llm_exception_agent/`**: Ambiguous candidate resolver, multi-key failover rotation pool, and structured JSON audit reasoning.
- **`06_layer5_audit_reports_export/`**: Executive ReportLab PDF generator, Matplotlib visual chart buffer streaming, and period closing audit vault.

### 3. Tags & Reconciliation Taxonomy (`docs/03_tags_and_taxonomy/`)
- **`01_taxonomy_and_tags.txt`**: Comprehensive specification of all 10 taxonomy statuses and tags (SETTLED, MATCHED, SIMILAR, UNMATCHED, INTERNATIONAL, ROUND_OFF_VARIANCE, FEE_DEDUCTED, HIGH_CONFIDENCE, EXCEPTION, UNRECONCILED).

### 4. Architecture & Code Map (`docs/04_architecture/`)
- **`01_system_architecture_overview.txt`**: SPA Frontend, Flask RESTful API, Core Reconciliation Engine, Background Pipeline Tracker, and Report Engine.
- **`02_code_map_and_file_structure.txt`**: Subsystem file & function code map table, symmetric pair deduplication, and UI keyword comparison logic.

### 5. Scaling & Performance Challenges (`docs/05_scaling_challenges/`)
- **`01_scaling_and_performance_challenges.txt`**: Streaming 100k+ row imports, $O(N \cdot M)$ complexity mitigations, virtualized table DOM rendering, AI rate-limiting, and PostgreSQL migration path.

### 6. Deployment & Cloud Hosting (`docs/06_deployment/`)
- **`01_deployment_and_cloud_hosting.txt`**: Environment configuration, Docker multi-stage builds, Google Cloud Run / AWS ECS hosting, and persistent volume storage.

### 7. Technical Mechanics (`docs/07_technical_mechanics/`)
- **`01_virtualized_table_rendering.txt`**: DocumentFragment DOM batching & viewport pagination.
- **`02_two_pass_pdf_generation.txt`**: ReportLab two-pass NumberedCanvas & in-memory chart streaming.
- **`03_async_pipeline_tracking.txt`**: Non-blocking background thread worker & 300ms UI progress polling.

---

## Verification & Test Suite

Run the full pytest suite to validate system integrity:

```bash
PYTHONPATH=. ./.venv/bin/pytest -q
```
