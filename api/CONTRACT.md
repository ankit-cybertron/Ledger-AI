# API Contract Documentation (Ledger AI v2)

This document defines the frozen API contract between the Flask backend (`frontend/api/routes.py`, `frontend/api/chat_routes.py`) and the frontend client (`frontend/static/js/api.js`).

---

## 1. Statement Store API (`/api/statements` & `/api/data/clear`)

### `GET /api/statements`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "statements": [
      {
        "id": "stmt_123",
        "name": "HDFC Bank Statement",
        "source_type": "bank",
        "original_filename": "hdfc_jan.csv",
        "color": "#3b82f6",
        "statement_type_label": "Bank Statement",
        "rules": "",
        "row_count": 150,
        "created_at": "2026-08-25T00:00:00Z"
      }
    ]
  }
  ```

### `POST /api/statements/import`
- **Method**: `POST` (`multipart/form-data`)
- **Body**: `file` (file), `name` (string), `source_type` (string), `color` (string), `statement_type_label` (string), `rules` (string)
- **Response**:
  ```json
  {
    "ok": true,
    "statement": {
      "id": "stmt_123",
      "name": "HDFC Bank Statement",
      "source_type": "bank",
      "original_filename": "hdfc_jan.csv",
      "color": "#3b82f6",
      "statement_type_label": "Bank Statement",
      "rules": "",
      "row_count": 150,
      "created_at": "2026-08-25T00:00:00Z"
    }
  }
  ```

### `GET /api/statements/<statement_id>`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "statement": {
      "id": "stmt_123",
      "name": "HDFC Bank Statement",
      "rows": [...]
    }
  }
  ```

### `POST /api/statements/<statement_id>/append`
- **Method**: `POST` (`multipart/form-data`)
- **Body**: `file` (file)
- **Response**:
  ```json
  {
    "ok": true,
    "result": {
      "added_rows": 10
    }
  }
  ```

### `POST /api/statements/<statement_id>/rename`
- **Method**: `POST` (`application/json`)
- **Body**: `{"name": "New Statement Name"}`
- **Response**:
  ```json
  {
    "ok": true,
    "name": "New Statement Name"
  }
  ```

### `POST /api/statements/<statement_id>/update-rows`
- **Method**: `POST` (`application/json`)
- **Body**: `{"rows": [{"row_index": 0, "updates": {"Customer Name": "Jane Doe"}}]}`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "1 rows updated."
  }
  ```

### `POST /api/statements/<statement_id>/delete-columns`
- **Method**: `POST` (`application/json`)
- **Body**: `{"columns": ["UnusedCol"]}`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "1 columns deleted."
  }
  ```

### `DELETE /api/statements/<statement_id>`
- **Method**: `DELETE`
- **Response**:
  ```json
  {
    "ok": true
  }
  ```

### `POST /api/data/clear`
- **Method**: `POST`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "All statement data and reconciliation results have been cleared."
  }
  ```

---

## 2. Legacy Upload API (`/api/upload`) (Deprecated)

### `POST /api/upload/razorpay`, `POST /api/upload/bank`, `POST /api/upload/orders`
- **Method**: `POST` (`multipart/form-data`)
- **Body**: `file` (file)
- **Response**:
  ```json
  {
    "ok": true,
    "source": "bank",
    "upload_id": "stmt_123",
    "filename": "statement.csv",
    "row_count": 100,
    "uploaded_at": "2026-08-25T00:00:00Z"
  }
  ```

---

## 3. Reconciliation, Pipeline & Dashboard API

### `POST /api/reconcile`
- **Method**: `POST` (`application/json`)
- **Body**: `{"period_label": "August 2026"}`
- **Response**:
  ```json
  {
    "ok": true,
    "run_id": "run_9876",
    "status": "completed"
  }
  ```

### `GET /api/reconciliation` & `GET /api/reconciliation/<run_id>`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "run": {
      "run_id": "run_9876",
      "period_label": "August 2026",
      "status": "completed",
      "closed": false,
      "summary": {
        "total_transactions": 50,
        "auto_matched": 40,
        "llm_matched": 5,
        "manual_matched": 3,
        "unreconciled": 2,
        "percent_reconciled": 96.0,
        "payments_total": 50000.0,
        "deposits_total": 50000.0,
        "variance": 0.0
      },
      "transactions": [
        {
          "settlement_id": "SETL1001",
          "bank_transaction_id": "BANK2001",
          "date": "2026-08-24",
          "bank_description": "UPI Payment",
          "gl_description": "Order #1001",
          "amount": 1000.0,
          "status": "auto",
          "confidence": 1.0,
          "resolved_by": "exact_matcher",
          "reason": "Exact UTR match",
          "stage": "exact",
          "evidence": {
            "amount_difference": 0.0,
            "date_difference_days": 0,
            "identifier_matched": true,
            "candidate_count": 1
          }
        }
      ],
      "exceptions": [...]
    }
  }
  ```

