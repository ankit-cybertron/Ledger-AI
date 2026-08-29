# Ledger AI: Automated Financial Reconciliation & Exception Engine

Ledger AI is an enterprise-grade financial reconciliation platform designed to automatically match, verify, and reconcile complex transaction datasets across bank statements, payment gateway settlement summaries (Razorpay, PayPal, Stripe, PhonePe, GPay), and internal order registers.

The system replaces manual spreadsheet matching with an automated multi-pass matching cascade, an evidence-weighted scoring engine, machine learning confidence evaluation, and Groq LLM semantic reasoning for unresolved exception handling.

---

## Architectural Overview

```
                          [ Ingestion Pipeline ]
                     Multi-Format (CSV, XLSX, PDF)
                                   │
                                   ▼
                       [ Taxonomy & Deduplication ]
                  Cross-App Dedupe & Exclusions Filter
                                   │
                                   ▼
                      [ Multi-Pass Matching Engine ]
    ┌──────────────────────────────┼──────────────────────────────┐
    │                              │                              │
[ Pass 1: Exact Match ]   [ Pass 2: Settlement Lag & MDR ]  [ Pass 3: N:1 Split/Aggregate ]
    │                              │                              │
    └──────────────────────────────┼──────────────────────────────┘
                                   │
                                   ▼
                   [ Scoring & ML Confidence Model ]
              Weights: Identifier, Amount, Date, Narration
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       High Confidence (>= 85%)       Ambiguous Exception (50% - 84%)
              [ MATCHED ]                         │
                                                  ▼
                                       [ Groq LLM Smart Matcher ]
                                                  │
                                                  ▼
                                      [ Exception Ledger & Audit ]
```

---

## Key Features & Capabilities

### 1. Multi-Format Ingestion Pipeline
- **Unified Processing**: Ingests CSV, Microsoft Excel (`.xlsx`, `.xls`), and PDF bank statements/settlement summaries.
- **Dynamic Header Normalization**: Automatically maps heterogeneous column aliases (e.g., `UTR`, `Auth Code`, `Txn ID`, `Credit`, `Debit`, `Gross Amount`) into a unified canonical schema (`CanonicalTransaction`).
- **PDF Extraction**: Extracts structured transaction tables from ICICI, SBI, HDFC, and Razorpay summary PDFs, stripping header text and footer totals.

### 2. Multi-Pass Matching Cascade
- **Pass 1: Clean Exact Match**: High-confidence matching on normalized UTRs, reference IDs, and exact amount/date alignments.
- **Pass 2: Settlement Lag & Fee/MDR Tolerance**: Net-of-fee matching accounting for settlement delays (1–4 days) and gateway MDR structures (Razorpay 1.8% + GST, PayPal 3.4% + FX, Card 1.9%).
- **Pass 3: N:1 Split & Aggregate Reconciliation**: Aggregates N individual payment rows to reconcile against single consolidated batch credits in bank statements.
- **Order Book Cross-Linking**: Cross-links internal order book records against payment processor credits.

### 3. Exception Handling & Discrepancy Taxonomy
- **Digit Transposition Detection**: Flags potential human typographical errors (e.g., ₹47,097.63 vs ₹47,079.63) as similar candidate matches rather than dropping them.
- **Duplicate Entry Detection**: Identifies double-booked credit entries and flags duplicate discrepancies.
- **Cross-App Deduplication**: Deduplicates identical transaction references originating across multiple exports (e.g., GPay and PhonePe).
- **Automated Exclusions**: Filters non-settlement statuses (`FAILED`, `DECLINED`, `PENDING`) prior to matching to prevent false exception generation.
- **Parenthetical Negative Parsing**: Handles negative debit formatting conventions across financial statements (e.g., `(1,234.56)` parsed as `-1234.56`).

### 4. Machine Learning & Groq LLM Reasoning
- **Scoring Engine**: Evaluates evidence scores based on parameter weights (Identifier match, Amount delta, Date proximity, Narration similarity).
- **Ambiguous Exception Resolution**: Routes unresolved transactions ($0.50 \le \text{Confidence} < 0.85$) to the Groq LLM reasoning engine.
- **Multi-Key API Rotation**: Uses automated fallback and rotation across Groq API keys to maintain high availability under rate limits.

