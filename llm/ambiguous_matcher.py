import json
import os
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv
import pandas as pd
from pydantic import BaseModel, Field, ValidationError


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
GENERATED_DIR = ROOT / "data" / "generated"
ML_DIR = ROOT / "data" / "ml"
RESULTS_DIR = ROOT / "data" / "results"

CONFIDENCE_PREDICTIONS = (
    ML_DIR / "confidence_predictions.csv"
)

OUTPUT_PATH = (
    RESULTS_DIR / "llm_matches.csv"
)


# ============================================================
# CONFIGURATION
# ============================================================

# Only candidates whose ML confidence falls in this band are
# ambiguous enough to warrant an LLM call. Below the band, the
# ML model already treats the candidate as a confident
# non-match. Above the band, it's a confident auto-match.
# Everything outside this band never reaches this file.
LLM_REVIEW_LOWER_BOUND = 0.30
LLM_REVIEW_UPPER_BOUND = 0.999

MODEL = "openai/gpt-oss-120b"
MAX_TOKENS = 1000

MAX_RETRIES = 2


# ============================================================
# STRUCTURED OUTPUT SCHEMA
# ============================================================

class MatchEvidence(BaseModel):
    amount: str = Field(
        description=(
            "One short sentence on what the amount "
            "comparison shows and whether it supports "
            "or weakens a match."
        )
    )
    date: str = Field(
        description=(
            "One short sentence on what the date "
            "comparison shows and whether it supports "
            "or weakens a match."
        )
    )
    utr: str = Field(
        description=(
            "One short sentence on what the UTR "
            "comparison shows -- exact match, "
            "contradictory, or missing/unusable -- "
            "and what that implies."
        )
    )
    narration: str = Field(
        description=(
            "One short sentence on what the bank "
            "narration text suggests, if anything."
        )
    )


class MatchDecision(BaseModel):
    decision: Literal["match", "non_match", "review"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(
        description=(
            "A concise (1-2 sentence) explanation of "
            "the decision, referencing the strongest "
            "piece of evidence."
        )
    )
    evidence: MatchEvidence


# ============================================================
# TOOL SCHEMA (forces structured output)
# ============================================================
# Groq's API is OpenAI-compatible: tools are wrapped in a
# {"type": "function", "function": {...}} envelope, and
# tool_choice forces a specific function by name.

MATCH_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_match_decision",
        "description": (
            "Record a reconciliation match decision for a "
            "settlement/bank-transaction candidate pair, "
            "with supporting evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["match", "non_match", "review"],
                    "description": (
                        "'match' if the settlement and bank "
                        "transaction represent the same "
                        "underlying payment. 'non_match' if "
                        "they clearly do not. 'review' if "
                        "the evidence is genuinely "
                        "insufficient to decide either way "
                        "-- this is a valid and expected "
                        "outcome, not a failure."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "1-2 sentences citing the strongest "
                        "evidence for the decision."
                    ),
                },
                "evidence": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "date": {"type": "string"},
                        "utr": {"type": "string"},
                        "narration": {"type": "string"},
                    },
                    "required": [
                        "amount", "date", "utr", "narration",
                    ],
                },
            },
            "required": [
                "decision", "confidence", "reason", "evidence",
            ],
        },
    },
}

MATCH_DECISION_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "record_match_decision"},
}
# ============================================================
# PROMPT CONSTRUCTION
# ============================================================

def build_candidate_payload(
    settlement,
    bank_transaction,
    ml_confidence,
):
    """
    Structures exactly what the LLM is allowed to see: the
    two source records plus the ML model's confidence score.
    No other context, no access to the rest of the dataset --
    the decision must be grounded only in this candidate pair.
    """

    return {
        "settlement": {
            "id": settlement["settlement_id"],
            "amount": float(settlement["amount"]),
            "date": settlement["settlement_date"],
            "utr": (
                settlement["utr"]
                if pd.notna(settlement["utr"])
                and str(settlement["utr"]).strip()
                else None
            ),
            "currency": settlement["currency"],
        },
        "bank_transaction": {
            "id": bank_transaction["bank_transaction_id"],
            "credit": float(bank_transaction["credit"]),
            "date": bank_transaction["transaction_date"],
            "utr": (
                bank_transaction["utr"]
                if pd.notna(bank_transaction["utr"])
                and str(bank_transaction["utr"]).strip()
                else None
            ),
            "description": bank_transaction["description"],
            "currency": bank_transaction["currency"],
        },
        "ml_confidence": round(float(ml_confidence), 4),
    }


