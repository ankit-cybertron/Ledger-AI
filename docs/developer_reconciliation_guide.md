# Ledger AI — Developer Guide to Transaction Matching & Technical Architecture

> **Developer Architectural Specification**  
> Comprehensive technical reference for developers detailing transaction status rules, multi-pass matching mechanics, file structures, deduplication algorithms, unified master table views, beginning balance state propagation, PDF report generation, and side-by-side UI keyword comparison logic.

---

## 1. Overview & Core Philosophy

**Ledger AI** ingests multi-source financial statements (Bank Statements, Payment Gateways like Razorpay/Stripe, Internal Order Books, Cash Books, and UPI feeds) across formats (`CSV`, `XLSX`, `PDF`).

The system normalizes incoming records into standard `CanonicalTransaction` models and evaluates them through a multi-pass reconciliation engine. Based on mathematical certainty, fuzzy scoring, 12-dimensional ML vector classification, and Groq LLM reasoning, every transaction is categorized into one of four taxonomy statuses:

1. **`SETTLED`**: Primary statement record (Bank/Cash) reconciled against counterpart payouts or 1-to-N batch deposits.
2. **`MATCHED`**: Reconciled between two counterpart sources (e.g. Gateway vs Order Book) via high-confidence rule engine, ML score ($\ge 0.85$), or LLM recommendation.
3. **`SIMILAR`**: Potential candidate match identified ($0.50 \le \text{Score} < 0.85$) surfacing in candidate drawer for user/LLM review.
4. **`UNMATCHED`**: Financial discrepancy failing all matching rules ($< 0.50$), routed to the Exception Ledger.

---

## 2. File-by-File Architecture & Code Map

Below is the complete directory map of implemented files across ingestion, reconciliation, forecasting, reporting, API endpoints, and UI controllers:

| Subsystem / File | Main Functions / Classes | Implementation Purpose & Logic |
|---|---|---|
| **`ingestion/normalizer.py`** | `normalize_row()`, `_generate_clean_fallback_tx_id()` | Converts raw mapped rows into `CanonicalTransaction`. Parses locale amounts, extracts UTR/Order IDs, and generates clean synthetic IDs (`BNK-TXN-0004`). |
| **`ingestion/column_mapper.py`** | `map_columns()` | 3-stage column mapping (exact alias lookup + fuzzy distance fallback + Groq AI header alignment). |
| **`ingestion/dedupe.py`** | `detect_duplicates()` | Computes SHA-256 content hashes to detect intra-statement duplicate row uploads. |
| **`reconciler/pipeline_runner.py`** | `run_full_pipeline()` | Master 6-step reconciliation orchestrator executing exact, tolerance, ML, exception ledger, and summary passes. |
| **`reconciler/reconcile.py`** | `reconcile_all_statements()` | Main multi-statement reconciliation engine applying Primary vs. Counterpart pool rules. |
| **`matcher/exact_matcher.py`** | `match_exact()` | Stage 1 Exact Matcher. Sanitizes UTR/reference strings and matches with 100% amount parity. |
| **`matcher/tolerance_matcher.py`** | `match_tolerance()` | Stage 2 Tolerance Matcher. Computes 4-factor composite weighted scores ($\le ₹1.00$ variance, $\le 3$ day gap). |
| **`matcher/split_aggregate_matcher.py`**| `match_split_aggregate()`, `match_batch()` | Stage 3 Batch & Fee Solver. Solves 1-to-N batch deposits using net payout fee equations. |
| **`matcher/scoring_engine.py`** | `calculate_pair_score()` | Implements the composite weighted scoring equation ($0.40 S_{\text{id}} + 0.30 S_{\text{amt}} + 0.15 S_{\text{date}} + 0.15 S_{\text{narr}}$). |
| **`forecasting/engine.py`** | `build_forecast()`, `estimate_pending_settlements()` | Forward cash forecaster. Computes seasonal decomposition, 14-day WMA trends, pending settlements, recurring patterns, and beginning balance cumulative series. |
| **`reports/report_builder.py`** | `build_filtered_report_data()` | Aggregates summary KPIs, status subsets, source filters, date ranges, and 30-day forecast data for audit exports. |
| **`reports/pdf_generator.py`** | `generate_pdf_report()` | Generates high-fidelity PDF audit reports complete with visual summary blocks, charts, and detailed transaction tables. |
| **`llm/query_llm.py`** | `query_llm()`, `get_all_groq_keys()` | Central Groq LLM query engine with multi-key failover (`GROQ_API_KEY`, `GROQ_API_KEY1`, `GROQ_API_KEY2`) and fallback model rotation. |
| **`llm/ambiguous_matcher.py`** | `run_llm_match()` | Groq LLM agent evaluating ambiguous candidate pairs ($0.60 \le \text{Score} < 0.85$). |
| **`frontend/api/routes.py`** | `_build_dashboard_run()`, `/reconciliation/beginning_balance`, `/forecast`, `/report/pdf` | Core Flask API layer managing statement store, beginning balance persistence, mirror-pair deduplication (`seen_matched_ids`), and report downloads. |
| **`frontend/statement_store.py`** | `get_statement()`, `list_statements()`, `rebuild_generated_csv()` | JSON database store managing uploaded statement records and disk persistence (`data/statements_db.json`). |
| **`frontend/static/js/dashboard.js`** | `openUnifiedSourceView()`, `editBeginningBalance()`, `initTestCaseLoaders()`, `openRecordComparisonModal()` | Client UI application controller. Manages tab routing, master table rendering, modal popups, benchmark loaders, and keyword comparison. |

