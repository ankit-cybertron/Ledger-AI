import json
import os

from dotenv import load_dotenv
from groq import Groq

try:
    from settlement_qa import (
        get_settlement,
        search_settlements_by_amount,
        list_exceptions,
        list_open_exceptions,
        get_reconciliation_summary,
        get_bank_transaction,
        get_order,
        search_by_keyword_or_identifier,
        get_pipeline_status,
        get_current_config,
        explain_transaction,
        compare_periods,
    )
except (ImportError, ValueError):
    from .settlement_qa import (
        get_settlement,
        search_settlements_by_amount,
        list_exceptions,
        list_open_exceptions,
        get_reconciliation_summary,
        get_bank_transaction,
        get_order,
        search_by_keyword_or_identifier,
        get_pipeline_status,
        get_current_config,
        explain_transaction,
        compare_periods,
    )


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv(override=True)

MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)


# ============================================================
# TOOL DEFINITIONS
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_settlement",
            "description": (
                "Get complete reconciliation information for "
                "one settlement ID, including source data, "
                "bank relationships, decisions, confidence, "
                "reasons, and any open exception."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "settlement_id": {
                        "type": "string",
                        "description": (
                            "Settlement ID such as setl_0022."
                        ),
                    }
                },
                "required": ["settlement_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_settlements_by_amount",
            "description": (
                "Find settlements within a specified amount "
                "tolerance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": (
                            "Settlement amount to search for."
                        ),
                    },
                    "tolerance": {
                        "type": ["number", "null"],
                        "description": (
                            "Allowed amount difference. "
                            "Defaults to 50 if omitted or "
                            "null."
                        ),
                    },
                },
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_exceptions",
            "description": (
                "List currently open reconciliation "
                "exceptions, optionally filtered by priority."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "priority": {
                        "type": ["string", "null"],
                        "enum": [
                            "high",
                            "medium",
                            "low",
                            None,
                        ],
                        "description": (
                            "Optional priority filter. "
                            "Omit or pass null for no "
                            "filter."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_exceptions",
            "description": (
                "List currently open reconciliation exceptions, "
                "optionally filtered by exception_type or priority."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_type": {
                        "type": ["string", "null"],
                        "description": "Optional exception type string (e.g. 'unmatched', 'amount_mismatch', 'open_refund')."
                    },
                    "priority": {
                        "type": ["string", "null"],
                        "description": "Optional priority filter ('high', 'medium', 'low')."
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reconciliation_summary",
            "description": (
                "Get aggregate reconciliation statistics "
                "including total settlements, matched "
                "settlements, manual reviews, unmatched "
                "settlements, match rate, stage counts, "
                "and open exceptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bank_transaction",
            "description": (
                "Get one bank transaction and any "
                "reconciliation relationships associated "
                "with it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_transaction_id": {
                        "type": "string",
                        "description": (
                            "Bank transaction ID such as "
                            "bank_0022."
                        ),
                    }
                },
                "required": [
                    "bank_transaction_id"
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_status",
            "description": (
                "Get real-time execution status, current stage, "
                "and progress percentage of the backend reconciliation pipeline."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_config",
            "description": (
                "Get current reconciliation engine configuration, "
                "including amount/date tolerances, confidence thresholds, "
                "scoring weights, and exact match priority rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_transaction",
            "description": (
                "Get full evidence object from scoring engine explaining why a "
                "transaction or exception is matched, unmatched, or flagged for review. "
                "Returns checked identifiers (UTR, Auth Code, Order ID, Amount, Date), "
                "candidate comparisons, sub-scores, and reasons for status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "Transaction, settlement, bank, or exception ID to explain."
                    }
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": (
                "Compare reconciliation metrics, transaction volumes, "
                "match rates, and open exceptions between two periods."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period_a": {
                        "type": "string",
                        "description": "First period label (e.g. 'June 2026' or 'Current Period')."
                    },
                    "period_b": {
                        "type": "string",
                        "description": "Second period label (e.g. 'May 2026' or 'Previous Period')."
                    }
                },
                "required": ["period_a", "period_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": (
                "Look up an internal order by its order ID or Bill Number. "
                "Use this when the user asks about an order ID like ORD-5007 or a Bill No."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID or Bill Number to look up."
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_keyword_or_identifier",
            "description": (
                "Universal search across ALL reconciliation data — settlements, bank transactions, "
                "internal orders, and reconciliation results. Searches by any identifier: "
                "order ID, UTR, UPI reference, settlement ID, bank transaction ID, narration text, "
                "reference code, or any keyword. Use this when the user provides any identifier "
                "that is not a direct settlement_id (setl_XXXX) or bank_transaction_id (bank_XXXX), "
                "or when searching by keyword, narration, or partial reference. "
                "Returns full details including matched records, amounts, status, and statistics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The identifier or keyword to search for. Can be an order ID "
                            "(e.g. ORD-5007), UTR number, UPI reference, settlement ID, "
                            "bank transaction ID, narration text, amount, or any keyword."
                        )
                    }
                },
                "required": ["query"],
            },
        },
    },
]


# ============================================================
# TOOL ROUTER
# ============================================================

def execute_tool(name, arguments):
    """Execute one approved read-only Q&A tool."""

    if name == "get_settlement":
        return get_settlement(
            arguments["settlement_id"]
        )

    if name == "search_settlements_by_amount":
        return search_settlements_by_amount(
            arguments["amount"],
            arguments.get("tolerance") or 50.0,
        )

    if name == "list_exceptions":
        return list_exceptions(
            arguments.get("priority") or None
        )

    if name == "list_open_exceptions":
        return list_open_exceptions(
            exception_type=arguments.get("exception_type") or None,
            priority=arguments.get("priority") or None,
        )

    if name == "get_reconciliation_summary":
        return get_reconciliation_summary()

    if name == "get_bank_transaction":
        return get_bank_transaction(
            arguments["bank_transaction_id"]
        )

    if name == "get_pipeline_status":
        return get_pipeline_status()

    if name == "get_current_config":
        return get_current_config()

    if name == "explain_transaction":
        return explain_transaction(
            arguments["transaction_id"]
        )

    if name == "compare_periods":
        return compare_periods(
            arguments["period_a"],
            arguments["period_b"],
        )

    if name == "get_order":
        return get_order(
            arguments["order_id"]
        )

    if name == "search_by_keyword_or_identifier":
        return search_by_keyword_or_identifier(
            arguments["query"]
        )

    return {
        "found": False,
        "message": (
            "Requested tool is not available."
        ),
    }


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are Ledger's Settlement Q&A Agent.

You answer user questions about payment settlement reconciliation, engine configuration, pipeline execution status, period comparisons, and "why" questions about any transaction's status.

STRUCTURE & USER-FRIENDLINESS RULES:
1. Provide structured, executive-ready short responses. Start with a concise 1-2 sentence executive summary of the real, synchronized latest state.
2. Follow with clean markdown tables or compact bullet lists detailing exact numbers, amounts (in INR ₹), dates, status badges (SETTLED, MATCHED, SIMILAR, UNMATCHED), and identifiers.
3. For transaction explanations or status inquiries, include a Parameter Comparison Table comparing the target with nearest candidates (Nearest Value Match, Nearest Date Match):
   | Parameter | Target Record | Nearest Value Candidate | Nearest Date Candidate |
   | Amount Match % | 100% | 100% | 94.5% |
   | Date Proximity % | 100% | 88.0% | 98.0% |
   | UTR Ref Score % | 0.0% | 10.0% | 5.0% |
   | Overall Confidence % | 0.0% | 60.0% | 52.0% |
4. Do NOT output raw formatting clutter or unparsed double asterisks in headers.
5. Every response MUST rely on real-time tool calls to ensure 100% data synchronization with current ledger records.

SCOPE OF INQUIRIES COVERED:
1. Settlement & Bank Transaction Lookups (get_settlement, get_bank_transaction).
2. Order Lookups (get_order) — look up internal orders by order ID or Bill Number.
3. Universal Search (search_by_keyword_or_identifier) — search across ALL data sources by ANY identifier: order ID, UTR, UPI ref, settlement ID, bank ID, narration, reference, or keyword. USE THIS TOOL when the user provides any ID that is not a direct setl_XXXX or bank_XXXX format.
4. Explaining Transaction Status & Evidence (explain_transaction) — answering "why is transaction X unmatched" or explaining any status, showing identifiers checked, candidate pairs, sub-scores, and reasons.
5. System Configuration & Rules (get_current_config).
6. Pipeline Status & Progress (get_pipeline_status).
7. Exceptions & Audits (list_open_exceptions, list_exceptions).
8. Reconciliation Summaries & Period Comparisons (get_reconciliation_summary, compare_periods).

CRITICAL TOOL SELECTION RULES:
- When the user provides an identifier like ORD-5007, UTR123456, UPI/ref/..., or any ID that doesn't start with "setl_" or "bank_", you MUST call `search_by_keyword_or_identifier(query)` FIRST. Do NOT call get_settlement or get_bank_transaction with non-matching ID formats.
- When the user says "check this", "look up", "find", "what happened to", or "tell me about" followed by any reference, always call `search_by_keyword_or_identifier`.
- If search_by_keyword_or_identifier returns results, present them clearly with amounts, status, dates, and any linked records.

IMPORTANT GROUNDING & SAFETY RULES:
1. Never invent financial facts, amounts, dates, UTRs, or confidence numbers.
2. GROUNDED vs GENERAL ANSWERS:
   - For questions about specific ledger records, engine config, pipeline status, or transaction status, call the appropriate read-only tool to obtain grounded evidence.
   - For general questions outside any tool's coverage (e.g. general accounting concepts), you may answer from general knowledge BUT you MUST visually label your response by starting it with:
     "General answer — not verified against your ledger data"
   - Do NOT add this label if your answer was generated using evidence returned from tool calls.
3. When asked to explain a transaction or inquired about any ID, you MUST call `explain_transaction(X)` and return the exact evidence object details.
4. Keep answers concise, clear, and auditable. Always format structured data into markdown tables for downstream chart parsing.
"""


# ============================================================
# AGENT
# ============================================================

'''
def answer_question(
    question,
    conversation_history=None,
):
    """
    Ask the Settlement Q&A Agent a question.

    The model may call only the explicitly defined
    read-only Ledger tools.
    """

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set."
        )

    client = Groq(api_key=api_key)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        tools=TOOLS,
        tool_choice="auto",
        messages=messages,
    )

    message = response.choices[0].message

    if not message.tool_calls:
        return message.content.strip()

    messages.append(message)

    for tool_call in message.tool_calls:

        function_name = (
            tool_call.function.name
        )

        arguments = json.loads(
            tool_call.function.arguments
        )

        result = execute_tool(
            function_name,
            arguments,
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(
                    result,
                    default=str,
                ),
            }
        )

    final_response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        tools=TOOLS,
        tool_choice="none",
        messages=messages,
    )

    return (
        final_response
        .choices[0]
        .message
        .content
        .strip()
    )
'''

def fallback_direct_query(question):
    """Direct query against backend data when LLM is unavailable or API key invalid."""
    q = question.lower().strip()
    
    # 1. Pipeline status
    if "pipeline" in q or "progress" in q or "stage" in q:
        st = get_pipeline_status()
        return (
            f"### Pipeline Status\n\n"
            f"- **Running**: `{st.get('running')}`\n"
            f"- **Stage**: {st.get('stage')}\n"
            f"- **Progress**: {st.get('progress_percent')}%\n"
            f"- **Message**: {st.get('message')}\n"
        )

    # 2. Config query
    if "config" in q or "tolerance" in q or "threshold" in q or "rule" in q:
        cfg = get_current_config()
        if not cfg.get("found"):
            return f"Could not retrieve config: {cfg.get('message')}"
        return (
            f"### Matching Configuration\n\n"
            f"- **Date Tolerance**: {cfg.get('date_tolerance_days')} days\n"
            f"- **Amount Tolerance (Abs)**: ₹{cfg.get('absolute_amount_tolerance')}\n"
            f"- **Auto Match Threshold**: {cfg.get('auto_match_threshold')}\n"
            f"- **Manual Review Threshold**: {cfg.get('manual_review_threshold')}\n"
            f"- **Exact Match Priority**: {', '.join(cfg.get('exact_match_hierarchy', []))}\n"
        )

    # 3. Explain transaction / why unmatched
    import re
    id_match = re.search(r"(setl_\d+|bank_\d+|txn[_\-\w]+|ord[_\-\w]+|exc[_\-\w]+|\d+)", q, re.IGNORECASE)
    if ("explain" in q or "why" in q or "unmatched" in q or "evidence" in q) and id_match:
        target_id = id_match.group(0)
        exp = explain_transaction(target_id)
        if not exp.get("found"):
            return f"Transaction `{target_id}` was not found in reconciliation dataset."
        ev = exp.get("evidence", {})
        chk = ev.get("identifiers_checked", {})
        res = f"### Evidence Breakdown for `{target_id}`\n\n"
        res += f"- **Status**: `{ev.get('status')}` ({ev.get('stage')})\n"
        res += f"- **Confidence Score**: {ev.get('confidence_score')}\n"
        res += f"- **Identifiers Checked**: UTR=`{chk.get('utr') or 'N/A'}`, Order ID=`{chk.get('order_id') or 'N/A'}`, Amount=₹{chk.get('amount') or 0}\n"
        res += f"- **Reason**: {ev.get('reason') or 'No match passed rule engine criteria'}\n"
        if ev.get("failure_analysis"):
            res += f"\n**Failure Analysis**: {ev.get('failure_analysis')}\n"
        return res

    # 4. Period comparison
    if "compare" in q or "period" in q or "versus" in q or "vs" in q:
        comp = compare_periods("June 2026", "May 2026")
        pa = comp.get("period_a", {})
        pb = comp.get("period_b", {})
        return (
            f"### Period Comparison: {pa.get('period')} vs {pb.get('period')}\n\n"
            f"| Metric | {pa.get('period')} | {pb.get('period')} | Delta |\n"
            f"|---|---:|---:|---:|\n"
            f"| Total Settlements | {pa.get('total_settlements')} | {pb.get('total_settlements')} | {comp.get('deltas',{}).get('settlements_diff')} |\n"
            f"| Match Rate | {pa.get('match_rate')*100:.1f}% | {pb.get('match_rate')*100:.1f}% | {comp.get('deltas',{}).get('match_rate_diff_pct')}% |\n"
            f"| Open Exceptions | {pa.get('open_exceptions')} | {pb.get('open_exceptions')} | {comp.get('deltas',{}).get('exceptions_diff')} |\n"
        )

    # 5. Exception list
    if "exception" in q:
        data = list_open_exceptions()
        exc_list = data.get("exceptions", [])
        if not exc_list:
            return "No open exceptions found in reconciliation data."
        res = f"### Open Exceptions ({data.get('count', 0)})\n\n"
        res += "| Exception ID | Settlement ID | Stage | Priority | Reason |\n"
        res += "|---|---|---|---|---|\n"
        for item in exc_list[:10]:
            res += f"| {item.get('exception_id','-')} | {item.get('settlement_id','-')} | {item.get('stage','-')} | {item.get('priority','-')} | {item.get('reason','-')} |\n"
        return res

    # 6. Summary
    if "summary" in q or "overall" in q:
        summary = get_reconciliation_summary()
        res = "### Reconciliation Summary\n\n"
        res += f"- **Total Settlements**: {summary.get('total_settlements', 0)}\n"
        res += f"- **Matched**: {summary.get('matched', 0)}\n"
        res += f"- **Manual Review**: {summary.get('manual_review', 0)}\n"
        res += f"- **Unmatched**: {summary.get('unmatched', 0)}\n"
        res += f"- **Match Rate**: {summary.get('match_rate', 0) * 100:.1f}%\n"
        res += f"- **Open Exceptions**: {summary.get('open_exceptions', 0)}\n"
        return res

    # 7. Settlement ID direct lookup
    match = re.search(r"setl_\d+", q)
    if match:
        setl_id = match.group(0)
        res_data = get_settlement(setl_id)
        if not res_data.get("found"):
            return f"Settlement `{setl_id}` was not found in the dataset."
        settlement = res_data.get("settlement", {})
        return (
            f"### Settlement {setl_id}\n\n"
            f"- **Amount**: ₹{settlement.get('amount', 0):,.2f}\n"
            f"- **Status**: `{res_data.get('overall_status')}`\n"
            f"- **Date**: {settlement.get('settlement_date')}\n"
            f"- **UTR**: `{settlement.get('utr', 'N/A')}`\n"
        )

    if q in {"hi", "hello", "hey", "help"}:
        summary = get_reconciliation_summary()
        return (
            f"Hello! I am Ledger's Settlement Q&A Agent.\n\n"
            f"Current status: **{summary.get('total_settlements', 0)} total settlements** "
            f"({summary.get('matched', 0)} matched, {summary.get('open_exceptions', 0)} open exceptions).\n\n"
            "You can ask me about:\n"
            "- *'Why is setl_0022 unmatched?'*\n"
            "- *'What is the current pipeline status?'*\n"
            "- *'Show current matching config'*\n"
            "- *'Compare June 2026 vs May 2026'*"
        )

    # General concept answer fallback (ungrounded label requirement)
    general_concepts = ["what is", "how does", "define", "explain concept", "reconciliation in general", "chargeback", "two-way", "3-way", "utr code"]
    if any(c in q for c in general_concepts):
        return (
            "General answer — not verified against your ledger data\n\n"
            "Payment reconciliation is the process of matching transaction records from internal sales/orders, payment gateways, and bank statement credits to verify that expected funds have been deposited correctly."
        )

    # 8. Universal search fallback — try searching all data by the raw query
    # This catches order IDs (ORD-5007), UTR numbers, UPI refs, narrations, etc.
    search_result = search_by_keyword_or_identifier(question)
    if search_result.get("found"):
        stats = search_result.get("stats", {})
        res = f"### Search Results for `{search_result.get('query')}`\n\n"
        res += f"- **Total Records Found**: {stats.get('total_records_found', 0)}\n"
        res += f"- **Settlements**: {stats.get('settlements_count', 0)}\n"
        res += f"- **Bank Transactions**: {stats.get('bank_transactions_count', 0)}\n"
        res += f"- **Internal Orders**: {stats.get('internal_orders_count', 0)}\n"
        res += f"- **Match Rate**: {stats.get('reconciliation_match_rate', '0%')}\n"
        res += f"- **Settlement Amount**: ₹{stats.get('total_settlement_amount', 0):,.2f}\n"
        res += f"- **Bank Credit Amount**: ₹{stats.get('total_bank_credit_amount', 0):,.2f}\n"
        res += f"- **Variance**: ₹{stats.get('net_amount_variance', 0):,.2f}\n"
        res += f"- **Open Exceptions**: {stats.get('open_exceptions_count', 0)}\n"

        # Show settlement details
        settlements = search_result.get("settlements", [])
        if settlements:
            res += "\n**Settlements:**\n"
            for s in settlements[:5]:
                s_rec = s.get("settlement", {})
                res += f"- `{s_rec.get('settlement_id')}` — ₹{s_rec.get('amount', 0):,.2f} — Status: `{s.get('overall_status')}`\n"

        # Show bank transaction details
        bank_txns = search_result.get("bank_transactions", [])
        if bank_txns:
            res += "\n**Bank Transactions:**\n"
            for b in bank_txns[:5]:
                b_rec = b.get("bank_transaction", {})
                res += f"- `{b_rec.get('bank_transaction_id')}` — ₹{b_rec.get('amount') or b_rec.get('Credit (INR)', 0):,.2f}\n"

        # Show internal order details
        orders = search_result.get("internal_orders", [])
        if orders:
            res += "\n**Internal Orders:**\n"
            for o in orders[:5]:
                o_rec = o.get("order", {})
                res += f"- `{o_rec.get('order_id')}` — ₹{o_rec.get('amount', 0):,.2f}\n"

        return res

    return (
        "I searched across all reconciliation data (settlements, bank transactions, orders) "
        "but couldn't find any matching records. Try providing a specific settlement ID (setl_XXXX), "
        "bank transaction ID (bank_XXXX), order ID, UTR number, or amount to search for."
    )


def answer_question(
    question,
    conversation_history=None,
):
    """
    Ask the Settlement Q&A Agent a question.
    Calls Groq LLM with tools if GROQ_API_KEY is valid, otherwise uses direct backend queries.
    """
    try:
        from llm import get_all_groq_keys, get_groq_model
        keys = get_all_groq_keys()
        if not keys:
            return fallback_direct_query(question)

        last_err = None
        for api_key in keys:
            try:
                client = Groq(api_key=api_key)
                model_name = get_groq_model()

                messages = [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    }
                ]

                if conversation_history:
                    messages.extend(conversation_history)

                messages.append(
                    {
                        "role": "user",
                        "content": question,
                    }
                )

                tool_executed = False

                while True:
                    response = client.chat.completions.create(
                        model=model_name,
                        temperature=0,
                        tools=TOOLS,
                        tool_choice="auto",
                        messages=messages,
                    )

                    message = response.choices[0].message

                    if not message.tool_calls:
                        content = message.content.strip() if message.content else "I could not produce an answer."
                        # If no tools executed and general concept question, ensure visual label is present
                        if not tool_executed and any(term in question.lower() for term in ["what is", "how does", "define", "in general", "chargeback", "reconciliation concept"]):
                            if "general answer" not in content.lower():
                                content = "General answer — not verified against your ledger data\n\n" + content
                        return content

                    tool_executed = True

                    messages.append(
                        {
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.function.name,
                                        "arguments": tool_call.function.arguments,
                                    },
                                }
                                for tool_call in message.tool_calls
                            ],
                        }
                    )

                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        arguments = json.loads(tool_call.function.arguments)
                        result = execute_tool(function_name, arguments)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(result, default=str),
                            }
                        )
            except Exception as exc:
                last_err = exc
                continue

        return fallback_direct_query(question)
    except Exception as exc:
        print(f"[Settlement Q&A Agent Note] LLM call note: {exc}")
        return fallback_direct_query(question)


# ============================================================
# CLI
# ============================================================

def main():

    print("=" * 60)
    print("LEDGER - SETTLEMENT Q&A AGENT")
    print("=" * 60)

    print()
    print("Ask questions about settlements, bank transactions,")
    print("reconciliation status, and exceptions.")
    print("Type 'exit' to quit.")
    print()

    conversation_history = []

    while True:

        try:
            question = input("You: ").strip()

        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        if question.lower() in {
            "exit",
            "quit",
        }:
            break

        try:
            answer = answer_question(
                question,
                conversation_history,
            )

            conversation_history.append(
                {
                    "role": "user",
                    "content": question,
                }
            )

            conversation_history.append(
                {
                    "role": "assistant",
                    "content": answer,
                }
            )

        except Exception as exc:
            answer = (
                "I could not safely complete this query. "
                f"Technical error: {exc}"
            )

        print()
        print("Ledger:", answer)
        print()

if __name__ == "__main__":
    main()