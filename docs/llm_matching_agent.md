# Ledger AI — LLM Matching Agent Specification

> **Subsystem**: `llm/ambiguous_matcher.py`  
> **LLM Provider**: Google Gemini API (`gemini-2.5-flash` / `gemini-1.5-pro`)

---

## 1. Overview & Architecture

The **LLM Matching Agent** handles complex, ambiguous financial discrepancies where traditional rule-based matchers and ML feature models produce moderate confidence scores ($0.60 \le \text{Score} < 0.85$), or when a user clicks **"Run LLM Match"** in the Comparison Modal.

Using structured prompts, the agent analyzes raw transaction descriptions, customer names, partial reference numbers, gateway fee deductions, and date offsets to produce a natural-language audit reasoning and structured match recommendation.

---

## 2. High-Level Agent Workflow

```
  ┌──────────────────────────────────────────────────────────┐
  │   Unmatched Record or Ambiguous Pair Selected in UI      │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │               Context Payload Construction               │
  │  Primary Tx, Candidate Records, Fees, Dates, Descriptions│
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │                 Google Gemini API Call                   │
  │     Evaluates structured financial prompt schema          │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │               Structured Response Parsing                │
  │  - recommendation: CONFIRMED | REJECTED | MANUAL_REVIEW  │
  │  - confidence_score: 0.00 - 1.00                         │
  │  - reasoning: Detailed audit trail explanation          │
  └────────────────────────────┬─────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │ Recommendation == CONFIRMED         │ Recommendation != CONFIRMED
            ▼                                     ▼
  ┌───────────────────────────┐         ┌───────────────────────────┐
  │ Update Status to MATCHED  │         │ Retain UNMATCHED Status   │
  │ Display LLM Audit Trail   │         │ Display AI Audit Reasoning│
  └───────────────────────────┘         └───────────────────────────┘
```

---

## 3. Input JSON Context Payload Schema

When an LLM match request is triggered, `llm/ambiguous_matcher.py` constructs a structured JSON context payload:

```json
{
  "primary_transaction": {
    "transaction_id": "BNK-TXN-0004",
    "source": "Rw 01 Bank Statement",
    "amount": 4999.00,
    "date": "2024-08-15",
    "description": "CARD-SETL Meera Iyer",
    "utr": null
  },
  "candidate_records": [
    {
      "transaction_id": "PGREF202421",
      "source": "Rw 04 Card Payment",
      "amount": 5000.00,
      "date": "2024-08-14",
      "description": "Payment for order ORD8034 Meera Iyer",
      "fee": 1.00
    }
  ]
}
```

---

## 4. Structured Output Format

The agent returns JSON formatted adhering to strict schema:

```json
{
  "recommendation": "CONFIRMED",
  "matched_candidate_id": "PGREF202421",
  "confidence_score": 0.92,
  "reasoning": "The bank entry 'CARD-SETL Meera Iyer' for ₹4999.00 matches card payment PGREF202421 for ₹5000.00 minus a ₹1.00 gateway processing fee. Customer name 'Meera Iyer' and transaction dates (1-day gap) align perfectly."
}
```

---

## 5. Key Files & Code Reference

| File Path | Responsible Function / Method | Role |
|---|---|---|
| `llm/ambiguous_matcher.py` | `run_llm_match()` | Formats prompt, invokes Google Gemini API, and parses response. |
| `frontend/api/routes.py` | `/api/llm_match` | Flask endpoint handling LLM match requests from frontend UI. |
| `frontend/static/js/dashboard.js` | `executeLLMMatchInModal()` | UI handler binding "Run LLM Match" button in comparison modal. |

---

## 6. User Interface Representation

- **Modal Footer Action**: Single consolidated **"Run LLM Match"** button.
- **Audit Section**: Displays real-time loading spinner during LLM invocation, followed by an AI Audit Trail box showing reasoning text, match status pill, and confidence score.
