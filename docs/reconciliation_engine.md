# Ledger AI — Multi-Pass Reconciliation Engine & Deduplication Specification

> **Subsystem**: `reconciler/` & `frontend/api/routes.py`  
> **Core Purpose**: Multi-pass transaction reconciliation, primary pool separation, four-status taxonomy v2, Groq LLM integration, and symmetric mirror-pair deduplication.

---

## 1. Overview

The **Reconciliation Engine** coordinates multi-statement matching across uploaded financial datasets. It splits active statement sources into **Primary Ledgers** (`is_primary = True`) and **Counterpart Ledgers**, executes a sequential 6-stage matching cascade, and applies symmetric deduplication to ensure matched pairs render cleanly without duplicate listings.

---

## 2. Statement Pool Separation

Uploaded statement sources are split into two operational pools:

1. **Primary Pool (`is_primary = True`)**:
   - High-priority anchor ledgers (e.g. Bank Statements, Main Treasury Accounts).
   - Serves as the primary reference side for matching (`SETTLED` status).
2. **Counterpart Pool (`is_primary = False`)**:
   - Secondary operational ledgers (e.g. Gateway Settlement feeds, Internal Sales Registers, UPI feeds, Card Payment Reports, Cash Books).

---

## 3. Sequential 6-Pass Matching Cascade (`reconciler/pipeline_runner.py`)

```
  ┌──────────────────────────────────────────────────────────┐
  │     Primary Pool Records vs Counterpart Pool Records      │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 1: Exact Reference Matcher (`matcher/exact_matcher.py`)│
  │ Sanitized UTR / Order ID / Bill No Parity + Amount Match │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 2: Dynamic Tolerance Matcher (`matcher/tolerance_matcher.py`)│
  │ Composite Score >= 0.85 (Amount diff <= 1.00, Date <= 3d) │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 3: ML Confidence Engine (`ml/evaluate_confidence_model.py`)│
  │ 12-Dimensional Random Forest feature vector evaluation    │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 4: Reconciliation Aggregator (`reconciler/reconcile.py`)│
  │ Four-Status Taxonomy assignment: SETTLED / MATCHED /     │
  │ SIMILAR / UNMATCHED                                      │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 5: Exception Ledger (`exceptions/exception_ledger.py`)│
  │ Builds structured exception records for manual review    │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Step 6: Automated Report & QA Agent Reload               │
  │ Generates markdown audit reports & updates QA agent DB   │
  └──────────────────────────────────────────────────────────┘
```

---

## 4. Groq LLM Smart Matching & On-Demand Review

In accordance with Ledger AI safety rules, Groq LLM (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`) is invoked **on-demand** from the UI (e.g. "Smart AI Import", "Organize Table by AI", and candidate review modal `/api/transactions/llm-smart-match`) using multi-key failover (`GROQ_API_KEY`, `GROQ_API_KEY1`, `GROQ_API_KEY2`).

---

## 5. Symmetric Mirror-Pair Deduplication

In two-sided ledger reconciliation, a matched pair involving Record A and Record B can be represented in two directional views:
- `(Record A -> Record B)`
- `(Record B -> Record A)`

To prevent duplicate row entries in the UI dashboard table, `frontend/api/routes.py` applies symmetric pair deduplication in `_build_dashboard_run()`:

```python
seen_matched_ids = set()
for tx in all_reconciled_transactions:
    p_id = str(tx.get("primary_id"))
    c_id = str(tx.get("counterpart_id"))
    
    pair_key = (p_id, c_id)
    reverse_key = (c_id, p_id)
    
    if pair_key in seen_matched_ids or reverse_key in seen_matched_ids:
        continue
        
    seen_matched_ids.add(pair_key)
```

---

## 6. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `reconciler/pipeline_runner.py` | `run_full_pipeline()` | Master 6-step reconciliation orchestrator. |
| `reconciler/reconcile.py` | `reconcile()` | Core aggregator assigning SETTLED, MATCHED, SIMILAR, UNMATCHED. |
| `llm/query_llm.py` | `query_llm()`, `get_all_groq_keys()` | Central Groq LLM query handler with key rotation. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Performs mirror-pair deduplication (`seen_matched_ids`) and API output. |
| `config/matching_config.py` | `MatchingConfig` | Houses engine thresholds, tolerances, and scoring weights. |
--

## 4. Symmetric Mirror-Pair Deduplication

In two-sided ledger reconciliation, a matched pair involving Record A and Record B can be represented in two directional views:
- `(Record A -> Record B)`
- `(Record B -> Record A)`

To prevent duplicate row entries in the UI dashboard table, `frontend/api/routes.py` applies symmetric pair deduplication in `_build_dashboard_run()`:

```python
seen_matched_ids = set()
for tx in all_reconciled_transactions:
    p_id = str(tx.get("primary_id"))
    c_id = str(tx.get("counterpart_id"))
    
    pair_key = (p_id, c_id)
    reverse_key = (c_id, p_id)
    
    if pair_key in seen_matched_ids or reverse_key in seen_matched_ids:
        continue
        
    seen_matched_ids.add(pair_key)
    # Consolidated single row added to dashboard table
```

---

## 5. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `reconciler/reconcile.py` | `reconcile_all_statements()` | Main multi-statement reconciliation orchestrator. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Performs mirror-pair deduplication (`seen_matched_ids`) and API output. |
| `config/matching_config.py` | `MatchingConfig` | Houses engine thresholds, tolerances, and scoring weights. |