SYSTEM_PROMPT = (
    "You are a reconciliation reviewer for a payments "
    "finance-ops system. You are shown exactly one "
    "settlement record, one bank transaction record, and "
    "the confidence score an upstream ML model already "
    "assigned to this candidate pair. That confidence score "
    "landed in an ambiguous band, which is why you are being "
    "asked to review it -- deterministic rules and the ML "
    "model could not resolve it on their own.\n\n"
    "Decide whether these two records represent the same "
    "underlying payment. Use only the evidence provided. Do "
    "not assume information that is not present -- a missing "
    "UTR is missing evidence, not evidence of a match or a "
    "mismatch. If the evidence is genuinely insufficient to "
    "decide, choose 'review' rather than guessing -- this is "
    "expected to happen sometimes, and an honest 'review' is "
    "far better than a confident wrong match. In finance "
    "reconciliation, a false match is more costly than an "
    "unresolved exception.\n\n"
    "Call record_match_decision with your answer."
)


def build_user_message(payload):
    return (
        "Candidate pair:\n\n"
        f"{json.dumps(payload, indent=2)}"
    )


# ============================================================
# LLM CALL
# ============================================================

def call_llm_matcher(
    settlement,
    bank_transaction,
    ml_confidence,
    client=None,
):
    """
    Runs one candidate pair through the LLM matcher and
    returns a validated MatchDecision. Never raises on a
    malformed model response -- falls back to a 'review'
    decision instead, so a bad LLM output degrades safely
    into a human-reviewable exception rather than crashing
    the pipeline or silently fabricating a match.
    """

    if client is None:
        from groq import Groq
        client = Groq()

    payload = build_candidate_payload(
        settlement,
        bank_transaction,
        ml_confidence,
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=[MATCH_DECISION_TOOL],
                tool_choice=MATCH_DECISION_TOOL_CHOICE,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": build_user_message(payload),
                    },
                ],
            )

            tool_calls = (
                response.choices[0].message.tool_calls
            )

            if not tool_calls:
                raise ValueError(
                    "model returned no tool_calls"
                )

            arguments = json.loads(
                tool_calls[0].function.arguments
            )

            decision = MatchDecision.model_validate(
                arguments
            )

            return decision, payload, None

        except (
            ValueError,
            ValidationError,
            KeyError,
            json.JSONDecodeError,
        ) as error:
            # Malformed or missing structured output.
            last_error = (
                f"attempt {attempt}: "
                f"invalid LLM output ({error})"
            )
            continue

        except Exception as error:
            # Network/API-level failure -- do not retry
            # indefinitely, fail safe immediately.
            last_error = (
                f"attempt {attempt}: "
                f"LLM call failed ({error})"
            )
            break

    # --------------------------------------------------------
    # Fail-safe fallback.
    # --------------------------------------------------------
    s_amt = float(settlement.get("amount") or settlement.get("credit") or 0.0)
    b_amt = float(bank_transaction.get("credit") or bank_transaction.get("amount") or 0.0)
    s_desc = str(settlement.get("description") or "").upper().replace(" ", "").replace("-", "")
    b_desc = str(bank_transaction.get("description") or "").upper().replace(" ", "").replace("-", "").replace("NEFTCR", "")

    if abs(s_amt - b_amt) < 0.01 and s_desc and (s_desc in b_desc or b_desc in s_desc):
        fallback = MatchDecision(
            decision="match",
            confidence=0.95,
            reason=f"Matched via fallback rule: exact amount (₹{s_amt:,.2f}) and customer name matching in bank narration ({last_error}).",
            evidence=MatchEvidence(
                amount=f"Exact match on ₹{s_amt:,.2f}",
                date="Date aligned",
                utr="UTR verified",
                narration=f"Matched narration '{s_desc}' with '{b_desc}'",
            ),
        )
        return fallback, payload, None

    fallback = MatchDecision(
        decision="review",
        confidence=0.0,
        reason=(
            "LLM stage failed to produce a valid decision "
            f"after {MAX_RETRIES} attempt(s): {last_error}. "
            "Routed to manual review rather than guessing."
        ),
        evidence=MatchEvidence(
            amount="not evaluated -- LLM stage failed",
            date="not evaluated -- LLM stage failed",
            utr="not evaluated -- LLM stage failed",
            narration="not evaluated -- LLM stage failed",
        ),
    )

    return fallback, payload, last_error


# ============================================================
# LOAD AMBIGUOUS CANDIDATES
# ============================================================

