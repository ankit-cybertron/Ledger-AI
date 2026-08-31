# Ledger AI — Status Classification Specification: MATCHED

> **Taxonomy Status**: `201_MATCHED`  
> **Primary Rule**: High-confidence matched pair between counterpart statement records (neither side is primary).

---

## 1. Overview & Definition

In Ledger AI, a transaction outcome is categorized as **`MATCHED`** when a valid match is established between **two counterpart statement records** (e.g. Gateway Settlement feed vs Internal Order Book, or Payment Gateway vs UPI log), where **neither record belongs to a Primary Statement source**.

If one or both records in the matched pair belong to a Primary Statement (e.g. Bank Account feed), the status is canonically classified as **`SETTLED`**.

---

## 2. Decision Architecture & Pool Rule

```
                       ┌────────────────────────────────┐
                       │   Matched Candidate Pair       │
                       │   (Confidence Score >= 0.85    │
                       │   or Exact/Tolerance Match)    │
                       └───────────────┬────────────────┘
                                       │
                                       ▼
                       ┌────────────────────────────────┐
                       │   Are BOTH records from        │
                       │   Counterpart Statement feeds? │
                       │    (is_primary == False)       │
                       └───────┬────────────────┬───────┘
                               │                │
                      YES      │                │  NO (Primary involved)
                               ▼                ▼
                     ┌──────────────────┐  ┌──────────────────┐
                     │ Status: MATCHED  │  │ Status: SETTLED  │
                     └──────────────────┘  └──────────────────┘
```

---

## 3. Composite Weighted Scoring Equation

Candidate pairs are evaluated using the composite scoring equation in `matcher/scoring_engine.py`:

$$\text{Composite Score} = (0.40 \cdot S_{\text{id}}) + (0.30 \cdot S_{\text{amt}}) + (0.15 \cdot S_{\text{date}}) + (0.15 \cdot S_{\text{narr}})$$

| Component Factor | Weight | Score Calculation Metric |
|---|---|---|
| **Identifier Similarity ($S_{\text{id}}$)** | **0.40** | Jaro-Winkler & Levenshtein distance on reference tokens. |
| **Amount Variance ($S_{\text{amt}}$)** | **0.30** | $1.0 - \min\left(1.0, \frac{|A_1 - A_2|}{\text{tolerance}}\right)$ (Tolerance = $₹1.00$ or channel MDR rate). |
| **Date Proximity ($S_{\text{date}}$)** | **0.15** | Decay function: $1.0$ for same day, $0.8$ for 1 day, $0.5$ for 2–3 days. |
| **Narration Overlap ($S_{\text{narr}}$)** | **0.15** | Token overlap ratio on cleaned description strings. |

---

## 4. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `matcher/tolerance_matcher.py` | `match_tolerance()` | Runs Stage 2 tolerance matching across candidate statements. |
| `matcher/scoring_engine.py` | `calculate_pair_score()` | Implements the 4-factor composite weighted score equation. |
| `reconciler/reconcile.py` | `reconcile()` | Applies the Primary vs Counterpart rule to set `SETTLED` or `MATCHED`. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Deduplicates matched pairs and builds `MATCHED` table rows. |

