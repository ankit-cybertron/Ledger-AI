# Ledger AI — Flexible Reconciliation & Smart Schema Upgrade Plan

## Purpose

This document is the implementation roadmap for upgrading Ledger AI from a fixed-schema reconciliation prototype into a flexible reconciliation engine that can work with different banks, gateways, payment channels, order books, cash books, and settlement formats.

The plan is intentionally broken into small, independently executable tasks. Each task is suitable to give to Antigravity one at a time.

The core principle is:

> **Normalize diverse financial files into a rich canonical transaction schema first. Then run reconciliation against the canonical schema.**

Do not rewrite the existing reconciliation engine unnecessarily. Extend it in controlled stages and preserve current behavior while adding flexibility.

---

# 0. Current Ledger Architecture

Current matching pipeline:

```text
Uploaded data
      ↓
Smart Schema Recognition
      ↓
Exact Matching
      ↓
Tolerance / Split Matching
      ↓
ML Confidence
      ↓
LLM Reasoning
      ↓
Exception Ledger
      ↓
Reconciliation Results
```

Current matching rules include:

### Stage 1 — Deterministic Exact Matching

- Order/sub-ledger amount match plus supporting evidence.
- Exact UTR + amount.
- Exact description/name + amount.
- Unique amount match.

### Stage 2 — Tolerance / Split Matching

- Multi-line settlement matching.
- 1-to-1 tolerance matching.
- Current date tolerance: 3 days.
- Current absolute amount tolerance: ₹1.
- Current narration similarity threshold: 0.50.
- Candidate ranking uses amount difference, date difference, and narration similarity.
- Current tie guard rejects equally ranked top candidates.

### Stage 3 — ML Confidence

- ML score >= 0.95 → automatic match.
- 0.50 <= score < 0.95 → LLM review.
- score < 0.50 → exception.

### Stage 4 — LLM

- `match` + confidence >= 0.70 → matched.
- Otherwise → exception/review.

Do not assume these thresholds are optimal. They are the current baseline and should remain configurable.

---

# 1. Target Architecture

The upgraded architecture should become:

```text
                  FILE INGESTION
                       │
                       ▼
              TABLE / FILE DETECTION
                       │
                       ▼
               SOURCE DETECTION
                       │
                       ▼
              COLUMN FIELD MAPPING
                       │
                       ▼
           SEMANTIC NORMALIZATION
                       │
                       ▼
          CANONICAL TRANSACTION SCHEMA
                       │
                       ▼
             DATA QUALITY ENGINE
                       │
                       ▼
             ELIGIBILITY FILTER
                       │
                       ▼
              CANDIDATE GENERATION
                       │
                       ▼
             DETERMINISTIC MATCHING
                       │
                       ▼
          FEE / TOLERANCE / SPLIT MATCH
                       │
                       ▼
               ML CONFIDENCE MODEL
                       │
                 ┌─────┴─────┐
                 │           │
              confident   ambiguous
                 │           │
                 │           ▼
                 │       LLM REASONING
                 │           │
                 └─────┬─────┘
                       ▼
                 FINAL DECISION
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
            MATCH    REVIEW   NO MATCH
                       │
                       ▼
                EXCEPTION LEDGER
```

---

# 2. Non-Negotiable Design Principles

1. Do not hardcode one merchant's column names.
2. Do not assume every file has UTR.
3. Do not assume every transaction has an explicit ID.
4. Do not discard useful source-specific fields.
5. Missing data must be represented as `null`, not guessed.
6. Do not force a match when evidence is insufficient.
7. Preserve the original uploaded values for auditability.
8. Preserve the normalized values separately from raw values.
9. Every automatic decision should have machine-readable evidence.
10. Every reconciliation run must record the configuration/thresholds used.
11. Existing generated datasets remain useful for regression tests, but production runs must accept arbitrary uploaded files.
12. The ML model must receive a stable feature schema regardless of source format.
13. The LLM should reason over structured evidence, not replace deterministic matching.
14. A safe `REVIEW` / `INSUFFICIENT_DATA` result is preferable to a false match.
15. Do not break currently working matching behavior while implementing the upgrade.

---

# 3. Phase 1 — Baseline and Regression Safety

## Task 1.1 — Inventory the Existing Backend

Before changing code, inspect:

