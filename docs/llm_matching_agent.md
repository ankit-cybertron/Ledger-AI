# Ledger AI — LLM Matching Agent Specification

> **Subsystem**: `llm/query_llm.py`, `llm/ambiguous_matcher.py`, & `agents/settlement_qa_agent.py`  
> **LLM Provider**: Groq API (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.6-27b`) with Key Rotation

---

## 1. Overview & Architecture

The **LLM Infrastructure** handles:
1. **Column Mapping & Smart Ingestion** (`frontend/statement_store.py`): Analyzes raw column headers and sample data rows to infer canonical schema field mappings.
2. **Ambiguous Discrepancy Matching** (`llm/ambiguous_matcher.py`): Evaluates candidate pairs when traditional rule-based matchers produce ambiguous results or when user clicks **"Run LLM Match"**.
3. **Settlement Q&A Agent ("Talk to Ledger")** (`agents/settlement_qa_agent.py`): Natural language chat assistant with function-calling tools against ledger databases.

All LLM calls funnel through `llm/query_llm.py`, which provides automatic API key rotation (`GROQ_API_KEY`, `GROQ_API_KEY1`, `GROQ_API_KEY2`) and fallback model selection.

---

## 2. Centralized Key Rotation (`llm/query_llm.py`)

```python
def query_llm(prompt: str, system_prompt: str = None) -> str:
    """
    Executes an LLM prompt against Groq API with multi-key failover & model fallback.
    Rotates through all valid GSK keys in environment variables.
    """
```

---

## 3. High-Level Agent Workflow

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
  └────────────────────────────┬─────────────────────────────┘
```

---

## 4. Key Files & Code Reference

| File Path | Responsible Function / Class | Role |
|---|---|---|
| `llm/query_llm.py` | `query_llm()`, `get_all_groq_keys()` | Central Groq query engine with key failover & model rotation. |
| `llm/ambiguous_matcher.py` | `run_llm_match()` | Ambiguous pair evaluation using Groq LLM. |
| `agents/settlement_qa_agent.py` | `answer_question()` | Settlement Q&A chat agent with tool execution. |
| `frontend/statement_store.py` | `_llm_analyze_columns()` | Smart AI column mapping during import. |
nt": 5000.00,
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
