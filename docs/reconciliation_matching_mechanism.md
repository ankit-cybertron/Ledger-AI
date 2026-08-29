# Ledger AI — Reconciliation & Matching Mechanism Specification

> **Canonical System Specification**  
> Detailed architecture, matching conditions, multi-pass algorithms, criteria, mathematical equations, configuration parameters, and settlement taxonomy for Ledger AI.

---

## 1. Executive Summary

**Ledger AI** is an automated financial reconciliation and transaction matching platform designed to ingest multi-source financial statements (Bank Statements, Payment Gateways like Razorpay/Stripe, Internal Order Books, Cash Books, and UPI feeds) across formats (CSV, XLSX, PDF).

The core engine uses a **Sequential 3-Pass Matching Cascade**, backed by a **12-Dimensional Machine Learning Confidence Model**, a **Gateway Fee & Settlement Equation Engine**, an **LLM Ambiguous Matching Agent (Google Gemini)**, and a **Four-Status Outcomes Taxonomy**.

---

## 2. End-to-End Reconciliation Pipeline Workflow

```
                               ┌────────────────────────────────┐
                               │     Raw Statement Ingestion    │
                               │   (Bank, Gateway, Orders, PDF) │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │   Normalization & Canonical    │
                               │     Transaction Adapter        │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │     PASS 1: Exact Matching     │
                               │   (Reference / UTR / Amount)   │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │    PASS 2: Tolerance Match     │
                               │   (Fuzzy Text + Amount/Date)   │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │    PASS 3: Split & Aggregate   │
                               │    (1-to-N, N-to-M Settlement)  │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │  ML Feature Vector Extraction  │
                               │   & Random Forest Evaluation   │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │      LLM Fallback Review       │
                               │  (Gemini Agent for 0.60-0.85)  │
                               └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │    Four-Status Outcome Taxonomy│
                               │ (SETTLED, MATCHED, SIMILAR,    │
                               │           UNMATCHED)           │
                               └────────────────────────────────┘
```

---

## 3. Multi-Pass Matching Engine Mechanics

### Pass 1: Exact Reference & UTR Matching (`matcher/exact_matcher.py`)

- **Objective**: Instantly pair records with 100% mathematical certainty.
- **Pre-Processing**: References are sanitized using normalized prefix stripping (`NEFTCR-`, `NEFT-`, `UPI-`, `UTR-`, `GPAY-`, `PAYTM-`, `RAZORPAY-`, `SETTLEMENT-`, `INB-`, `REF:`). Minimum identifier length requirement is 5 characters.
- **Criteria & Conditions**:
  1. **Identifier Match**: Normalized Reference ID / UTR / Bank Reference matches counterpart exactly (`exact_utr_confidence = 1.00`).
  2. **Amount Parity**: `abs(primary_amount - counterpart_amount) == 0.00`.
  3. **Date Window Guard**: `abs(primary_date - counterpart_date) <= date_tolerance_days` (Default: 3 days).
- **Assigned Taxonomy Status**: `SETTLED` or `MATCHED`.

---

### Pass 2: Tolerance & Fuzzy Text Matching (`matcher/tolerance_matcher.py`)

- **Objective**: Pair transactions containing typos, truncated reference strings, minor amount fees, or date offsets.
- **Criteria & Conditions**:
  1. **Fuzzy Reference & Narration Distance**: Evaluates text similarity using Levenshtein distance and Jaro-Winkler string comparison (`narration_similarity_threshold >= 0.50`).
  2. **Amount Tolerance**: `abs(primary_amount - counterpart_amount) <= absolute_amount_tolerance` (Default: `₹1.00`).
  3. **Date Offset**: Date difference evaluated against business day calendar offsets.

#### Multi-Factor Weighted Scoring Equation (`matcher/scoring_engine.py`)

Every candidate pair in Pass 2 is evaluated using the following composite scoring equation:

$$\text{Composite Score} = (w_{\text{id}} \cdot S_{\text{id}}) + (w_{\text{amt}} \cdot S_{\text{amt}}) + (w_{\text{date}} \cdot S_{\text{date}}) + (w_{\text{narr}} \cdot S_{\text{narr}})$$

| Component Factor | Weight ($w$) | Score Metric ($S$) |
|---|---|---|
| **Identifier Match ($S_{\text{id}}$)** | **0.40** | Normalized token overlap & substring alignment |
| **Amount Match ($S_{\text{amt}}$)** | **0.30** | $1.0 - \min\left(1.0, \frac{|A_1 - A_2|}{\text{tolerance}}\right)$ |
| **Date Delta ($S_{\text{date}}$)** | **0.15** | Exponential decay over days difference ($e^{-\lambda \cdot \Delta t}$) |
| **Narration Text ($S_{\text{narr}}$)** | **0.15** | Jaro-Winkler similarity on normalized description text |

- **Assigned Taxonomy Status**:
  - Score $\ge 0.85$: **`MATCHED`**
  - Score $0.50 \le \text{Score} < 0.85$: **`SIMILAR`** (Queued for ML/LLM review)

---

### Pass 3: Split & Aggregate Settlement Matching (`matcher/split_aggregate_matcher.py`)

