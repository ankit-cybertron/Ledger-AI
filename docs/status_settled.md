# Ledger AI — Status Classification Specification: SETTLED

> **Taxonomy Status**: `200_SETTLED`  
> **Target Outcome**: Fully reconciled & mathematically verified payout/deposit across ledgers.

---

## 1. Overview & Definition

In Ledger AI, a transaction is classified as **`SETTLED`** when there is **100% mathematical certainty** that funds transferred between a primary bank account and a counterpart ledger (e.g. Gateway Settlement, Internal Order Book, UPI feed, or Cash Book) match completely with zero discrepancy.

---

## 2. High-Level Classification Algorithm

```
  ┌──────────────────────────────────────────────────────────┐
  │              Incoming Transaction Records                │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │   Pass 1: Exact Reference / UTR & Amount Parity Check    │
  │   - Sanitized UTR == Sanitized Counterpart UTR          │
  │   - Net Amount Difference == ₹0.00                       │
  │   - Date Window <= 3 Days                                │
  └────────────────────────────┬─────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               │ MATCHED                       │ NO MATCH
               ▼                               ▼
  ┌──────────────────────────┐   ┌───────────────────────────┐
  │ Assign SETTLED Status    │   │ Pass 3: Fee Equation Check│
  │ (Confidence = 1.00)      │   │ (Net = Gross - Fees - Tax)│
  └──────────────────────────┘   └─────────────┬─────────────┘
                                               │
                               ┌───────────────┴───────────────┐
                               │ VERIFIED                      │ FAILED
                               ▼                               ▼
                 ┌──────────────────────────┐    ┌──────────────────────────┐
                 │ Assign SETTLED Status    │    │ Proceed to Tolerance     │
                 │ (Confidence = 0.95)      │    │ Matching (MATCHED/SIMILAR│
                 └──────────────────────────┘    └──────────────────────────┘
```

---

## 3. Detailed Qualification Criteria

A transaction pair qualifies for **`SETTLED`** status if it satisfies **either** of the following two rules:

### Rule 1: Exact Identifier & Amount Parity
1. **Reference Sanitization**: Identifiers (UTRs, Bank Ref Numbers, Payment IDs) are stripped of prefix noises (`NEFTCR-`, `UPI-`, `RAZORPAY-`, `SETTLEMENT-`, `INB-`).
2. **Identifier Match**: `clean_utr_primary == clean_utr_counterpart` (minimum length: 5 characters).
3. **Zero Variance**: `abs(primary_net_amount - counterpart_net_amount) == 0.00`.
4. **Date Window Guard**: `abs(primary_date - counterpart_date) <= 3 calendar days`.

### Rule 2: Multi-Item Fee Equation Verification
For 1-to-N batch payouts (e.g., 1 Bank deposit matching N internal orders minus gateway charges):
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