### `GET /api/reconciliation/runs`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "runs": [
      {
        "run_id": "run_9876",
        "period_label": "August 2026",
        "status": "completed",
        "created_at": "2026-08-25T00:00:00Z"
      }
    ]
  }
  ```

### `POST /api/reconciliation/<run_id>/close`
- **Method**: `POST`
- **Response**:
  ```json
  {
    "ok": true,
    "run": {
      "run_id": "run_9876",
      "closed": true,
      "status": "closed"
    }
  }
  ```

### `GET /api/exceptions` & `GET /api/exceptions/<run_id>`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "run_id": "run_9876",
    "exceptions": [
      {
        "exception_id": "EXC-0001",
        "settlement_id": "SETL1002",
        "bank_transaction_id": "BANK2002",
        "date": "2026-08-24",
        "description": "Unresolved Settlement",
        "amount": 500.0,
        "source": "reconciler",
        "exception_type": "ambiguous_tie",
        "priority": "high",
        "reason": "Multiple candidate matches with close scores",
        "resolution_status": "open",
        "resolved_outcome": null,
        "resolved_by": null,
        "candidate_comparison": {
          "candidate_a": { ... },
          "candidate_b": { ... }
        }
      }
    ]
  }
  ```

### `POST /api/exceptions/<exception_id>/resolve`
- **Method**: `POST` (`application/json`)
- **Body**: `{"target_status": "matched", "bank_transaction_id": "BANK2002", "notes": "Manually verified"}`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "Exception EXC-0001 resolved successfully."
  }
  ```

### `GET /api/dashboard/summary`
- **Method**: `GET` (optional `?run_id=...`)
- **Response**:
  ```json
  {
    "ok": true,
    "run_id": "run_9876",
    "period_label": "August 2026",
    "closed": false,
    "summary": { ... }
  }
  ```

### `GET /api/report-html`
- **Method**: `GET`
- **Response**: Returns rendered HTML string (`text/html`).

### `GET /api/pipeline/status`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "status": "idle",
    "log": [...]
  }
  ```

### `GET /api/config`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "config": {
      "schema_version": "2.0.0",
      "absolute_amount_tolerance": 1.0,
      "percentage_tolerance": 0.005,
      "max_tolerance_cap": 50.0,
      "ml_match_threshold": 0.95,
      "llm_match_threshold": 0.70,
      "minimum_score_margin": 0.05
    }
  }
  ```

---

## 4. Manual Overrides, Rematch & Similarity API

### `GET /api/transactions`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "count": 50,
    "transactions": [...]
  }
  ```

### `GET /api/similar-payments`
- **Method**: `GET` (query params: `settlement_id`, `amount`, `date`, `description`, `limit`)
- **Response**:
  ```json
  {
    "ok": true,
    "settlement_id": "SETL1001",
    "candidates": [...]
  }
  ```