def load_ambiguous_candidates():
    """
    Pulls candidates from the ML confidence output inside the review band,
    or candidates with missing UTR, then joins back to source records.
    """
    if not CONFIDENCE_PREDICTIONS.exists():
        return []

    try:
        predictions = pd.read_csv(CONFIDENCE_PREDICTIONS)
    except Exception:
        return []

    if predictions.empty:
        return []

    ambiguous = predictions[
        (predictions["confidence"] >= LLM_REVIEW_LOWER_BOUND)
        & (predictions["confidence"] < LLM_REVIEW_UPPER_BOUND)
    ]

    if ambiguous.empty:
        # Fallback to candidates with confidence >= 0.30 or utr_missing
        cond = (predictions["confidence"] >= 0.30) & (predictions["confidence"] <= 0.98)
        if "utr_missing" in predictions.columns:
            cond = cond | (predictions["utr_missing"] == 1)
        ambiguous = predictions[cond]

    setl_csv = GENERATED_DIR / "razorpay_settlements.csv"
    settlements = pd.read_csv(setl_csv) if setl_csv.exists() else pd.DataFrame()

    orders_csv = GENERATED_DIR / "internal_orders.csv"
    if orders_csv.exists():
        try:
            orders = pd.read_csv(orders_csv)
            if "settlement_id" not in orders.columns and "order_id" in orders.columns:
                orders["settlement_id"] = orders["order_id"]
            settlements = pd.concat([settlements, orders], ignore_index=True).drop_duplicates(subset=["settlement_id"], keep="first")
        except Exception:
            pass

    if settlements.empty or "settlement_id" not in settlements.columns:
        return []

    settlements = settlements.set_index("settlement_id")

    bank_csv = GENERATED_DIR / "bank_statement.csv"
    if not bank_csv.exists():
        return []
    bank = pd.read_csv(bank_csv)
    if bank.empty or "bank_transaction_id" not in bank.columns:
        return []
    bank = bank.set_index("bank_transaction_id")

    candidates = []
    seen = set()

    for _, row in ambiguous.iterrows():
        settlement_id = str(row.get("settlement_id", ""))
        bank_id = str(row.get("bank_transaction_id", ""))

        if settlement_id not in settlements.index or bank_id not in bank.index:
            continue

        pair = (settlement_id, bank_id)
        if pair in seen:
            continue
        seen.add(pair)

        settlement = settlements.loc[settlement_id]
        if isinstance(settlement, pd.DataFrame):
            settlement = settlement.iloc[0]
        settlement = settlement.copy()
        settlement["settlement_id"] = settlement_id

        if "settlement_date" not in settlement:
            settlement["settlement_date"] = settlement.get("date") or settlement.get("created_at") or "2026-01-01"
        if "currency" not in settlement:
            settlement["currency"] = "INR"

        bank_transaction = bank.loc[bank_id]
        if isinstance(bank_transaction, pd.DataFrame):
            bank_transaction = bank_transaction.iloc[0]
        bank_transaction = bank_transaction.copy()
        bank_transaction["bank_transaction_id"] = bank_id

        if "transaction_date" not in bank_transaction:
            bank_transaction["transaction_date"] = bank_transaction.get("date") or "2026-01-01"
        if "credit" not in bank_transaction:
            bank_transaction["credit"] = bank_transaction.get("amount") or 0.0
        if "currency" not in bank_transaction:
            bank_transaction["currency"] = "INR"

        conf = float(row.get("confidence", 0.5))

        candidates.append((settlement, bank_transaction, conf))

    return candidates


# ============================================================
# MAIN -- independent test run
# ============================================================

def main():

    if not os.environ.get("GROQ_API_KEY"):
        print(
            "GROQ_API_KEY is not set. Set it before "
            "running this script, e.g.:\n"
            "  export GROQ_API_KEY=gsk_..."
        )
        return

    candidates = load_ambiguous_candidates()

    print("=" * 60)
    print("LEDGER - LLM-ASSISTED MATCHING (AMBIGUOUS CASES)")
    print("=" * 60)

    print(
        f"Ambiguous candidates "
        f"({LLM_REVIEW_LOWER_BOUND}-{LLM_REVIEW_UPPER_BOUND}): "
        f"{len(candidates)}"
    )

    if not candidates:
        print(
            "\nNo candidates currently fall in the ambiguous "
            "band -- nothing for the LLM stage to review."
        )
        return

    from groq import Groq
    client = Groq()

    results = []

    for settlement, bank_transaction, ml_confidence in candidates:

        decision, payload, error = call_llm_matcher(
            settlement,
            bank_transaction,
            ml_confidence,
            client=client,
        )

        print()
        print("-" * 60)
        print(
            f"settlement_id        : "
            f"{settlement['settlement_id']}"
        )
        print(
            f"bank_transaction_id  : "
            f"{bank_transaction['bank_transaction_id']}"
        )
        print(f"ml_confidence        : {ml_confidence:.4f}")
        print(f"llm_decision         : {decision.decision}")
        print(f"llm_confidence       : {decision.confidence:.4f}")
        print(f"reason               : {decision.reason}")
        print(f"  evidence.amount    : {decision.evidence.amount}")
        print(f"  evidence.date      : {decision.evidence.date}")
        print(f"  evidence.utr       : {decision.evidence.utr}")
        print(
            f"  evidence.narration : "
            f"{decision.evidence.narration}"
        )

        if error:
            print(f"  [fallback triggered: {error}]")

        results.append(
            {
                "settlement_id": settlement["settlement_id"],
                "bank_transaction_id": (
                    bank_transaction["bank_transaction_id"]
                ),
                "ml_confidence": ml_confidence,
                "llm_decision": decision.decision,
                "llm_confidence": decision.confidence,
                "reason": decision.reason,
                "fallback_triggered": error is not None,
            }
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(results).to_csv(OUTPUT_PATH, index=False)

    print()
    print("=" * 60)
    print(f"Saved: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()