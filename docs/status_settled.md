# Ledger AI — Status Classification Specification: SETTLED

> **Taxonomy Status**: `200_SETTLED`  
> **Primary Rule**: High-confidence matched pair involving at least one primary statement record (`is_primary=True`).

---

## 1. Overview & Definition

In Ledger AI, a transaction outcome is classified as **`SETTLED`** when a valid match is established between statement records where **at least one side of the match belongs to a designated Primary Statement source** (e.g. Bank Account feed, Master Cash Book).

While `MATCHED` status represents reconciliation between two counterpart sources (e.g. Gateway vs Order Book), **`SETTLED`** represents canonical settlement of primary bank/cash balances against counterpart channels.

---

## 2. Decision Tree Architecture

```
                       ┌────────────────────────────────┐
                       │   Matched Candidate Pair       │
                       │   (Confidence Score >= 0.85    │
                       │   or Exact/Tolerance Match)    │
                       └───────────────┬────────────────┘
                                       │
                                       ▼
                       ┌────────────────────────────────┐
                       │   Is either record from a      │
                       │   Primary Statement source?    │
                       │     (is_primary == True)       │
                       └───────┬────────────────┬───────┘
                               │                │
                      YES      │                │  NO (Counterpart only)
                               ▼                ▼
                     ┌──────────────────┐  ┌──────────────────┐
                     │ Status: SETTLED  │  │ Status: MATCHED  │
                     └──────────────────┘  └──────────────────┘
```

---

## 3. Qualification & Rule Specifications

A candidate pair qualifies for **`SETTLED`** status if:
1. **Match Validity**: The pair passes Pass 1 (Exact UTR/Amount Parity), Pass 2 (Tolerance / MDR Fee Equation Match), or Pass 3 (Split / Batch Aggregate Match) with confidence $\ge 0.85$.
2. **Primary Pool Membership**: `primary_statement_id` is associated with an active statement where `is_primary=True` (or `is_primary` flag is enabled).

---

## 4. Key Code Reference

- **Rule Implementation**: `reconciler/reconcile.py` — `# SETTLED vs MATCHED Rule: If either side belongs to an is_primary statement -> SETTLED; else (both counterpart) -> MATCHED.`
- **Configuration & Tolerances**: `config/matching_config.py`
- **Fee Breakdown**: `matcher/settlement_equation.py`
 (e.g., 1 Bank deposit matching N internal orders minus gateway charges):
$$\text{Net Bank Deposit} = \sum_{i=1}^N \text{Gross Order Amount}_i - \text{Gateway Fees} - \text{Taxes / GST}$$
- **Solver Engine**: Solves the bounded subset sum equation to verify batch total matches deposit amount.

---

## 4. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `matcher/exact_matcher.py` | `match_exact()` | Executes Stage 1 exact UTR and zero-variance amount matching. |
| `matcher/split_aggregate_matcher.py` | `match_split_aggregate()` | Solves 1-to-N batch payouts using the fee equation. |
| `reconciler/reconcile.py` | `reconcile_all_statements()` | Assigns `SETTLED` status to verified primary/counterpart pairs. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Formats `SETTLED` rows for table rendering and summary counters. |

---

## 5. User Interface Representation

- **Table Status Pill**: `<span class="status-pill status-settled">SETTLED</span>` (Emerald Green)
- **Comparison Modal**: Displays **Exact Reference Match**, **Exact Reconciled Amount**, and 100% Match Confidence.
