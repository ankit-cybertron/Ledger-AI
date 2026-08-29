# Ledger AI — Multi-Pass Reconciliation Engine & Deduplication Specification

> **Subsystem**: `reconciler/` & `frontend/api/routes.py`  
> **Core Purpose**: Multi-pass transaction reconciliation, primary pool separation, and symmetric mirror-pair deduplication.

---

## 1. Overview

The **Reconciliation Engine** coordinates multi-statement matching across uploaded financial datasets. It splits active statement sources into **Primary Ledgers** and **Counterpart Ledgers**, executes a sequential 3-pass matching cascade, and applies symmetric deduplication to ensure matched pairs render cleanly without duplicate listings.

---

## 2. Statement Pool Separation

Uploaded statement sources are split into two operational pools:

1. **Primary Pool (`is_primary = True`)**:
   - High-priority anchor ledgers (e.g. Bank Statements, Main Treasury Accounts).
   - Serves as the primary reference side for matching.
2. **Counterpart Pool (`is_primary = False`)**:
   - Secondary operational ledgers (e.g. Gateway Settlement feeds, Internal Order Books, UPI feeds, Cash Books).

---

## 3. Sequential 3-Pass Matching Cascade

```
  ┌──────────────────────────────────────────────────────────┐
  │     Primary Pool Records vs Counterpart Pool Records      │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Pass 1: Exact Reference & Amount Parity Matcher          │
  │ Sanitized UTR Match + Amount Diff = ₹0.00 + Date <= 3 Days│
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Pass 2: Tolerance & Fuzzy Text Scoring Matcher           │
  │ Weighted Composite Score = 0.40(ID) + 0.30(Amt) + ...     │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Pass 3: Split & Aggregate Fee Equation Solver            │
  │ Solves 1-to-N batch payout fee equations                 │
  └────────────────────────────┬─────────────────────────────┘
                               │ (Unresolved Records)
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Exception Ledger (UNMATCHED Status)                      │
  │ Queued for ML Classification or Gemini LLM Match        │
  └──────────────────────────────────────────────────────────┘
```

---

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
