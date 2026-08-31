# Ledger AI — Groq LLM Agent Architecture Specification

> **Subsystem**: `llm/query_llm.py`, `llm/ambiguous_matcher.py`, & `agents/settlement_qa_agent.py`  
> **LLM Provider**: Groq API (`openai/gpt-oss-120b`, `qwen/qwen3.6-27b`, `openai/gpt-oss-20b`) with Multi-Key Failover Rotation

---

## 1. Executive Summary

The **LLM Infrastructure** provides three core capabilities:
1. **On-Demand Ambiguous Match Evaluation** (`llm/ambiguous_matcher.py`): Evaluates candidate pairs when traditional rule-based matchers produce scores between $0.60$ and $0.85$ or when user clicks **"Run LLM Match"** in the UI modal.
2. **Smart AI Column Alignment** (`frontend/statement_store.py`): Analyzes raw column headers and sample data rows to infer canonical schema field mappings (`_llm_analyze_columns`).
3. **Settlement Q&A Agent ("Talk to Ledger")** (`agents/settlement_qa_agent.py`): Natural language chat assistant providing database lookups and reconciliation insights.

All LLM requests funnel through `llm/query_llm.py`, which provides automatic API key rotation (`GROQ_API_KEY`, `GROQ_API_KEY1`, `GROQ_API_KEY2`) and model failover.

---

## 2. Centralized Key Failover & Query Engine (`llm/query_llm.py`)

The query engine manages environment key rotation and model fallback:

```python
def query_llm(prompt: str, system_prompt: str = None) -> str:
    """
    Executes an LLM prompt against Groq API with multi-key failover & model fallback.
    Rotates through GROQ_API_KEY, GROQ_API_KEY1, GROQ_API_KEY2.
    Fallback models: openai/gpt-oss-120b -> qwen/qwen3.6-27b -> openai/gpt-oss-20b.
    """
```

---

## 3. Ambiguous Matching Workflow

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
  │            Groq API Call (`llm/query_llm.py`)            │
  │  Rotates GROQ_API_KEY -> GROQ_API_KEY1 -> GROQ_API_KEY2  │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │               Structured Response Parsing                │
  │  - recommendation: CONFIRMED | REJECTED | MANUAL_REVIEW  │
  │  - confidence_score: 0.00 - 1.00                         │
  │  - reasoning: Detailed audit trail explanation          │
  └──────────────────────────────────────────────────────────┘
```

---

## 4. Input & Output Schemas

### Input Payload:
```json
{
  "primary_transaction": {
    "id": "BNK-TXN-0004",
    "amount": 4999.00,
    "date": "2026-08-15",
    "description": "CARD-SETL Meera Iyer"
  },
  "candidate_transactions": [
    {
      "id": "PGREF202421",
      "amount": 5000.00,
      "date": "2026-08-14",
      "description": "Payment for order ORD8034 Meera Iyer",
      "fee": 1.00
    }
  ]
}
```

### Structured Response Output:
```json
{
  "recommendation": "CONFIRMED",
  "matched_candidate_id": "PGREF202421",
  "confidence_score": 0.92,
  "reasoning": "The bank entry 'CARD-SETL Meera Iyer' for ₹4999.00 matches card payment PGREF202421 for ₹5000.00 minus a ₹1.00 gateway processing fee. Customer name 'Meera Iyer' and transaction dates align perfectly."
}
```

---

## 5. Key Files & Code Reference

| File Path | Responsible Class / Function | Implementation Role |
|---|---|---|
| `llm/query_llm.py` | `query_llm()`, `get_all_groq_keys()` | Central Groq query engine with key rotation and fallback models. |
| `llm/ambiguous_matcher.py` | `run_llm_match()` | Ambiguous pair evaluation using Groq LLM. |
| `agents/settlement_qa_agent.py` | `answer_question()` | Settlement Q&A chat assistant ("Talk to Ledger"). |
| `frontend/statement_store.py` | `_llm_analyze_columns()` | Smart AI column mapping during file import. |
| `frontend/api/routes.py` | `/api/llm_match`, `/api/chat` | Flask endpoints handling LLM match requests and chat agent bridge. |
| `frontend/static/js/dashboard.js` | `executeLLMMatchInModal()` | Client UI binding for "Run LLM Match" button in comparison modal. |

---

## 6. User Interface Representation

- **Comparison Modal Action**: Single consolidated **"Run LLM Match"** button in modal footer.
- **AI Audit Section**: Renders real-time spinner during invocation, followed by an AI Audit Trail box displaying reasoning explanation, recommendation status pill, and confidence score.
