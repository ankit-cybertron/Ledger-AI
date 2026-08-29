# Ledger AI — Status Classification Specification: MATCHED

> **Taxonomy Status**: `201_MATCHED`  
> **Target Outcome**: High-confidence matched transaction pair via rule scoring, ML classifier, or LLM confirmation.

---

## 1. Overview & Definition

A transaction is categorized as **`MATCHED`** when it successfully pairs with a counterpart record under predefined tolerance parameters or high ML/LLM confidence, even if minor text typos, rounding variances ($\le ₹1.00$), or date offsets ($\le 3$ days) exist.

---

## 2. High-Level Classification Algorithm

```
  ┌──────────────────────────────────────────────────────────┐
  │     Records Unmatched in Pass 1 (Exact Matcher)          │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │         Pass 2: Composite Weighted Score Evaluation       │
  │  Score = 0.40(ID) + 0.30(Amt) + 0.15(Date) + 0.15(Narr)   │
  └────────────────────────────┬─────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │ Score >= 0.85                       │ Score < 0.85
            ▼                                     ▼
  ┌───────────────────────────┐         ┌───────────────────────────┐
  │ Assign MATCHED Status     │         │ Evaluate ML / LLM Window  │
  │ (Rule Confidence >= 0.85) │         │ (Confidence 0.60 - 0.85)  │
  └───────────────────────────┘         └─────────────┬─────────────┘
                                                      │
                                      ┌───────────────┴───────────────┐
                                      │ LLM CONFIRMED                 │ LLM REJECTED / LOW SCORE
                                      ▼                               ▼
                        ┌──────────────────────────┐    ┌──────────────────────────┐
                        │ Assign MATCHED Status    │    │ Proceed to SIMILAR or    │
                        │ (LLM Confidence >= 0.70) │    │ UNMATCHED Exceptions     │
                        └──────────────────────────┘    └──────────────────────────┘
```

---

## 3. Composite Weighted Scoring Equation

Candidate pairs are evaluated using the composite scoring equation in `matcher/scoring_engine.py`:

$$\text{Composite Score} = (0.40 \cdot S_{\text{id}}) + (0.30 \cdot S_{\text{amt}}) + (0.15 \cdot S_{\text{date}}) + (0.15 \cdot S_{\text{narr}})$$

| Component Factor | Weight | Score Calculation Metric |
|---|---|---|
| **Identifier Similarity ($S_{\text{id}}$)** | **0.40** | Jaro-Winkler & Levenshtein distance on reference tokens. |
| **Amount Variance ($S_{\text{amt}}$)** | **0.30** | $1.0 - \min\left(1.0, \frac{|A_1 - A_2|}{\text{tolerance}}\right)$ (Tolerance = $₹1.00$). |
| **Date Proximity ($S_{\text{date}}$)** | **0.15** | Decay function: $1.0$ for same day, $0.8$ for 1 day, $0.5$ for 2–3 days. |
| **Narration Overlap ($S_{\text{narr}}$)** | **0.15** | Token overlap ratio on cleaned description strings. |

---

## 4. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `matcher/tolerance_matcher.py` | `match_tolerance()` | Runs Stage 2 tolerance matching across candidate statements. |
| `matcher/scoring_engine.py` | `calculate_pair_score()` | Implements the 4-factor composite weighted score equation. |
| `ml/feedback_loop.py` | `predict_match_confidence()` | Evaluates 12-dimensional ML feature vector using Random Forest. |
| `llm/ambiguous_matcher.py` | `run_llm_match()` | Gemini LLM Agent recommendation for ambiguous score pairs. |
| `frontend/api/routes.py` | `_build_dashboard_run()` | Deduplicates matched pairs and builds `MATCHED` table rows. |

---

## 5. User Interface Representation

- **Table Status Pill**: `<span class="status-pill status-matched">MATCHED</span>` (Blue / Vibrant Cyan)
- **Comparison Modal**: Displays match score percentage (e.g. `92% Match Confidence`), source badges, and parameter variance breakdown.