```text
matcher/exact_matcher.py
matcher/tolerance_matcher.py
reconciler/reconcile.py
llm/ambiguous_matcher.py
statement_store.py
reconciler/exception_ledger.py
```

Also inspect any current data models, schemas, tests, and scripts used by the pipeline.

Deliverable:

```text
docs/backend_inventory.md
```

Document:

- functions
- inputs
- outputs
- current assumptions
- hardcoded paths
- current schemas
- current thresholds
- current dependencies between stages

Do not modify behavior in this task.

---

## Task 1.2 — Freeze Current Regression Baseline

Run the existing pipeline on the current known dataset.

Record:

- number of settlements
- number of matched records
- number of manual/review records
- number of unmatched records
- match rate
- exception count
- output file locations

Save a machine-readable baseline.

Suggested:

```text
tests/baseline/current_baseline.json
```

The purpose is to detect regressions after each upgrade.

---

## Task 1.3 — Add/Verify Stage-Level Tests

Create tests for the current exact/tolerance/ML/LLM decision boundaries.

At minimum test:

- exact UTR + amount
- exact description + amount
- unique amount
- split settlement
- tolerance match
- ambiguous top candidates
- low ML confidence
- high ML confidence
- LLM accepted match
- LLM rejection
- exception generation

Do not redesign matching yet.

---

# 4. Phase 2 — Canonical Transaction Schema

## Task 2.1 — Create Canonical Schema

Create a single internal transaction representation.

Recommended fields:

```text
transaction_id

source_type
channel

transaction_date
value_date
transaction_time
expected_settlement_date

gross_amount
debit_amount
credit_amount
fee_amount
tax_amount
net_amount
refund_amount
adjustment_amount

currency
direction

transaction_reference
utr
rrn
order_id
settlement_id
gateway_reference
auth_code

description
customer_name
vpa

status
transaction_type

account_identifier
```

Not every source needs every field.

Missing values must be `null`.

Do not fabricate missing information.

---

## Task 2.2 — Preserve Raw Data

Every canonical transaction should retain enough information to trace the normalized value back to the original file.

Recommended metadata:

```text
source_file
source_sheet
source_row_number
raw_record
normalization_warnings
```

The raw record is for audit/debugging and should not replace the canonical fields.

---

## Task 2.3 — Add Schema Versioning

Create a schema version:

```text
canonical_schema_version = "1.0"
```

Every normalized record should carry the version.

This is important because the ML feature schema and stored reconciliation results depend on the canonical representation.

---

# 5. Phase 3 — File and Table Recognition

## Task 3.1 — Robust File Reader

Create a unified file-reading layer.

Support:

```text
.csv
.xls
.xlsx
.pdf
```

The output of this layer should be a table-like structure.

Do not mix source classification or matching logic into the file reader.

---

## Task 3.2 — Excel Sheet Detection

For Excel:

- inspect all sheets
- ignore empty sheets
- identify likely transaction sheets
- detect header rows
- handle sheets with title/decorative rows above the header

Do not assume the first sheet is the transaction table.

---

## Task 3.3 — PDF Table Extraction

Implement PDF handling as a separate ingestion adapter.

Flow:

```text
PDF
 ↓
text/table extraction
 ↓
table candidate detection
 ↓
OCR fallback only where required
 ↓
normalized table
```

Do not send raw PDF text directly to matching.

---

# 6. Phase 4 — Source and Channel Detection

## Task 4.1 — Separate Source Type From Channel

Use two concepts.

### Source type

```text
bank_statement
payment_gateway
payment_subledger
order_book
cash_book
settlement_report
unknown
```

### Channel

```text
UPI
CARD
CASH
NEFT
IMPS
RTGS
BANK_TRANSFER
UNKNOWN
```

Example:

```text
source_type = payment_subledger
channel = UPI
```

Do not treat UPI/Card/Cash as completely separate incompatible schemas.

---

## Task 4.2 — Scored Source Detection

Instead of a simple keyword yes/no detector, calculate a source classification score.

Example output:

```json
{
  "bank_statement": 0.94,
  "payment_subledger": 0.02,
  "order_book": 0.03,
  "cash_book": 0.01
}
```

Recommended initial behavior:

```text
highest score >= 0.85
    → auto-classify

0.60 <= highest score < 0.85
    → request confirmation

highest score < 0.60
    → unknown / manual selection
```

These are starting configuration values, not permanent truths.

---

