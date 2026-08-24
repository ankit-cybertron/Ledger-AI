from pathlib import Path
import os

import pandas as pd
from dotenv import load_dotenv


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"
ML_DIR = ROOT / "data" / "ml"


SETTLEMENTS_PATH = (
    GENERATED_DIR / "razorpay_settlements.csv"
)

EXACT_RESULTS_PATH = (
    RESULTS_DIR / "exact_matches.csv"
)

TOLERANCE_RESULTS_PATH = (
    RESULTS_DIR / "tolerance_matches.csv"
)

CONFIDENCE_RESULTS_PATH = (
    ML_DIR / "confidence_predictions.csv"
)

LLM_RESULTS_PATH = (
    RESULTS_DIR / "llm_matches.csv"
)

OUTPUT_PATH = (
    RESULTS_DIR / "reconciliation_results.csv"
)


# ============================================================
# CONFIGURATION
# ============================================================

LLM_REVIEW_LOWER_BOUND = 0.50
LLM_REVIEW_UPPER_BOUND = 0.95


# ============================================================
# HELPERS
# ============================================================

def normalize_bank_ids(value):
    """
    Tolerance matcher may store split settlements as:

        bank_0036|bank_split_0001

    Convert that into a list.
    """

    if pd.isna(value):
        return []

    return [
        x.strip()
        for x in str(value).split("|")
        if x.strip()
    ]


def load_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


# ============================================================
# EXACT MATCHES
# ============================================================

def load_exact_matches():
    """
    Loads deterministic exact matches.

    Expected columns:
        settlement_id
        bank_transaction_id
    """

    exact = load_csv(
        EXACT_RESULTS_PATH
    )

    if exact.empty:
        return []

    required = {
        "settlement_id",
        "bank_transaction_id",
    }

    missing = required - set(exact.columns)

    if missing:
        raise ValueError(
            "exact_matches.csv is missing columns: "
            f"{sorted(missing)}"
        )

    results = []

    for _, row in exact.iterrows():

        bank_ids = normalize_bank_ids(
            row["bank_transaction_id"]
        )

        for bank_id in bank_ids:

            res_dict = {
                "settlement_id": row["settlement_id"],
                "bank_transaction_id": bank_id,
                "stage": "exact",
                "decision": "match",
                "confidence": 1.0,
                "reason": "Exact deterministic match.",
                "status": "matched",
            }
            if "amount" in row and pd.notna(row["amount"]):
                res_dict["amount"] = row["amount"]
            if "date" in row and pd.notna(row["date"]):
                res_dict["date"] = row["date"]
            results.append(res_dict)

    return results


# ============================================================
# TOLERANCE / SPLIT MATCHES
# ============================================================

def load_tolerance_matches(
    already_matched,
):
    """
    Loads tolerance-stage matches.

    Exact matches are excluded so that a settlement
    cannot be emitted twice.
    """

    tolerance = load_csv(
        TOLERANCE_RESULTS_PATH
    )

    if tolerance.empty:
        return []

    required = {
        "settlement_id",
        "bank_transaction_id",
    }

    missing = required - set(
        tolerance.columns
    )

    if missing:
        raise ValueError(
            "tolerance_matches.csv is missing "
            f"columns: {sorted(missing)}"
        )

    results = []

    for _, row in tolerance.iterrows():

        settlement_id = row[
            "settlement_id"
        ]

        if settlement_id in already_matched:
            continue

        bank_ids = normalize_bank_ids(
            row["bank_transaction_id"]
        )

        for bank_id in bank_ids:

            results.append(
                {
                    "settlement_id": settlement_id,
                    "bank_transaction_id": bank_id,
                    "stage": "tolerance",
                    "decision": "match",
                    "confidence": 1.0,
                    "reason": (
                        "Tolerance-stage match."
                    ),
                    "status": "matched",
                }
            )

        already_matched.add(
            settlement_id
        )

    return results


# ============================================================
# ML CONFIDENCE
# ============================================================