### `POST /api/transactions/flag-manual`
- **Method**: `POST` (`application/json`)
- **Body**: `{"transaction_id": "SETL1001", "reason": "Audit required"}`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "Transaction flagged for manual review."
  }
  ```

### `POST /api/transactions/rematch-llm`
- **Method**: `POST` (`application/json`)
- **Body**: `{"settlement_id": "SETL1001", "bank_transaction_id": "BANK2001"}`
- **Response**:
  ```json
  {
    "ok": true,
    "decision": "match",
    "confidence": 0.95,
    "reason": "Matching amounts and date proximity",
    "evidence": { ... }
  }
  ```

### `POST /api/transactions/llm-smart-match`
- **Method**: `POST` (`application/json`)
- **Body**: `{"settlement_id": "SETL1001", "candidates": [...]}`
- **Response**:
  ```json
  {
    "ok": true,
    "selected_candidate_id": "BANK2001",
    "decision": "match",
    "confidence": 0.95,
    "reason": "Cluster candidate similarity evaluation",
    "evidence": { ... }
  }
  ```

### `POST /api/transactions/override-status`
- **Method**: `POST` (`application/json`)
- **Body**: `{"settlement_id": "SETL1001", "bank_transaction_id": "BANK2001", "target_status": "matched"}`
- **Response**:
  ```json
  {
    "ok": true,
    "message": "Transaction 'SETL1001' successfully marked as MATCHED.",
    "settlement_id": "SETL1001",
    "target_status": "matched",
    "run_id": "run_9876"
  }
  ```

---

## 5. Talk to Ledger Chat API (`/api/chat`)

### `GET /api/chat/sessions`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "sessions": [
      {
        "id": "sess_123",
        "title": "Settlement Q&A",
        "created_at": "2026-08-25T00:00:00Z",
        "updated_at": "2026-08-25T00:00:00Z",
        "message_count": 2
      }
    ]
  }
  ```

### `POST /api/chat/sessions`
- **Method**: `POST`
- **Response**:
  ```json
  {
    "ok": true,
    "session": {
      "id": "sess_123",
      "title": "New Chat Session",
      "created_at": "...",
      "updated_at": "...",
      "message_count": 0
    }
  }
  ```

### `GET /api/chat/sessions/<session_id>`
- **Method**: `GET`
- **Response**:
  ```json
  {
    "ok": true,
    "session": {
      "id": "sess_123",
      "title": "New Chat Session",
      "messages": [...]
    }
  }
  ```

### `DELETE /api/chat/sessions/<session_id>`
- **Method**: `DELETE`
- **Response**:
  ```json
  {
    "ok": true
  }
  ```

### `POST /api/chat/sessions/<session_id>/messages`
- **Method**: `POST` (`application/json`)
- **Body**: `{"message": "What is the status of settlement SETL1001?"}`
- **Response**:
  ```json
  {
    "ok": true,
    "reply": "Settlement SETL1001 was matched by exact UTR matching.",
    "session": { ... }
  }
  ```

### `POST /api/chat` (Direct Endpoint)
- **Method**: `POST` (`application/json`)
- **Body**: `{"message": "Why is exception EXC-0001 open?"}`
- **Response**:
  ```json
  {
    "ok": true,
    "answer": "EXC-0001 is open due to an ambiguous tie between two candidate bank transactions."
  }
  ```

---

## 6. Report Export API (`/api/reports/export`) (Part 10)

### `POST /api/reports/export` & `GET /api/reports/export`
- **Method**: `POST` (`application/json`) or `GET`
- **Body (POST)**:
  ```json
  {
    "format": "pdf",
    "statuses": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
    "sources": ["all"],
    "start_date": "2026-01-01",
    "end_date": "2026-12-31",
    "sections": ["summary", "charts", "transactions", "exceptions", "integrity"]
  }
  ```
- **Response**:
  - Binary file download attachment (`application/pdf` or `text/markdown`).
  - Headers: `Content-Disposition: attachment; filename="ledger_reconciliation_report.pdf"` (or `.md`).

