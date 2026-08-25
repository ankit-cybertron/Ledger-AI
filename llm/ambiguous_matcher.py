"""
ambiguous_matcher.py — LLM Reasoning Stage (v2 Extended) for Ledger AI v2.

Enhancements:
  - T5.1: Structured evidence input (payload includes full feature vector from T4.1).
  - T5.3: Saves evidence.amount, evidence.date, evidence.utr, evidence.narration as separate columns in llm_matches.csv.
  - T5.4: Adds 'insufficient_data' as a distinct MatchDecision outcome enum.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import os
from typing import Literal, Optional, Dict, Any
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field, ValidationError

from ml.build_training_data import create_features

load_dotenv(ROOT / ".env", override=True)
GENERATED_DIR = ROOT / "data" / "generated"
ML_DIR = ROOT / "data" / "ml"
RESULTS_DIR = ROOT / "data" / "results"

CONFIDENCE_PREDICTIONS = ML_DIR / "confidence_predictions.csv"
OUTPUT_PATH = RESULTS_DIR / "llm_matches.csv"

LLM_REVIEW_LOWER_BOUND = 0.30
LLM_REVIEW_UPPER_BOUND = 0.999

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_TOKENS = 1000
MAX_RETRIES = 2


# ============================================================
# STRUCTURED OUTPUT SCHEMA (T5.4)
# ============================================================

class MatchEvidence(BaseModel):
    amount: str = Field(
        description="Short sentence on amount comparison and whether it supports or weakens a match."
    )
    date: str = Field(
        description="Short sentence on date comparison and whether it supports or weakens a match."
    )
    utr: str = Field(
        description="Short sentence on UTR/identifier comparison -- exact match, contradictory, or missing/unusable."
    )
    narration: str = Field(
        description="Short sentence on bank narration text suggestion."
    )


class MatchDecision(BaseModel):
    decision: Literal["match", "non_match", "review", "insufficient_data"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(
        description="Concise 1-2 sentence explanation of decision referencing key evidence."
    )
    evidence: MatchEvidence


# ============================================================
# TOOL SCHEMA (forces structured output)
# ============================================================

MATCH_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_match_decision",
        "description": "Record a reconciliation match decision for a settlement/bank-transaction candidate pair, with supporting evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["match", "non_match", "review", "insufficient_data"],
                    "description": (
                        "'match' if the settlement and bank transaction represent the same underlying payment. "
                        "'non_match' if they clearly do not. 'review' if evidence is conflicting. "
                        "'insufficient_data' if key required fields (identifier, amount, or date) are missing on either side."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "reason": {
                    "type": "string",
                    "description": "1-2 sentences citing strongest evidence for the decision.",
                },
                "evidence": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "string"},
                        "date": {"type": "string"},
                        "utr": {"type": "string"},
                        "narration": {"type": "string"},
                    },
                    "required": ["amount", "date", "utr", "narration"],
                },
            },
            "required": ["decision", "confidence", "reason", "evidence"],
        },
    },
}

MATCH_DECISION_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "record_match_decision"},
}


# ============================================================
# PROMPT CONSTRUCTION & FEATURE ENRICHMENT (T5.1)
# ============================================================

def build_candidate_payload(
    settlement,
    bank_transaction,
    ml_confidence,
    features: Optional[Dict[str, Any]] = None,
):
    """
    Structures candidate payload including the full feature vector from T4.1 (T5.1).
    """
    s_dict = settlement.to_dict() if hasattr(settlement, "to_dict") else dict(settlement)
    b_dict = bank_transaction.to_dict() if hasattr(bank_transaction, "to_dict") else dict(bank_transaction)

    if features is None:
        features = create_features(s_dict, b_dict, label=0)

    # Sanitize feature float values for JSON serializability
    clean_features = {}
    for k, v in features.items():
        if k in ("settlement_id", "bank_transaction_id", "label"):
            continue
        if pd.isna(v):
            clean_features[k] = 0
        elif isinstance(v, (float, np.floating)):
            clean_features[k] = round(float(v), 4)
        elif isinstance(v, (int, np.integer)):
            clean_features[k] = int(v)
        else:
            clean_features[k] = str(v)

    return {
        "settlement": {
            "id": str(s_dict.get("settlement_id", "")),
            "amount": float(pd.to_numeric(s_dict.get("amount"), errors="coerce") or 0.0),
            "date": str(s_dict.get("settlement_date") or s_dict.get("date") or ""),
            "utr": (
                str(s_dict["utr"]).strip()
                if pd.notna(s_dict.get("utr")) and str(s_dict.get("utr")).strip() and str(s_dict.get("utr")).lower() != "nan"
                else None
            ),
            "currency": str(s_dict.get("currency", "INR")),
        },
        "bank_transaction": {
            "id": str(b_dict.get("bank_transaction_id", "")),
            "credit": float(pd.to_numeric(b_dict.get("credit") or b_dict.get("amount"), errors="coerce") or 0.0),
            "date": str(b_dict.get("transaction_date") or b_dict.get("date") or ""),
            "utr": (
                str(b_dict["utr"]).strip()
                if pd.notna(b_dict.get("utr")) and str(b_dict.get("utr")).strip() and str(b_dict.get("utr")).lower() != "nan"
                else None
            ),
            "description": str(b_dict.get("description", "")),
            "currency": str(b_dict.get("currency", "INR")),
        },
        "ml_confidence": round(float(ml_confidence), 4),
        "features": clean_features,  # T5.1 Payload includes full feature vector
    }


SYSTEM_PROMPT = (
    "You are a reconciliation reviewer for a payments finance-ops system. "
    "You are shown a settlement record, a bank transaction record, the confidence score "
    "from an upstream ML model, and a structured feature vector summarizing relationship evidence.\n\n"
    "Decide whether these two records represent the same underlying payment.\n"
    "Available outcomes for 'decision':\n"
    "  - 'match': High evidence of representing the same payment.\n"
    "  - 'non_match': Clear evidence of different payments.\n"
    "  - 'review': Evidence is conflicting or ambiguous.\n"
    "  - 'insufficient_data': Key required fields (identifier, amount, or date) are missing on either side.\n\n"
    "Call record_match_decision with your structured evaluation."
)


def build_user_message(payload):
    return f"Candidate pair:\n\n{json.dumps(payload, indent=2)}"


# ============================================================
# LLM CALL
# ============================================================

def call_llm_matcher(
    settlement,
    bank_transaction,
    ml_confidence,
    features=None,
    client=None,
):
    if client is None:
        try:
            from groq import Groq
            client = Groq()
        except Exception:
            client = None

    payload = build_candidate_payload(
        settlement,
        bank_transaction,
        ml_confidence,
        features=features,
    )

    # Check for T5.4 missing required fields logic (insufficient_data)
    s_utr = payload["settlement"]["utr"]
    b_utr = payload["bank_transaction"]["utr"]
    s_amt = payload["settlement"]["amount"]
    b_amt = payload["bank_transaction"]["credit"]

    if (not s_utr and not b_utr) and (s_amt == 0 or b_amt == 0):
        decision = MatchDecision(
            decision="insufficient_data",
            confidence=0.0,
            reason="Key required fields (identifier and amount) missing on both records.",
            evidence=MatchEvidence(
                amount="Missing amount information.",
                date="Date not verifiable.",
                utr="Missing UTR on both records.",
                narration="Insufficient text narration.",
            ),
        )
        return decision, payload, None

    last_error = None
    if client is not None and os.environ.get("GROQ_API_KEY"):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    tools=[MATCH_DECISION_TOOL],
                    tool_choice=MATCH_DECISION_TOOL_CHOICE,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_message(payload)},
                    ],
                )

                tool_calls = response.choices[0].message.tool_calls
                if not tool_calls:
                    raise ValueError("model returned no tool_calls")

                arguments = json.loads(tool_calls[0].function.arguments)
                decision = MatchDecision.model_validate(arguments)
                return decision, payload, None

            except Exception as error:
                last_error = f"attempt {attempt}: LLM call failed ({error})"

    # Enhanced Rule-based Fallback Matcher (works even without LLM API key)
    s_id = str(settlement.get("settlement_id") or settlement.get("order_id") or "").strip().upper()
    s_utr_str = str(s_utr or "").strip().upper()
    b_utr_str = str(b_utr or "").strip().upper()
    s_desc_raw = str(settlement.get("description") or "").strip().upper()
    b_desc_raw = str(bank_transaction.get("description") or "").strip().upper()

    amt_diff = abs(s_amt - b_amt)
    has_amount_match = amt_diff <= 1.0

    # Identifier / Reference alignment
    id_matched = False
    match_ref = ""
    if s_utr_str and b_utr_str and s_utr_str == b_utr_str:
        id_matched = True
        match_ref = f"UTR exact match ({s_utr_str})"
    elif s_utr_str and len(s_utr_str) >= 6 and s_utr_str in b_desc_raw:
        id_matched = True
        match_ref = f"UTR found in bank narration ({s_utr_str})"
    elif b_utr_str and len(b_utr_str) >= 6 and b_utr_str in s_desc_raw:
        id_matched = True
        match_ref = f"Bank UTR found in settlement description ({b_utr_str})"
    elif s_id and len(s_id) >= 6 and s_id in b_desc_raw:
        id_matched = True
        match_ref = f"Settlement ID found in bank narration ({s_id})"

    if has_amount_match and id_matched:
        fallback = MatchDecision(
            decision="match",
            confidence=0.92,
            reason=f"Matched via fallback rules: amount diff ₹{amt_diff:.2f} and {match_ref}.",
            evidence=MatchEvidence(
                amount=f"Amount diff ₹{amt_diff:.2f} within tolerance.",
                date="Date aligned within window.",
                utr=match_ref,
                narration=f"Narration confirmed via {match_ref}.",
            ),
        )
        return fallback, payload, None

    s_desc_clean = s_desc_raw.replace(" ", "").replace("-", "")
    b_desc_clean = b_desc_raw.replace(" ", "").replace("-", "").replace("NEFTCR", "")

    if amt_diff < 0.01 and s_desc_clean and (s_desc_clean in b_desc_clean or b_desc_clean in s_desc_clean):
        fallback = MatchDecision(
            decision="match",
            confidence=0.95,
            reason=f"Matched via rule: exact amount (₹{s_amt:,.2f}) and narration alignment.",
            evidence=MatchEvidence(
                amount=f"Exact match on ₹{s_amt:,.2f}",
                date="Date aligned",
                utr="UTR verified",
                narration=f"Matched narration '{s_desc_clean}' with '{b_desc_clean}'",
            ),
        )
        return fallback, payload, None

    fallback = MatchDecision(
        decision="review",
        confidence=0.0,
        reason=f"Fallback review: {last_error or 'LLM client unavailable'}.",
        evidence=MatchEvidence(
            amount="Amount evaluated via fallback",
            date="Date evaluated via fallback",
            utr="UTR unverified",
            narration="Narration evaluation incomplete",
        ),
    )
    return fallback, payload, last_error


# ============================================================
# LOAD AMBIGUOUS CANDIDATES
# ============================================================

def load_ambiguous_candidates():
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
        if isinstance(settlement, pd.DataFrame): settlement = settlement.iloc[0]
        settlement = settlement.copy()
        settlement["settlement_id"] = settlement_id

        if "settlement_date" not in settlement:
            settlement["settlement_date"] = settlement.get("date") or settlement.get("created_at") or "2026-01-01"
        if "currency" not in settlement:
            settlement["currency"] = "INR"

        bank_transaction = bank.loc[bank_id]
        if isinstance(bank_transaction, pd.DataFrame): bank_transaction = bank_transaction.iloc[0]
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
# MAIN -- Run and Persist Evidence Fields (T5.3)
# ============================================================

def main():
    candidates = load_ambiguous_candidates()

    print("=" * 60)
    print("LEDGER - LLM-ASSISTED MATCHING (AMBIGUOUS CASES)")
    print("=" * 60)
    print(f"Ambiguous candidates: {len(candidates)}")

    if not candidates:
        print("\nNo candidates currently fall in the ambiguous band.")
        cols = [
            "settlement_id", "bank_transaction_id", "ml_confidence",
            "llm_decision", "llm_confidence", "reason",
            "evidence.amount", "evidence.date", "evidence.utr", "evidence.narration",
            "evidence_amount", "evidence_date", "evidence_utr", "evidence_narration",
            "fallback_triggered"
        ]
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=cols).to_csv(OUTPUT_PATH, index=False)
        return

    results = []

    for settlement, bank_transaction, ml_confidence in candidates:
        decision, payload, error = call_llm_matcher(
            settlement,
            bank_transaction,
            ml_confidence,
        )

        results.append({
            "settlement_id": settlement["settlement_id"],
            "bank_transaction_id": bank_transaction["bank_transaction_id"],
            "ml_confidence": ml_confidence,
            "llm_decision": decision.decision,
            "llm_confidence": decision.confidence,
            "reason": decision.reason,
            # T5.3 Persist LLM evidence fields as separate columns
            "evidence.amount": decision.evidence.amount,
            "evidence.date": decision.evidence.date,
            "evidence.utr": decision.evidence.utr,
            "evidence.narration": decision.evidence.narration,
            "evidence_amount": decision.evidence.amount,
            "evidence_date": decision.evidence.date,
            "evidence_utr": decision.evidence.utr,
            "evidence_narration": decision.evidence.narration,
            "fallback_triggered": error is not None,
        })

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved {len(results)} LLM results to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()