def load_ml_candidates(
    already_matched,
):
    """
    Loads ML confidence predictions.

    Only unresolved settlements are considered.

    The ML model itself is not allowed to blindly
    create a match here. Its confidence determines
    which downstream path is taken.
    """

    predictions = load_csv(
        CONFIDENCE_RESULTS_PATH
    )

    if predictions.empty:
        return []

    required = {
        "settlement_id",
        "bank_transaction_id",
        "confidence",
    }

    missing = required - set(
        predictions.columns
    )

    if missing:
        raise ValueError(
            "confidence_predictions.csv is "
            f"missing columns: {sorted(missing)}"
        )

    active_settlements = load_csv(SETTLEMENTS_PATH)
    if not active_settlements.empty and "settlement_id" in active_settlements.columns:
        valid_ids = set(active_settlements["settlement_id"].astype(str))
        predictions = predictions[predictions["settlement_id"].astype(str).isin(valid_ids)]

    candidates = []

    for _, row in predictions.iterrows():

        settlement_id = row[
            "settlement_id"
        ]

        if settlement_id in already_matched:
            continue

        confidence = float(
            row["confidence"]
        )

        candidates.append(
            {
                "settlement_id": settlement_id,
                "bank_transaction_id": row[
                    "bank_transaction_id"
                ],
                "confidence": confidence,
            }
        )

    return candidates


# ============================================================
# LLM RESULTS
# ============================================================

def load_llm_results():
    """
    Loads results already produced by
    llm/ambiguous_matcher.py.
    """

    if not LLM_RESULTS_PATH.exists():
        return pd.DataFrame(
            columns=[
                "settlement_id",
                "bank_transaction_id",
                "ml_confidence",
                "llm_decision",
                "llm_confidence",
                "reason",
                "fallback_triggered",
            ]
        )

    return load_csv(
        LLM_RESULTS_PATH
    )


# ============================================================
# BUILD LLM LOOKUP
# ============================================================

def build_llm_lookup(llm_results):

    lookup = {}

    for _, row in llm_results.iterrows():

        key = (
            row["settlement_id"],
            row["bank_transaction_id"],
        )

        lookup[key] = row

    return lookup


# ============================================================
# MAIN RECONCILIATION
# ============================================================

def reconcile():

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    settlements = load_csv(
        SETTLEMENTS_PATH
    )

    final_results = []

    matched_settlements = set()

    # --------------------------------------------------------
    # STAGE 1 — EXACT
    # --------------------------------------------------------

    exact_results = load_exact_matches()

    final_results.extend(
        exact_results
    )

    for result in exact_results:
        matched_settlements.add(
            result["settlement_id"]
        )

    # --------------------------------------------------------
    # STAGE 2 — TOLERANCE
    # --------------------------------------------------------

    tolerance_results = (
        load_tolerance_matches(
            matched_settlements
        )
    )

    final_results.extend(
        tolerance_results
    )

    # --------------------------------------------------------
    # STAGE 3 — ML
    # --------------------------------------------------------

    ml_candidates = load_ml_candidates(
        matched_settlements
    )

    llm_results = load_llm_results()

    llm_lookup = build_llm_lookup(
        llm_results
    )

    for candidate in ml_candidates:

        settlement_id = candidate[
            "settlement_id"
        ]

        bank_id = candidate[
            "bank_transaction_id"
        ]

        ml_confidence = candidate[
            "confidence"
        ]

        # A settlement already resolved by an earlier
        # candidate must never be emitted again.
        if settlement_id in matched_settlements:
            continue

        # ----------------------------------------------------
        # HIGH CONFIDENCE
        # ----------------------------------------------------

        if ml_confidence >= (
            LLM_REVIEW_UPPER_BOUND
        ):

            final_results.append(
                {
                    "settlement_id": settlement_id,
                    "bank_transaction_id": bank_id,
                    "stage": "ml",
                    "decision": "match",
                    "confidence": ml_confidence,
                    "reason": (
                        "High-confidence ML match."
                    ),
                    "status": "matched",
                }
            )

            matched_settlements.add(
                settlement_id
            )

            continue

        # ----------------------------------------------------
        # LLM REVIEW BAND
        # ----------------------------------------------------

        if (
            ml_confidence
            >= LLM_REVIEW_LOWER_BOUND
            and ml_confidence
            < LLM_REVIEW_UPPER_BOUND
        ):

            key = (
                settlement_id,
                bank_id,
            )

            llm = llm_lookup.get(
                key
            )

            # The LLM result should normally already exist
            # because ambiguous_matcher.py was run first.
            if llm is None:

                final_results.append(
                    {
                        "settlement_id": settlement_id,
                        "bank_transaction_id": bank_id,
                        "stage": "llm",
                        "decision": "review",
                        "confidence": ml_confidence,
                        "reason": (
                            "Candidate falls inside "
                            "the LLM review band, but "
                            "no LLM result is available."
                        ),
                        "status": "manual_review",
                    }
                )

                continue

            llm_decision = str(
                llm["llm_decision"]
            )

            llm_confidence = float(
                llm["llm_confidence"]
            )

            reason = str(
                llm["reason"]
            )

            fallback = bool(
                llm.get(
                    "fallback_triggered",
                    False,
                )
            )

            if llm_decision == "match":

                final_results.append(
                    {
                        "settlement_id": settlement_id,
                        "bank_transaction_id": bank_id,
                        "stage": "llm",
                        "decision": "match",
                        "confidence": llm_confidence,
                        "reason": reason,
                        "status": "matched",
                    }
                )

                matched_settlements.add(
                    settlement_id
                )

            elif llm_decision == "non_match":

                final_results.append(
                    {
                        "settlement_id": settlement_id,
                        "bank_transaction_id": bank_id,
                        "stage": "llm",
                        "decision": "non_match",
                        "confidence": llm_confidence,
                        "reason": reason,
                        "status": "unmatched",
                    }
                )

            else:

                final_results.append(
                    {
                        "settlement_id": settlement_id,
                        "bank_transaction_id": bank_id,
                        "stage": "llm",
                        "decision": "review",
                        "confidence": (
                            0.0
                            if fallback
                            else llm_confidence
                        ),
                        "reason": reason,
                        "status": "manual_review",
                    }
                )

            continue

        # ----------------------------------------------------
        # LOW CONFIDENCE
        # ----------------------------------------------------

        final_results.append(
            {
                "settlement_id": settlement_id,
                "bank_transaction_id": bank_id,
                "stage": "ml",
                "decision": "non_match",
                "confidence": ml_confidence,
                "reason": (
                    "ML confidence is below "
                    "the LLM review threshold."
                ),
                "status": "unmatched",
            }
        )

    # --------------------------------------------------------
    # UNRESOLVED SETTLEMENTS
    # --------------------------------------------------------

    processed = {
        result["settlement_id"]
        for result in final_results
    }

    for settlement_id in settlements[
        "settlement_id"
    ]:

        if settlement_id in processed:
            continue

        final_results.append(
            {
                "settlement_id": settlement_id,
                "bank_transaction_id": "",
                "stage": "reconciler",
                "decision": "review",
                "confidence": 0.0,
                "reason": (
                    "No deterministic or ML "
                    "candidate resolved this settlement."
                ),
                "status": "manual_review",
            }
        )

    return pd.DataFrame(
        final_results
    )