# 7. Phase 5 — Intelligent Column Mapping

## Task 5.1 — Expand Field Alias Dictionary

Create centralized mappings for common financial field variants.

Examples:

```text
amount:
Amount
Net Amount
Txn Amount
Transaction Amount
Credit (INR)
Amount (INR)

date:
Date
Txn Date
Transaction Date
Value Date
Created At
Settlement Date

reference:
UTR
UTR No
UTR Number
RRN
Ref No
Gateway Ref
Bank Ref No
Transaction Reference

description:
Description
Particulars
Narration
Remarks
VPA
Customer Name

order_id:
Order ID
Ord ID
Order No
Invoice No

settlement_id:
Settlement ID
Setl ID
Settlement Ref
Voucher No
```

Keep aliases in configuration/data rather than scattering them across code.

---

## Task 5.2 — Mapping Confidence

Every detected mapping should produce:

```text
canonical_field
source_column
mapping_method
confidence
```

Example:

```text
amount
source_column = "Amount (INR)"
method = exact_alias
confidence = 1.0
```

---

## Task 5.3 — Datatype-Aware Mapping

Use sample values to validate mappings.

Examples:

- date field should contain parseable dates
- amount field should be mostly numeric
- identifier field should contain stable strings
- description should not be mostly numeric
- balance should not automatically be treated as transaction amount

Reject suspicious mappings rather than silently accepting them.

---

## Task 5.4 — Mapping Review

If a critical field has low confidence, surface a user confirmation step.

Critical fields may include:

```text
date
amount / credit / debit
transaction reference
```

Do not require every optional field.

---

# 8. Phase 6 — Financial Semantics Normalization

## Task 6.1 — Normalize Amounts

Support:

```text
₹1,500.00
1,500.00
$1500
1500
```

Normalize into numeric values while preserving the original value.

Do not lose currency information.

---

## Task 6.2 — Normalize Credit/Debit

If separate columns exist:

```text
net_amount = credit - debit
```

Also preserve:

```text
credit_amount
debit_amount
direction
```

Do not throw away the original credit/debit information.

---

## Task 6.3 — Normalize Status

Map source-specific statuses into canonical states:

```text
SUCCESS
PENDING
FAILED
DECLINED
CAPTURED
REFUNDED
CANCELLED
ADJUSTMENT
UNKNOWN
```

Keep the original source status as well.

---

## Task 6.4 — Normalize Transaction Type

Create a canonical type where possible:

```text
PAYMENT
SETTLEMENT
REFUND
FEE
TAX
TRANSFER
WITHDRAWAL
DEPOSIT
ADJUSTMENT
CHARGEBACK
EXPENSE
UNKNOWN
```

Never infer a transaction type with high confidence from a weak signal.

---

## Task 6.5 — Normalize Dates

Preserve:

```text
transaction_date
value_date
settlement_date
expected_settlement_date
```

Do not collapse all dates into one date.

---

# 9. Phase 7 — Data Quality Engine

## Task 7.1 — Transaction Quality Report

Before matching, generate:

```text
rows_detected
valid_rows
ignored_rows
missing_amount_count
missing_date_count
missing_reference_count
invalid_date_count
invalid_amount_count
duplicate_count
schema_confidence
source_confidence
warnings
```

---

## Task 7.2 — Duplicate Detection

Detect:

### Exact duplicates

Same transaction/reference ID.

### Probable duplicates

Same:

```text
amount
date
reference
description
```

Use a risk score rather than automatically deleting records.

---

## Task 7.3 — Required Field Validation

Required fields should depend on source type.

Example:

### Bank

Usually requires:

```text
date
amount or credit/debit
```

### Order book

Usually requires:

```text
order_id
amount
date/status
```

### UPI

Usually benefits from:

```text
transaction_id
amount
status
```

Do not make UTR mandatory for every source.

---

# 10. Phase 8 — Eligibility Engine

Before matching, determine whether a transaction is eligible for a specific reconciliation relationship.

Examples:

```text
FAILED payment
    → should not match successful settlement

DECLINED card
    → should not match captured payment

REFUNDED payment
    → may require refund relationship

DEBIT transaction
    → should not normally match settlement CREDIT
```

Create:

```text
eligibility_status
eligibility_reasons
```

This prevents bad candidates from reaching the ML model.

---

# 11. Phase 9 — Candidate Generation

Do not compare every transaction against every other transaction.