- **Objective**: Solve complex 1-to-N (1 lump-sum Bank deposit = N order items), N-to-1, or N-to-M batch settlements.
- **Criteria & Conditions**:
  1. **Settlement Fee Equation (`matcher/settlement_equation.py`)**:
     $$\text{Net Bank Deposit} = \sum_{i=1}^{N} \text{Gross Order Amount}_i - \text{Total Gateway Fees} - \text{Taxes / GST}$$
  2. **Batch Clustering**: Groups transactions sharing settlement batch reference IDs, merchant batch codes, or matching execution timestamps.
  3. **Subset Sum Equation Solver**: Solves the bounded subset sum problem to identify exact item combinations matching payout amounts within tolerance (`split_match_confidence = 0.95`).
- **Assigned Taxonomy Status**: `SETTLED` or `MATCHED`.

---

## 4. Machine Learning & LLM Fallback Layer

### ML Feature Vector Schema (`ml/feature_schema.py`)

Candidate matches pass through a **12-dimensional feature extraction vector** evaluated by a trained **Random Forest Classifier** (`models/confidence_model.joblib`):

| Feature Name | Type | Description |
|---|---|---|
| `amount_diff_abs` | Float | Absolute amount difference ($|A_1 - A_2|$) |
| `amount_ratio` | Float | Ratio between primary and counterpart amounts |
| `ref_similarity_exact` | Binary | 1 if normalized reference matches, 0 otherwise |
| `ref_jaro_winkler` | Float | Jaro-Winkler string similarity score ($0.0 \rightarrow 1.0$) |
| `ref_levenshtein` | Float | Normalized Levenshtein edit distance |
| `date_diff_days` | Integer | Absolute calendar date difference |
| `is_business_day_offset` | Binary | 1 if offset is explained by weekend/bank holiday |
| `narration_similarity` | Float | Description text token similarity score |
| `fee_equation_matched` | Binary | 1 if fee equation holds for net payout |
| `source_type_pair` | Categorical | Encoded source pair (e.g. Bank vs Razorpay) |
| `payment_mode_match` | Binary | 1 if payment modes (UPI, NEFT, CC) align |
| `historical_user_approval` | Float | Historical approval rate for similar pattern |

### Decision Threshold Matrix

```
  0.0                      0.50            0.60            0.85                 1.0
  ├─────────────────────────┼───────────────┼───────────────┼────────────────────┤
  │   UNMATCHED Exception   │    SIMILAR    │  LLM Review   │  AUTO-APPROVED     │
  │   (Human Review Queue)  │ (Review Req)  │ (Gemini Agent)│  (MATCHED/SETTLED) │
  └─────────────────────────┴───────────────┴───────────────┴────────────────────┘
```

### LLM Fallback Agent (`llm/ambiguous_matcher.py`)

- **Trigger Window**: Confidence scores falling between **`0.60`** and **`0.85`**.
- **Model**: **Google Gemini API**.
- **Context Payload**: Transmits structured JSON payloads containing primary/counterpart records, raw descriptions, transaction modes, fee breakdowns, and dates.
- **Output Schema**:
  - `recommendation`: `"CONFIRMED"`, `"REJECTED"`, or `"MANUAL_REVIEW"`
  - `confidence_score`: Float between $0.0$ and $1.0$
  - `reasoning`: Natural language audit explanation

---

## 5. Four-Status Outcome Taxonomy

| Status | Code | Description | Qualification Criteria |
|---|---|---|---|
| **`SETTLED`** | `200_SETTLED` | Fully reconciled & payment finalized | Exact UTR + Amount match OR verified 1-to-N gateway batch payout. |
| **`MATCHED`** | `201_MATCHED` | Reconciled via engine/ML rules | High confidence ($\ge 0.85$) passing tolerance and scoring guards. |
| **`SIMILAR`** | `300_SIMILAR` | Potential candidate match identified | Moderate score ($0.50 - 0.84$), flagged for human/LLM review. |
| **`UNMATCHED`**| `400_UNMATCHED`| Discrepancy / Exception | Failed all reference, amount, date, and fee matching rules. |

---

## 6. Engine Configuration & Parameters (`config/matching_config.py`)

Below is the reference matrix of tunable parameters controlling the matching engine:

```python
date_tolerance_days = 3                     # Max calendar days delta
absolute_amount_tolerance = 1.00            # Max currency variance (₹)
narration_similarity_threshold = 0.50       # Minimum text similarity floor
ml_match_threshold = 0.80                   # ML auto-match score floor
llm_match_threshold = 0.70                  # LLM recommendation confidence floor
source_confidence_auto_accept = 0.85        # High-confidence threshold
exact_utr_confidence = 1.00                 # Exact match score
split_match_confidence = 0.95               # Split match score
scoring_weight_identifier = 0.40            # Identifier weight in scoring equation
scoring_weight_amount = 0.30                # Amount weight in scoring equation
scoring_weight_date = 0.15                  # Date weight in scoring equation
scoring_weight_narration = 0.15             # Narration weight in scoring equation
```

---

## 7. Audit & Integrity Verification

Following each reconciliation run, the engine executes a zero-loss integrity verification check:

$$\text{Total Input Records} = N_{\text{SETTLED}} + N_{\text{MATCHED}} + N_{\text{SIMILAR}} + N_{\text{UNMATCHED}}$$

- **Integrity Pass Condition**: 100% of input transaction records are accounted for in the four-status taxonomy without duplicates or unreferenced records.
