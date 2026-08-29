# Ledger AI — Developer Guide to Transaction Matching & Status Classification

> **Developer Architectural Specification**  
> Comprehensive reference for developers detailing transaction status rules, multi-pass matching mechanics, file structures, deduplication algorithms, and side-by-side UI keyword comparison logic.

---

## 1. Overview & Core Philosophy

**Ledger AI** ingests multi-source financial statements (Bank Statements, Payment Gateways like Razorpay/Stripe, Internal Order Books, Cash Books, and UPI feeds) across formats (`CSV`, `XLSX`, `PDF`).

The system normalizes incoming records into standard `CanonicalTransaction` models and evaluates them through a multi-pass reconciliation engine. Based on mathematical certainty, fuzzy scoring, ML vector classification, and LLM reasoning, every transaction is categorized into one of four taxonomy statuses:

1. **`SETTLED`**: Fully reconciled and mathematically finalized payout/deposit.
2. **`MATCHED`**: Reconciled via high-confidence rule engine, ML score ($\ge 0.85$), or LLM recommendation.
3. **`SIMILAR`**: Potential candidate match identified ($0.50 \le \text{Score} < 0.85$) requiring developer/user review.
4. **`UNMATCHED`**: Discrepancy / exception failing all matching rules ($< 0.50$), routed to exception ledger.

---

## 2. File-by-File Architecture & Code Map

Below is the directory map of files responsible for statement ingestion, matching, deduplication, and UI comparison:

| Directory / File | Main Function / Class | Core Purpose & Logic |
|---|---|---|
| **`ingestion/normalizer.py`** | `normalize_row()`, `_generate_clean_fallback_tx_id()` | Converts raw mapped rows into `CanonicalTransaction`. Parses amounts, extracts UTR/Order IDs, and generates clean synthetic IDs (`BNK-TXN-0004`). |
| **`ingestion/column_mapper.py`** | `map_columns()` | 3-stage column mapping (exact alias lookup + fuzzy string distance fallback). |
| **`ingestion/dedupe.py`** | `detect_duplicates()` | Identifies identical intra-statement row uploads using SHA-256 content hashes. |
| **`reconciler/reconcile.py`** | `reconcile_all_statements()` | Main multi-statement reconciliation orchestrator. Divides statements into Primary vs. Counterpart pools and runs matching passes. |
| **`matcher/exact_matcher.py`** | `match_exact()` | Stage 1 Exact Matcher. Sanitizes UTR/reference strings and matches with 100% amount parity. |
| **`matcher/tolerance_matcher.py`** | `match_tolerance()` | Stage 2 Tolerance & Fuzzy Matcher. Computes multi-factor weighted scores ($\le ₹1.00$ variance, $\le 3$ day gap). |
| **`matcher/split_aggregate_matcher.py`**| `match_split_aggregate()` | Stage 3 Batch & Fee Solver. Solves 1-to-N batch deposits using net payout fee equations. |
| **`frontend/api/routes.py`** | `_build_dashboard_run()`, `/api/similar_payments` | API Data Layer. Performs symmetric pair deduplication (`seen_matched_ids`), assigns primary source badges, and fetches candidate matches. |
| **`frontend/statement_store.py`** | `_load_db()`, `rebuild_generated_csv()` | Local JSON store manager for uploaded statements and CSV generator. |
| **`ml/feedback_loop.py`** | `extract_features_for_pair()` | Builds 12-dimensional feature vectors for Random Forest evaluation. |
| **`llm/ambiguous_matcher.py`** | `run_llm_match()` | Gemini LLM Agent integration for ambiguous match resolution. |
| **`frontend/static/js/dashboard.js`** | `openRecordComparisonModal()`, `extractSharedKeywords()` | Frontend UI controller. Manages direct row clicks, side-by-side matrices, and description keyword extraction. |

---

## 3. Status Classification Rules & Criteria

### 1. `SETTLED` Status
- **Target Condition**: Complete ledger reconciliation between Bank and Counterpart/Gateway records.
- **Criteria**:
  - **Exact Reference Match**: Cleaned UTR, Settlement ID, or Bank Reference matches counterpart exactly.
  - **Zero Amount Variance**: `abs(primary_net_amount - counterpart_net_amount) == 0.00`.
  - **Or Fee Equation Verified**: 
    $$\text{Net Bank Deposit} = \sum_{i=1}^N \text{Gross Order Amount}_i - \text{Gateway Fees} - \text{GST/Tax}$$
- **Engine Assignment**: Executed in `matcher/exact_matcher.py` & `matcher/split_aggregate_matcher.py`.
- **UI Pill**: `<span class="status-pill status-settled">SETTLED</span>`

