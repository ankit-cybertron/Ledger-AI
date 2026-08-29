# Ledger AI — Statement Ingestion Pipeline Specification

> **Subsystem**: `ingestion/`  
> **Core Purpose**: End-to-end ingestion, parsing, mapping, normalization, and deduplication of multi-format financial statements.

---

## 1. Executive Summary

The **Ingestion Pipeline** ingests raw financial statement files (`CSV`, `XLSX`, `PDF`) from multi-source systems (Banks, Razorpay, Stripe, Internal Orders, Cash Books, UPI) and converts them into standardized `CanonicalTransaction` models.

---

## 2. End-to-End Ingestion Flow

```
  ┌──────────────────────────────────────────────────────────┐
  │         Raw File Upload (CSV, XLSX, PDF)                 │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Stage 1: File Reader (`ingestion/file_reader.py`)        │
  │ Read sheet tables, sanitize encodings, extract headers   │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Stage 2: Duplicate Columns (`ingestion/duplicate_columns.py`)│
  │ Detect identical mapped headers & resolve collisions    │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Stage 3: Column Mapper (`ingestion/column_mapper.py`)    │
  │ 3A: Exact Alias Lookup | 3B: Fuzzy Distance | 3C: Log   │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Stage 4 & 5: Row Normalizer (`ingestion/normalizer.py`)  │
  │ Parse locale amounts, infer direction, regex backfill,  │
  │ generate clean fallback IDs (e.g. BNK-TXN-0004)          │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Deduplication (`ingestion/dedupe.py`)                    │
  │ SHA-256 content hash check to eliminate duplicate rows   │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ DB Store & CSV Generator (`frontend/statement_store.py`) │
  │ Save to `data/statements_db.json` & rebuild CSV feeds    │
  └──────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Ingestion Pipeline Stages

### Stage 1: File Reader (`ingestion/file_reader.py`)
- Reads raw files using pandas/openpyxl for spreadsheets or pdfplumber/fitz for PDF bank statements.
- Converts input streams into `RawTable` data structures containing source metadata, sheet names, raw headers, and row dicts.

### Stage 2: Duplicate Column Resolution (`ingestion/duplicate_columns.py`)
- Detects files containing duplicate headers mapping to the same canonical field (e.g., two `Amount` columns).
- Computes non-null count and variance metrics to automatically retain the primary data column and drop redundant duplicates.

### Stage 3: 3-Stage Column Mapping (`ingestion/column_mapper.py`)
- **Stage 3A (Exact Alias)**: Checks raw header strings against configurable alias table (`config/column_aliases.json`). Confidence = $1.0$.
- **Stage 3B (Fuzzy Similarity)**: Evaluates string distance using Levenshtein ratio for unmapped headers. Confidence = $0.60 - 0.90$.
- **Stage 3C (Unmapped Logging)**: Logs unresolved headers to `data/logs/unmapped_headers.log` for continuous dictionary expansion.

### Stage 4 & 5: Row Normalization (`ingestion/normalizer.py`)
- **Locale-Agnostic Numeric Parsing**: Handles currency symbols (`₹`, `$`), thousand separators, Dr/Cr suffixes, and parenthetical negatives `(500.00)`.
- **Reference Identifier Extraction**: Extracts UTRs, Order IDs, and Settlement IDs from free-text narration using regex patterns defined in `config/normalization_rules.json`.
- **Clean Fallback ID Generator (`_generate_clean_fallback_tx_id`)**: When a record has no explicit transaction ID, generates clean human-readable IDs (`BNK-TXN-0004`, `ORD-TXN-0012`, `UPI-TXN-0005`) instead of raw ugly filename strings.

### Intra-Statement Deduplication (`ingestion/dedupe.py`)
- Computes a SHA-256 content hash over key fields (`transaction_date`, `net_amount`, `utr`, `order_id`, `description`, `customer_name`).
- Suppresses duplicate row uploads within the same statement file.

---

## 4. Key Files & Code Reference

| File Path | Responsible Class / Function | Purpose |
|---|---|---|
| `ingestion/file_reader.py` | `read_source_file()`, `RawTable` | Reads CSV, XLSX, and PDF files. |
| `ingestion/duplicate_columns.py` | `detect_duplicate_columns()` | Resolves multi-column header collisions. |
| `ingestion/column_mapper.py` | `map_columns()`, `ColumnMapping` | 3-stage column header mapper. |
| `ingestion/normalizer.py` | `normalize_row()`, `_generate_clean_fallback_tx_id()` | Normalizes amounts, status, dates, and IDs. |
| `ingestion/dedupe.py` | `detect_duplicates()` | Computes SHA-256 hash deduplication. |
| `frontend/statement_store.py` | `normalize_statement_columns()`, `rebuild_generated_csv()` | Persists normalized statements and regenerates active CSVs. |
