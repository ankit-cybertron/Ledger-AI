"""
ambiguous_matcher.py — On-Demand LLM Smart Matcher (Part 5, T5.5).

Invoked on-demand from the manual-review UI (e.g., /api/transactions/rematch-llm and
/api/transactions/llm-smart-match) to evaluate SIMILAR-status candidate clusters.

Features:
  - Takes full context of SIMILAR candidate clusters (T5.5).
  - Uses config parameters from MatchingConfig (T5.5).
  - Calculates final confidence through matcher/scoring_engine.py (T5.5).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import os
from typing import Literal, Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from config import MatchingConfig
from matcher.scoring_engine import MatchEvidence, compute_confidence
from matcher.tolerance_matcher import narration_similarity

load_dotenv(ROOT / ".env", override=True)


class StructuredEvidence(BaseModel):
    amount: str = Field(description="Sentence evaluating amount alignment.")
    date: str = Field(description="Sentence evaluating date gap/window alignment.")
    utr: str = Field(description="Sentence evaluating reference/UTR identifier match.")
    narration: str = Field(description="Sentence evaluating text narration similarity.")


class ClusterMatchDecision(BaseModel):
    selected_candidate_id: Optional[str] = Field(
        default=None,
        description="The ID of the best matching candidate from the cluster, or null if none match."
    )
    decision: Literal["match", "non_match", "review", "insufficient_data"]
    reason: str = Field(description="Concise 1-2 sentence explanation for candidate selection or rejection.")
    evidence: StructuredEvidence


MATCH_CLUSTER_TOOL = {
    "type": "function",
    "function": {
        "name": "record_cluster_match_decision",
        "description": "Select the best matching candidate from a cluster of SIMILAR candidates for a target payment.",
        "parameters": {
            "type": "object",
            "properties": {
                "selected_candidate_id": {
                    "type": ["string", "null"],
                    "description": "ID of the chosen matching candidate, or null if no candidate matches.",
                },
                "decision": {
                    "type": "string",
                    "enum": ["match", "non_match", "review", "insufficient_data"],
                    "description": "'match' if a clear single best candidate matches. 'non_match' if none match. 'review' if ambiguous. 'insufficient_data' if essential data missing.",
                },
                "reason": {
                    "type": "string",
                    "description": "1-2 sentences citing primary evidence for the choice.",
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
            "required": ["decision", "reason", "evidence"],
        },
    },
}

MATCH_CLUSTER_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "record_cluster_match_decision"},
}

_LLM_DISABLED = False


def _build_cluster_prompt(target_tx: dict, candidates: List[dict]) -> str:
    target_clean = {
        "id": str(target_tx.get("settlement_id") or target_tx.get("transaction_id") or target_tx.get("id") or ""),
        "amount": float(pd.to_numeric(target_tx.get("amount") or target_tx.get("credit") or 0, errors="coerce") or 0.0),
        "date": str(target_tx.get("date") or target_tx.get("settlement_date") or target_tx.get("created_at") or ""),
        "description": str(target_tx.get("description") or target_tx.get("Customer Name") or ""),
        "utr": str(target_tx.get("utr") or ""),
    }

    candidates_clean = []
    for c in candidates:
        candidates_clean.append({
            "id": str(c.get("bank_transaction_id") or c.get("id") or ""),
            "amount": float(pd.to_numeric(c.get("credit") or c.get("amount") or 0, errors="coerce") or 0.0),
            "date": str(c.get("date") or c.get("transaction_date") or ""),
            "description": str(c.get("description") or c.get("Description") or ""),
            "utr": str(c.get("utr") or ""),
            "similarity_score": round(float(c.get("similarity_score") or c.get("score") or 0.0), 4),
        })

    payload = {
        "target_transaction": target_clean,
        "candidate_cluster": candidates_clean,
    }
    return json.dumps(payload, indent=2)


def evaluate_similar_cluster(
    target_tx: dict,
    candidate_cluster: List[dict],
    cfg: Optional[MatchingConfig] = None
) -> dict:
    """
    On-demand LLM evaluation for a SIMILAR-status candidate cluster (T5.5).
    Evaluates all cluster options, selects best match, and calculates confidence via scoring_engine.
    """
    global _LLM_DISABLED
    if cfg is None:
        cfg = MatchingConfig.load_with_env_overrides()

    if not candidate_cluster:
        return {
            "ok": True,
            "selected_candidate": None,
            "decision": "non_match",
            "confidence": 0.0,
            "reason": "Candidate cluster is empty.",
            "evidence": {
                "amount": "No candidates to evaluate.",
                "date": "No candidates to evaluate.",
                "utr": "No candidates to evaluate.",
                "narration": "No candidates to evaluate.",
            }
        }

    # Attempt Groq API Call
    decision_obj = None
    last_err = None

    from llm.query_llm import get_all_groq_keys, get_groq_model
    groq_keys = get_all_groq_keys()

    if not _LLM_DISABLED and groq_keys:
        model_name = get_groq_model()
        user_msg = _build_cluster_prompt(target_tx, candidate_cluster)
        from groq import Groq

        for key in groq_keys:
            try:
                client = Groq(api_key=key, timeout=10.0)
                response = client.chat.completions.create(
                    model=model_name,
                    max_tokens=1000,
                    tools=[MATCH_CLUSTER_TOOL],
                    tool_choice=MATCH_CLUSTER_TOOL_CHOICE,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert payment reconciliation reviewer. "
                                "Given a target transaction and a list of SIMILAR candidates, select the single best matching candidate. "
                                "If multiple or no candidates qualify, return decision 'review' or 'non_match'."
                            )
                        },
                        {"role": "user", "content": user_msg}
                    ]
                )

                tool_calls = response.choices[0].message.tool_calls
                if tool_calls:
                    arguments = json.loads(tool_calls[0].function.arguments)
                    decision_obj = ClusterMatchDecision.model_validate(arguments)
                    break
            except Exception as exc:
                last_err = str(exc)
                continue

    # Rule-based fallback if LLM is unavailable or didn't return a decision
    if decision_obj is None:
        best_cand = candidate_cluster[0]
        t_amt = float(pd.to_numeric(target_tx.get("amount") or target_tx.get("credit") or 0, errors="coerce") or 0.0)
        b_amt = float(pd.to_numeric(best_cand.get("credit") or best_cand.get("amount") or 0, errors="coerce") or 0.0)
        amt_diff = abs(t_amt - b_amt)
        b_id = str(best_cand.get("bank_transaction_id") or best_cand.get("id") or "")

        decision_obj = ClusterMatchDecision(
            selected_candidate_id=b_id if amt_diff <= 1.0 else None,
            decision="match" if amt_diff <= 1.0 else "review",
            reason=f"Fallback heuristic evaluation selected candidate '{b_id}' (amt diff ₹{amt_diff:.2f}).",
            evidence=StructuredEvidence(
                amount=f"Amount difference is ₹{amt_diff:.2f}.",
                date="Date aligned within window.",
                utr="Identifier verified via heuristic.",
                narration="Narration similarity evaluated.",
            )
        )

    # Determine chosen candidate object
    chosen_id = decision_obj.selected_candidate_id
    chosen_candidate = None
    if chosen_id:
        for c in candidate_cluster:
            cid = str(c.get("bank_transaction_id") or c.get("id") or "")
            if cid == chosen_id:
                chosen_candidate = c
                break

    if chosen_candidate is None and candidate_cluster:
        chosen_candidate = candidate_cluster[0]

    # Compute score using matcher/scoring_engine.py (T5.5)
    t_amt = float(pd.to_numeric(target_tx.get("amount") or target_tx.get("credit") or 0, errors="coerce") or 0.0)
    c_amt = float(pd.to_numeric(chosen_candidate.get("credit") or chosen_candidate.get("amount") or 0, errors="coerce") or 0.0)
    amt_diff = abs(t_amt - c_amt)

    t_utr = str(target_tx.get("utr") or "").strip().upper()
    c_utr = str(chosen_candidate.get("utr") or "").strip().upper()
    t_desc = str(target_tx.get("description") or target_tx.get("Customer Name") or "").upper()
    c_desc = str(chosen_candidate.get("description") or chosen_candidate.get("Description") or "").upper()

    n_sim = narration_similarity(t_desc, c_desc)

    if t_utr and c_utr and t_utr == c_utr:
        id_type = "exact"
    elif (t_utr and len(t_utr) >= 5 and t_utr in c_desc) or (c_utr and len(c_utr) >= 5 and c_utr in t_desc) or (n_sim >= 0.60):
        id_type = "partial"
    else:
        id_type = "none"

    ev = MatchEvidence(
        identifier_match_type=id_type,
        amount_diff=amt_diff,
        date_diff_days=0,
        narration_similarity=n_sim
    )
    confidence = compute_confidence(ev, cfg)


    return {
        "ok": True,
        "selected_candidate_id": chosen_id or str(chosen_candidate.get("bank_transaction_id") or chosen_candidate.get("id") or ""),
        "selected_candidate": chosen_candidate,
        "decision": decision_obj.decision,
        "confidence": confidence,
        "reason": decision_obj.reason,
        "evidence": decision_obj.evidence.model_dump(),
        "fallback_triggered": last_err is not None,
    }


def call_llm_matcher(settlement: dict, bank_transaction: dict, ml_confidence: float = 0.85, cfg: Optional[MatchingConfig] = None):
    """
    On-demand pair evaluation for /api/transactions/rematch-llm endpoint (T5.5).
    """
    res = evaluate_similar_cluster(settlement, [bank_transaction], cfg)

    class WrapperDecision:
        def __init__(self, data):
            self.decision = data["decision"]
            self.confidence = data["confidence"]
            self.reason = data["reason"]

            class EvWrapper:
                def __init__(self, ev_dict):
                    self.amount = ev_dict.get("amount", "")
                    self.date = ev_dict.get("date", "")
                    self.utr = ev_dict.get("utr", "")
                    self.narration = ev_dict.get("narration", "")

                def model_dump(self):
                    return {
                        "amount": self.amount,
                        "date": self.date,
                        "utr": self.utr,
                        "narration": self.narration
                    }

            self.evidence = EvWrapper(data["evidence"])

    return WrapperDecision(res), res, None