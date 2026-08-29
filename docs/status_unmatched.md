# Ledger AI — Status Classification Specification: UNMATCHED (Exceptions)

> **Taxonomy Status**: `400_UNMATCHED`  
> **Target Outcome**: Discrepancy or orphaned record requiring manual audit or LLM match intervention.

---

## 1. Overview & Definition

A transaction is assigned **`UNMATCHED`** status when it fails all exact, fuzzy tolerance, fee equation, and ML/LLM matching checks. These records represent true financial discrepancies (e.g. uncollected deposits, gateway failures, missing invoices, chargebacks) and are isolated into the **Exception Ledger**.

---

## 2. High-Level Classification Algorithm

```
  ┌──────────────────────────────────────────────────────────┐
  │                 Input Statement Records                  │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │        Sequential 3-Pass Reconciliation Engine          │
  │     Pass 1 (Exact) -> Pass 2 (Tolerance) -> Pass 3 (Fee) │
  └────────────────────────────┬─────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │ Candidate Match Found               │ No Candidate (Score < 0.50)
            ▼                                     ▼
  ┌───────────────────────────┐         ┌───────────────────────────┐
  │ Assign SETTLED / MATCHED  │         │ Assign UNMATCHED Status   │
  └───────────────────────────┘         │ Route to Exception Ledger │
                                        └─────────────┬─────────────┘
                                                      │
                                                      ▼
                                        ┌───────────────────────────┐
                                        │ Trigger LLM Match Button  │
                                        │ (Manual / AI Resolution)  │
                                        └───────────────────────────┘
```

---

## 3. Detailed Qualification Criteria

A transaction falls into **`UNMATCHED`** status under any of the following conditions:

1. **No Counterpart Record**: Transaction exists in the Bank Statement but has no corresponding record in Payment Gateway or Internal Order Book.
2. **Score Below Floor**: All evaluated candidate records score $< 0.50$ in the composite scoring equation.
3. **Amount Variance Exceeds Tolerance**: Amount delta exceeds allowable tolerance ($> ₹1.00$) without an explaining fee equation.
4. **Date Out of Window**: Transaction date gap exceeds maximum allowable window ($> 3$ calendar days).

---

## 4. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `reconciler/reconcile.py` | `reconcile_all_statements()` | Marks unresolved records as `UNMATCHED`. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Populates Exception Ledger table and exception count metrics. |
| `frontend/static/js/dashboard.js` | `renderExceptionsTable()`, `openRecordComparisonModal()` | Renders exception table and modal with empty counterpart state. |

---

## 5. User Interface Representation

- **Table Status Pill**: `<span class="status-pill status-unmatched">UNMATCHED</span>` (Rose Red)
- **Comparison Modal**: Renders primary record details on left, empty state container on right, and an active **"Run LLM Match"** action button in modal footer.