# ============================================================
# SUMMARY
# ============================================================

def print_summary(results):

    print("=" * 60)
    print("LEDGER - RECONCILIATION")
    print("=" * 60)

    settlement_count = (
        results["settlement_id"]
        .nunique()
    )

    print(
        f"Settlements processed : "
        f"{settlement_count}"
    )

    # --------------------------------------------------------
    # Settlement-level outcome
    # --------------------------------------------------------
    #
    # A split settlement can have multiple relationship rows.
    # Therefore, settlement outcomes must be calculated
    # after grouping by settlement_id.
    #

    settlement_status = (
        results
        .groupby("settlement_id")["status"]
        .agg(
            lambda values: (
                "matched"
                if "matched" in set(values)
                else (
                    "manual_review"
                    if "manual_review" in set(values)
                    else "unmatched"
                )
            )
        )
    )

    print()
    print("Settlement outcomes:")

    print(
        settlement_status
        .value_counts()
        .to_string()
    )

    matched = (
        settlement_status
        == "matched"
    ).sum()

    manual_review = (
        settlement_status
        == "manual_review"
    ).sum()

    unmatched = (
        settlement_status
        == "unmatched"
    ).sum()

    print()
    print(
        f"Matched settlements     : {matched}"
    )

    print(
        f"Manual review           : {manual_review}"
    )

    print(
        f"Unmatched settlements   : {unmatched}"
    )

    print()

    # --------------------------------------------------------
    # Relationship-level information
    # --------------------------------------------------------

    print("Relationship records:")

    print(
        results["stage"]
        .value_counts()
        .to_string()
    )

    print()

    print(
        f"Relationship records    : "
        f"{len(results)}"
    )

    print()

    print("Decisions:")

    print(
        results["decision"]
        .value_counts()
        .to_string()
    )

    print()

    print("Statuses:")

    print(
        results["status"]
        .value_counts()
        .to_string()
    )

# ============================================================
# MAIN
# ============================================================

def main():

    results = reconcile()

    results.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print_summary(
        results
    )

    print()
    print(
        f"Saved: {OUTPUT_PATH}"
    )

    print("=" * 60)
    print("RECONCILIATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()