---

## 3. Implemented Subsystem Workflows

### 3.1 Unified Master Source Table View (`#sub-unified-sources`)
- **UI Route**: Triggered from topbar "Sources" dropdown or direct sidebar click (`openUnifiedSourceView()`).
- **Aggregation Logic**: `filterAndRenderUnifiedTable()` aggregates rows from all ingested statements into a single, searchable table.
- **Filtering Capabilities**: Dynamic status filter pills (All, SETTLED, MATCHED, SIMILAR, UNMATCHED), source dropdown selector, date range inputs, search bar, and column visibility toggles.

### 3.2 Beginning Balance Engine & State Propagation
- **Endpoint**: `POST /reconciliation/beginning_balance` accepts `{"beginning_balance": <float>}`.
- **Backend Handler**: Updates global `_BEGINNING_BALANCE` in `frontend/api/routes.py` and updates all active runs in `_RUNS`.
- **Cascade Trigger**: In `dashboard.js`, `editBeginningBalance()` sends the backend request and immediately triggers a refresh cascade:
  1. `hydrateExistingRun()` (updates Overview KPIs & charts)
  2. `loadForecastData()` (re-calculates cumulative forward cash flow)
  3. `refreshReportsView()` (updates PDF report data)

### 3.3 Pre-configured Test Benchmark Data Loader
- **Location**: `test_cases/` folder scanner (`/api/test_cases`).
- **Dynamic Case Detection**: Scans for folders matching `Test[N]` (e.g. `Test1`, `Test2`, `Test3`, `Test4`, `Test5`).
- **UI Component**: Collapsible benchmark section featuring high-contrast dark-mode cards with custom badge styling per test case (`.btn-test-load`, `.test-file-badge`).

### 3.4 Add New Transaction Entry Modal
- **UI Modal**: `#addTransactionModalBackdrop` rendered with glassmorphism backdrop (`backdrop-filter: blur(8px)`), `#0f172a` slate container, styled date/amount/description/UTR inputs, currency selectors (`INR`, `USD`, `EUR`, `GBP`), transaction mode options, and primary `Save & Reconcile` button.

---

## 4. Status Classification Rules

### 1. `SETTLED` Status
- **Target Condition**: Reconciliation involving at least one record from a Primary Statement source (`is_primary=True`).
- **Criteria**:
  - **Exact Reference Match**: Cleaned UTR, Settlement ID, or Bank Reference matches counterpart exactly.
  - **Zero Amount Variance**: `abs(primary_net_amount - counterpart_net_amount) == 0.00`.
  - **Or Batch Fee Equation**: Net Bank Deposit equals gross order sum minus gateway fees and taxes.
- **UI Pill**: `<span class="status-pill status-settled">SETTLED</span>`

### 2. `MATCHED` Status
- **Target Condition**: Reconciliation between two counterpart records (`is_primary=False`).
- **Criteria**:
  - **Weighted Score Floor**: Composite Score $\ge 0.85$.
  - **Amount Variance**: Amount delta $\le ₹1.00$.
  - **Date Window**: Date difference $\le 3$ calendar days.
  - **Or LLM Recommendation**: LLM Smart Match agent returns `CONFIRMED` recommendation.
- **UI Pill**: `<span class="status-pill status-matched">MATCHED</span>`

### 3. `SIMILAR` Status
- **Target Condition**: Candidate pair identified with potential alignment, requiring user/LLM review.
- **Criteria**:
  - **Score Window**: Composite Score between $0.50$ and $0.84$.
  - **Candidate Drawer**: Surfaced in comparison modal under **"Find Similar Payments"** (`/api/similar_payments`).
- **UI Pill**: `<span class="status-pill status-similar">SIMILAR</span>`

### 4. `UNMATCHED` Status (Exceptions)
- **Target Condition**: Discrepancy or orphaned record failing all matching rules ($< 0.50$).
- **Routing**: Isolated into the **Exception Ledger** table with an active **"Run LLM Match"** action button.
- **UI Pill**: `<span class="status-pill status-unmatched">UNMATCHED</span>`

---

## 5. Symmetric Mirror-Pair Deduplication

To prevent duplicate row entries when Record A (Bank) matches Record B (Gateway), `frontend/api/routes.py` applies symmetric pair deduplication in `_build_dashboard_run()`:

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
    # Consolidated single row rendered in dashboard table
```

---

## 6. Description & Keyword Extraction in UI

When a user clicks any row to view the side-by-side Comparison Modal (`openRecordComparisonModal`), `dashboard.js` dynamically extracts shared keywords:

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

---

## 7. Verification Commands

Run the full pytest suite to validate all system components:

```bash
PYTHONPATH=. ./.venv/bin/pytest -q
```