Generate plausible candidates using blocking keys.

Possible blocks:

```text
normalized UTR
RRN
gateway reference
order ID
settlement ID
auth code
date window
amount window
customer name
VPA
```

Candidate generation should be broad enough not to miss valid matches, but narrow enough to avoid huge candidate sets.

---

# 12. Phase 10 — Deterministic Matching v2

Keep existing rules but expand identifiers.

Priority:

```text
1. Exact strong reference + amount
2. Exact order/settlement/gateway reference
3. Exact reference + compatible date
4. Exact amount + compatible date + unique candidate
5. Other deterministic combinations
```

Hard guards:

```text
currency compatible
direction compatible
status compatible
candidate_count appropriate
```

Do not force a match.

---

# 13. Phase 11 — Fee-Aware Matching

Replace the idea of one global ₹1 tolerance with configurable financial rules.

Concept:

```text
expected_net =
gross_amount
- fee_amount
- tax_amount
- refund_amount
+ adjustment_amount
```

Then:

```text
expected_net vs actual settlement/bank credit
```

Support both:

```text
absolute tolerance
percentage tolerance
```

and source/merchant-specific fee rules.

Do not automatically assume a 2% fee unless the data/configuration supports it.

---

# 14. Phase 12 — Split and Aggregate Matching

Support:

```text
1 settlement → many bank lines
many settlements → 1 bank line
```

Potentially:

```text
1 → 1
1 → N
N → 1
N → N
```

Start with 1→N and N→1.

Do not implement unrestricted N→N matching until strong constraints and tests exist.

---

# 15. Phase 13 — Better Similarity Features

Instead of one global narration similarity, calculate separate features:

```text
description_similarity
customer_name_similarity
utr_similarity
rrn_similarity
vpa_similarity
order_id_similarity
gateway_reference_similarity
```

Also calculate:

```text
amount_difference
relative_amount_difference
date_difference
```

Do not make one similarity score responsible for the entire decision.

---

# 16. Phase 14 — ML Feature Schema

Create a stable model input schema.

Recommended features:

```text
amount_difference
relative_amount_difference
date_difference

utr_exact
utr_similarity

rrn_exact
rrn_similarity

order_id_exact
settlement_id_exact
gateway_reference_exact
auth_code_exact

description_similarity
customer_name_similarity
vpa_similarity

same_direction
same_currency
status_compatible

candidate_count

split_candidate

fee_adjusted_difference

expected_settlement_date_gap

duplicate_risk
```

Categorical fields such as source type/channel should be encoded consistently.

The model must receive the same feature names and meanings regardless of the uploaded file format.

---

# 17. Phase 15 — ML Confidence Decision

Do not use the ML score alone.

Use:

```text
ML score
+
hard guards
+
best-vs-second-best margin
```

Calculate:

```text
best_score
second_best_score
score_margin
```

Recommended conceptual behavior:

```text
hard guards fail
    → reject candidate

high score + sufficient margin
    → automatic match

medium score OR small margin
    → review / LLM

low score
    → exception
```

Keep current thresholds as configuration until enough labeled data exists.

---

# 18. Phase 16 — LLM Reasoning

The LLM should receive structured evidence.

Example:

```json
{
  "settlement": {...},
  "candidate": {...},
  "features": {
    "amount_difference": 0.0,
    "date_difference": 1,
    "utr_exact": true,
    "description_similarity": 0.82,
    "candidate_count": 2
  }
}
```

The LLM should return structured output:

```text
decision
confidence
reason
evidence
```

Valid decisions:

```text
MATCH
REVIEW
NO_MATCH
INSUFFICIENT_DATA
```

Do not let the LLM invent missing transaction facts.

---

# 19. Phase 17 — Exception Ledger Upgrade

Every unresolved decision should record:

```text
exception_id
run_id
settlement_id
bank_transaction_id
stage
decision
confidence
exception_type
priority
reason
resolution_status

best_candidate_score
second_best_candidate_score
score_margin

evidence
configuration_version
```

This will make the dashboard and Talk to Ledger much more useful.

---

# 20. Phase 18 — Reconciliation Run Model

Production uploads must not overwrite the generated test files.

Create a run concept:

```text
run_id
created_at
source_files
source_types
schema_version
matching_config_version
status
results_location
exception_location
```

Example:

```text
/uploads/<run_id>/bank.xlsx
/uploads/<run_id>/razorpay.xlsx
/uploads/<run_id>/orders.xlsx
```

Results:

```text
/results/<run_id>/reconciliation_results.csv
/results/<run_id>/exception_ledger.csv
```

This makes every reconciliation run isolated and reproducible.

---

# 21. Phase 19 — Configuration Registry

Centralize parameters.

Example:

```json
{
  "date_tolerance_days": 3,
  "absolute_amount_tolerance": 1.0,
  "percentage_amount_tolerance": null,
  "narration_similarity_threshold": 0.50,
  "ml_match_threshold": 0.95,
  "ml_review_threshold": 0.50,
  "llm_match_threshold": 0.70,
  "allow_split_matches": true,
  "allow_aggregate_matches": true
}
```

Every run must store the configuration used.

Do not scatter magic numbers throughout the code.

---

# 22. Phase 20 — Training Dataset Upgrade

The ML training dataset should be generated from canonical records.

Each candidate pair should contain:

```text
candidate features
ground_truth_label
source_type
channel
decision_stage
```

Labels:

```text
1 = true match
0 = true non-match
```

Potential future label:

```text
2 = insufficient evidence / ambiguous
```

Do not train on LLM decisions as ground truth without human/known-ground-truth validation.

---

# 23. Phase 21 — Model Evaluation

Track more than overall accuracy.

Required metrics:

```text
precision
recall
F1
false positive rate
false negative rate
```

For financial matching, pay special attention to:

> **False positives**

A wrong automatic match can be more damaging than leaving a transaction for manual review.

Also report metrics by:

```text
source_type
channel
matching stage
transaction type
amount range
candidate count
```

---

# 24. Phase 22 — Threshold Calibration

Once enough labeled examples exist, evaluate:

```text
ML threshold
review threshold
LLM threshold
score margin threshold
date tolerance
amount tolerance
```

Do not assume:

```text
0.95
0.50
0.70
```

are universally optimal.

Use validation data to select thresholds that provide an appropriate precision/recall tradeoff.

---

# 25. Phase 23 — Explainability Output

Every match should be explainable.

Example:

```text
MATCHED
Confidence: 98.7%

Resolved by:
Tolerance Matcher

Evidence:
✓ UTR matched
✓ Amount difference: ₹0.00
✓ Date difference: 1 day
✓ Candidate count: 1
```

ML:

```text
MATCHED
Confidence: 96.4%

Resolved by:
ML Confidence Model

Evidence:
Amount difference: ₹0.50
Date difference: 1 day
Narration similarity: 0.81
Candidate count: 2
Score margin: 0.23
```

Exception:

```text
REVIEW REQUIRED

Reason:
Two candidates have nearly identical evidence.

Ledger did not automatically choose.
```

---

# 26. Phase 24 — Event-Level Reconciliation

This is a later-stage enhancement.

Instead of only matching rows, represent the financial event:

```text
Order
  ↓
Payment
  ↓
Gateway
  ↓
Fee
  ↓
Settlement
  ↓
Bank
```

Then determine whether the entire event reconciles.

Example:

```text
Order       ₹1,000 ✓
Payment     ₹1,000 ✓
Fee            ₹20 ✓
Settlement    ₹980 ✓
Bank          ₹980 ✓

FINANCIAL EVENT RECONCILED
```

Do this only after the canonical transaction and matching layers are stable.

---

# 27. Phase 25 — Backend/API Integration

The Flask API should call the upgraded backend engine.

Conceptual flow:

```text
Frontend
   ↓
Flask
   ↓
Create reconciliation run
   ↓
Upload files
   ↓
Schema recognition
   ↓
Canonicalization
   ↓
Validation
   ↓
Reconciliation engine
   ↓
Results
   ↓
Flask JSON API
   ↓
Dashboard
```

The frontend must not contain reconciliation logic.

---

# 28. Recommended API Surface

Initial API:

```text
POST /api/runs
POST /api/runs/<run_id>/upload/bank
POST /api/runs/<run_id>/upload/razorpay
POST /api/runs/<run_id>/upload/orders

GET  /api/runs/<run_id>/status

POST /api/runs/<run_id>/reconcile

GET  /api/runs/<run_id>/summary
GET  /api/runs/<run_id>/results
GET  /api/runs/<run_id>/exceptions

GET  /api/runs/<run_id>/results/<transaction_id>
GET  /api/runs/<run_id>/exceptions/<exception_id>
```