### 2. `MATCHED` Status
- **Target Condition**: High-confidence match under tolerance or verified via ML/LLM model.
- **Criteria**:
  - **Weighted Score Floor**: Composite Score $\ge 0.85$.
  - **Amount Variance**: Amount delta $\le ₹1.00$ (configurable in `config/matching_config.py`).
  - **Date Window**: Transaction date difference $\le 3$ calendar days.
  - **Or LLM Recommendation**: LLM Smart Match agent returned `CONFIRMED` recommendation with confidence $\ge 0.70$.
- **Engine Assignment**: Executed in `matcher/tolerance_matcher.py` & `llm/ambiguous_matcher.py`.
- **UI Pill**: `<span class="status-pill status-matched">MATCHED</span>`

### 3. `SIMILAR` Status
- **Target Condition**: Candidate pair identified with potential text or amount alignment, requiring user/developer review.
- **Criteria**:
  - **Score Range**: Composite Score between $0.50$ and $0.84$.
  - **Partial Overlap**: Shared customer name, card settlement token, or date/amount proximity without exact UTR match.
  - **Candidate Drawer**: Displayed in the side-by-side modal under **"Find Similar Payments"** (`/api/similar_payments`).
- **Engine Assignment**: Generated in `matcher/tolerance_matcher.py` & `frontend/api/routes.py`.
- **UI Pill**: `<span class="status-pill status-similar">SIMILAR</span>`

### 4. `UNMATCHED` Status (Exceptions)
- **Target Condition**: Discrepancy or orphaned record unable to be matched against any active statement pool.
- **Criteria**:
  - Composite Score $< 0.50$ across all candidate statements.
  - Missing counterpart record (e.g. uncollected deposit, failed gateway transfer, chargeback).
- **Engine Assignment**: Default status in `reconciler/reconcile.py` for unresolved records.
- **UI Pill**: `<span class="status-pill status-unmatched">UNMATCHED</span>`

---

## 4. Multi-Source Primary Prioritization & Mirror Pair Deduplication

In a two-sided reconciliation system, matching Record A (Bank Statement) to Record B (Internal Order Book) naturally creates two directional pairs:
1. `(Record A -> Record B)`
2. `(Record B -> Record A)`

To prevent duplicate row listings in the UI dashboard, `frontend/api/routes.py` applies the following logic in `_build_dashboard_run()`:

1. **Statement Priority Ordering**: Statements flagged as `is_primary=True` (e.g., Bank Statement) take precedence as the anchor/primary row.
2. **Symmetric Deduplication Set (`seen_matched_ids`)**:
   ```python
   seen_matched_ids = set()
   for tx in all_transactions:
       pair_key = (tx.primary_id, tx.counterpart_id)
       reverse_key = (tx.counterpart_id, tx.primary_id)
       if pair_key in seen_matched_ids or reverse_key in seen_matched_ids:
           continue
       seen_matched_ids.add(pair_key)
       # Include single consolidated row in dashboard table
   ```

---

## 5. Description & Keyword Similarity Extraction in UI

In `frontend/static/js/dashboard.js`, when a developer or user clicks any transaction row to open the side-by-side Comparison Modal (`openRecordComparisonModal`), the system dynamically extracts shared keywords between the two records:

```javascript
function extractSharedKeywords(str1, str2) {
  if (!str1 || !str2) return [];
  const STOP_WORDS = new Set(["the", "and", "for", "with", "ref", "txn", "card", "setl", "upi", "bank", "settlement", "payment", "inc", "ltd", "pvt", "corp", "org", "transfer", "neft", "rtgs", "imps", "from", "to", "via", "val", "date"]);
  const cleanTokens = (s) => String(s).toLowerCase().replace(/[^a-z0-9\s]/g, " ").split(/\s+/).filter(w => w.length >= 2 && !STOP_WORDS.has(w));
  
  const set1 = new Set(cleanTokens(str1));
  const set2 = cleanTokens(str2);
  const shared = new Set();
  set2.forEach(w => {
    if (set1.has(w)) shared.add(w.toUpperCase());
  });
  return Array.from(shared);
}
```

### Rendering in Parameter Match Matrix:
- **Shared Tokens Found**: Displays `<span class="status-pill status-exact">🔑 Shared Keywords: MEERA, IYER</span>`
- **Fuzzy Alignment**: Displays `<span class="status-pill">Fuzzy / Field Linked Match</span>`

---

## 6. Development Checklist for Modifying Matching Logic

When introducing new matching rules or statement types:
1. **Adding Column Aliases**: Update `config/column_aliases.json` under appropriate canonical key.
2. **Adding Reference Regex**: Add regex pattern to `config/normalization_rules.json` under `identifier_patterns`.
3. **Tuning Score Weights**: Adjust parameters in `config/matching_config.py`.
4. **Validating Pipeline**: Run the test suite:
   ```bash
   PYTHONPATH=. pytest --ignore=tests/test_pipeline.py
   ```