### 5. Configurable Constants Architecture
- **Zero Magic Numbers**: All matching thresholds, scoring weights, UI limits, and report parameters are externalized into dedicated JSON configuration files in `/config/`:
  - `scoring_weights.json`: Core matching weights and incompatibility penalties.
  - `ui_config.json`: Dashboard buffer limits, truncation lengths, and visual palettes.
  - `report_config.json`: PDF formatting, font sizes, margins, and branding options.

### 6. Audit & PDF Export Generation
- **Executive Audit Reports**: Generates downloadable PDF reports with executive summary KPIs, discrepancy breakdowns, and full transaction ledgers via ReportLab.
- **Data Export**: Supports Excel (`.xlsx`) export of reconciled results.

---

## Directory Structure

```
Ledger/
├── config/                  # Centralized JSON configuration files
│   ├── matching_config.py   # Matching configuration model & dynamic loader
│   ├── scoring_weights.json # Matching thresholds & scoring weights
│   ├── ui_config.json       # UI and dashboard parameters
│   └── report_config.json   # PDF & report layout styles
├── frontend/                # Web Dashboard Application
│   ├── api/                 # Flask REST routes & pipeline tracker
│   ├── static/              # CSS styles & modular JavaScript
│   ├── templates/           # Jinja2 HTML templates
│   ├── app.py               # Flask application factory
│   └── statement_store.py   # State management & session persistence
├── ingestion/               # Multi-format ingestion pipeline
│   ├── column_mapper.py     # Header normalization & alias resolution
│   ├── file_reader.py       # CSV, Excel, and PDF parser
│   ├── normalizer.py        # Data type cleaning & canonical adapter
│   └── dedupe.py            # Deduplication & exclusion rules
├── matcher/                 # Core matching algorithms
│   ├── exact_matcher.py     # Pass 1 clean exact matching
│   ├── tolerance_matcher.py # Pass 2 fee & date gap matching
│   ├── split_aggregate_matcher.py # Pass 3 N:1 aggregate matching
│   └── scoring_engine.py    # Evidence-weighted scoring matrix
├── llm/                     # Groq LLM Integration
│   └── query_llm.py         # Semantic exception matcher & key rotation
├── ml/                      # Machine Learning confidence scoring
│   ├── feature_schema.py    # Feature extraction pipeline
│   └── feedback_loop.py     # Feedback loop & model updating
├── reconciler/              # Pipeline runner & orchestration
│   ├── pipeline_runner.py   # Full reconciliation orchestrator
│   └── reconcile.py         # Cascade execution runner
├── reports/                 # Audit & export generators
│   ├── pdf_generator.py     # ReportLab PDF audit generator
│   └── excel_generator.py   # Excel export generator
├── schema/                  # Dataclasses & enums
│   ├── canonical_transaction.py # Canonical data schema
│   └── enums.py             # Match status & discrepancy taxonomy
├── Procfile                 # Cloud WSGI server entrypoint
├── render.yaml              # Render blueprint specification
├── Dockerfile               # Container deployment configuration
├── requirements.txt         # Production dependencies
└── run.py                   # Main local entrypoint
```

---

## Local Installation & Setup

### Prerequisites
- Python 3.10 or higher
- `pip` package manager

### Installation Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/ankit-cybertron/Ledger-AI.git
   cd Ledger
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install production dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to include your Groq API credentials:
   ```env
   GROQ_API_KEY=gsk_your_groq_api_key
   GROQ_MODEL=openai/gpt-oss-120b
   ```

5. Run the local application:
   ```bash
   python run.py
   ```
   Open your browser at `http://127.0.0.1:5050`.

---

## Production Cloud Deployment

### Render Deployment

The repository includes pre-configured `Procfile` and `render.yaml` files for seamless deployment on Render:

1. Connect your repository to Render in the Render Dashboard.
2. Render will automatically detect the settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
3. Add `GROQ_API_KEY` and `GROQ_MODEL` under **Environment Variables**.
4. Deploy the service.

---

## Testing

Run the test suite using `pytest`:

```bash
pytest tests/
```

---

## License

This project is licensed under the MIT License.