Keep the API layer separate from the reconciliation implementation.

---

# 29. Phase 26 — Testing With the Five Realistic Input Types

Use the provided test files:

```text
01_bank_statement.xlsx
02_internal_order_book.xlsx
03_upi_payment.xlsx
04_card_payment.xlsx
05_cash_book.xlsx
```

These should become schema-ingestion test fixtures.

Test that Ledger can identify:

```text
Bank Statement
Order Book
UPI
Card
Cash Book
```

and normalize them into the same canonical schema.

Then test cross-source matching.

---

# 30. Phase 27 — New Unseen Data Test

After implementation, create or obtain a dataset with:

- different column names
- different date formats
- different descriptions
- different identifier names
- different transaction statuses
- different fee structures
- different number of rows

The system must process it without modifying the matching code specifically for that dataset.

This is the real test of flexibility.

---

# 31. Suggested Antigravity Execution Order

Give Antigravity tasks in this exact order:

```text
01. Backend inventory
02. Regression baseline
03. Stage-level tests
04. Canonical schema
05. Raw-record preservation
06. Schema versioning
07. Unified file reader
08. Excel sheet/table detection
09. PDF ingestion
10. Source-type scoring
11. Channel detection
12. Alias registry
13. Column mapping confidence
14. Datatype-aware mapping
15. Financial amount normalization
16. Credit/debit normalization
17. Status normalization
18. Transaction-type normalization
19. Date normalization
20. Data-quality report
21. Duplicate detection
22. Eligibility engine
23. Candidate generation
24. Deterministic matcher v2
25. Fee-aware matching
26. Split matching
27. Aggregate matching
28. Similarity feature expansion
29. Stable ML feature schema
30. Candidate score margin
31. ML decision engine
32. Structured LLM evidence
33. LLM structured decision
34. Exception Ledger upgrade
35. Run/session model
36. Configuration registry
37. Training dataset generator
38. Model evaluation
39. Threshold calibration
40. Explainability output
41. Five-file integration tests
42. New unseen dataset test
43. Flask API integration
44. Dashboard integration
45. End-to-end test
```

---

# 32. Rules for Every Antigravity Task

For every task, tell Antigravity:

1. Inspect existing code before editing.
2. Do not rewrite unrelated files.
3. Preserve current working behavior.
4. Make the smallest safe change.
5. Add or update tests.
6. Run relevant tests.
7. Report exactly which files changed.
8. Report what was tested.
9. Do not invent missing data.
10. Do not silently change thresholds.
11. Do not remove existing functionality unless explicitly requested.
12. If an architectural conflict is discovered, stop and explain it before making a large rewrite.

---

# 33. Definition of Done

The upgrade is complete when:

### Input flexibility

Ledger can accept different:

```text
CSV
XLS
XLSX
PDF
```

formats and identify the relevant transaction table.

### Schema flexibility

Different column names map into the canonical schema with confidence.

### Semantic flexibility

Ledger understands:

```text
UPI
CARD
CASH
BANK
ORDER
SETTLEMENT
REFUND
FEE
```

without requiring source-specific matching code for every file.

### Matching flexibility

Ledger supports:

```text
exact
tolerance
fee-aware
split
aggregate
ML
LLM
```

matching.

### Safety

Ledger can say:

```text
MATCH
REVIEW
NO_MATCH
INSUFFICIENT_DATA
```

and does not force uncertain matches.

### Explainability

Every decision has machine-readable evidence.

### Reproducibility

Every reconciliation run records:

```text
input files
schema version
matching configuration
model version
results
exceptions
```

### Production behavior

A completely new dataset can be uploaded and processed without editing the reconciliation code for that dataset.

---

# 34. Final Product Philosophy

Ledger AI should not be:

> "A system that compares two CSV files."

It should be:

> **"A financial reconciliation engine that understands different financial records, converts them into a common representation, determines whether they describe the same financial event, and explains anything it cannot confidently reconcile."**

The strongest part of Ledger is not a single matching rule.

It is the combination of:

```text
Flexible ingestion
+
Canonical financial representation
+
Deterministic rules
+
Financial reconciliation logic
+
ML confidence
+
LLM reasoning
+
Safe abstention
+
Explainability
```

Build those layers independently and keep the interfaces between them stable.
