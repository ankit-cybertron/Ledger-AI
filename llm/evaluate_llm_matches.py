from pathlib import Path

import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIR = ROOT / "data" / "results"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"

LLM_RESULTS = RESULTS_DIR / "llm_matches.csv"
GROUND_TRUTH = (
    GROUND_TRUTH_DIR / "relationships.csv"
)


# ============================================================
# LOAD DATA
# ============================================================

def load_data():
    if not LLM_RESULTS.exists():
        raise FileNotFoundError(
            f"LLM results not found: {LLM_RESULTS}"
        )

    if not GROUND_TRUTH.exists():
        raise FileNotFoundError(
            f"Ground truth not found: {GROUND_TRUTH}"
        )

    llm = pd.read_csv(
        LLM_RESULTS
    )

    truth = pd.read_csv(
        GROUND_TRUTH
    )

    return llm, truth


# ============================================================
# BUILD GROUND-TRUTH LOOKUP
# ============================================================

def build_truth_lookup(truth):
    """
    Build a lookup containing every known positive
    settlement -> bank relationship.
    """

    matches = truth[
        truth["is_match"] == True
    ]

    return {
        (
            row["settlement_id"],
            row["bank_transaction_id"],
        )
        for _, row in matches.iterrows()
    }


# ============================================================
# EVALUATE LLM DECISIONS
# ============================================================

def evaluate(llm, truth):
    true_pairs = build_truth_lookup(
        truth
    )

    results = llm.copy()

    results["ground_truth_match"] = (
        results.apply(
            lambda row: (
                row["settlement_id"],
                row["bank_transaction_id"],
            ) in true_pairs,
            axis=1,
        )
    )

    results["correct"] = False

    # --------------------------------------------------------
    # MATCH
    # --------------------------------------------------------

    match_mask = (
        results["llm_decision"]
        == "match"
    )

    results.loc[
        match_mask,
        "correct",
    ] = (
        results.loc[
            match_mask,
            "ground_truth_match",
        ]
    )

    # --------------------------------------------------------
    # NON-MATCH
    # --------------------------------------------------------

    non_match_mask = (
        results["llm_decision"]
        == "non_match"
    )

    results.loc[
        non_match_mask,
        "correct",
    ] = (
        ~results.loc[
            non_match_mask,
            "ground_truth_match",
        ]
    )

    # --------------------------------------------------------
    # REVIEW
    # --------------------------------------------------------
    #
    # "review" is intentionally not counted as correct or
    # incorrect. It means the LLM declined to decide.
    #

    review_mask = (
        results["llm_decision"]
        == "review"
    )

    return results, review_mask


# ============================================================
# PRINT SUMMARY
# ============================================================

def print_summary(
    results,
    review_mask,
):

    total = len(results)

    matches = (
        results["llm_decision"]
        == "match"
    ).sum()

    non_matches = (
        results["llm_decision"]
        == "non_match"
    ).sum()

    reviews = review_mask.sum()

    correct = results[
        (~review_mask)
        & (results["correct"])
    ].shape[0]

    incorrect = results[
        (~review_mask)
        & (~results["correct"])
    ].shape[0]

    decided = matches + non_matches

    decision_accuracy = (
        correct / decided
        if decided
        else 0.0
    )

    coverage = (
        decided / total
        if total
        else 0.0
    )

    print("=" * 60)
    print("LEDGER - LLM MATCH EVALUATION")
    print("=" * 60)

    print(
        f"LLM candidates evaluated : {total}"
    )

    print(
        f"LLM matches              : {matches}"
    )

    print(
        f"LLM non-matches          : {non_matches}"
    )

    print(
        f"LLM reviews              : {reviews}"
    )

    print()

    print(
        f"Correct decisions        : {correct}"
    )

    print(
        f"Incorrect decisions      : {incorrect}"
    )

    print()

    print(
        f"Decision accuracy        : "
        f"{decision_accuracy:.4f}"
    )

    print(
        f"Decision coverage        : "
        f"{coverage:.4f}"
    )


# ============================================================
# PRINT ERRORS
# ============================================================

def print_errors(results):

    incorrect = results[
        results["correct"] == False
    ]

    # Exclude review decisions because review is an
    # intentional unresolved state, not a false prediction.
    incorrect = incorrect[
        incorrect["llm_decision"].isin(
            ["match", "non_match"]
        )
    ]

    print()
    print("=" * 60)
    print("INCORRECT LLM DECISIONS")
    print("=" * 60)

    if incorrect.empty:
        print("None")
        return

    columns = [
        "settlement_id",
        "bank_transaction_id",
        "ml_confidence",
        "llm_decision",
        "llm_confidence",
        "ground_truth_match",
        "reason",
    ]

    print(
        incorrect[
            columns
        ].to_string(index=False)
    )


# ============================================================
# PRINT REVIEWS
# ============================================================

def print_reviews(results):

    reviews = results[
        results["llm_decision"]
        == "review"
    ]

    print()
    print("=" * 60)
    print("LLM REVIEW CASES")
    print("=" * 60)

    if reviews.empty:
        print("None")
        return

    columns = [
        "settlement_id",
        "bank_transaction_id",
        "ml_confidence",
        "llm_decision",
        "llm_confidence",
        "reason",
    ]

    print(
        reviews[
            columns
        ].to_string(index=False)
    )


# ============================================================
# PRINT MATCHES
# ============================================================

def print_matches(results):

    matches = results[
        results["llm_decision"]
        == "match"
    ]

    print()
    print("=" * 60)
    print("LLM MATCH DECISIONS")
    print("=" * 60)

    if matches.empty:
        print("None")
        return

    columns = [
        "settlement_id",
        "bank_transaction_id",
        "ml_confidence",
        "llm_confidence",
        "ground_truth_match",
    ]

    print(
        matches[
            columns
        ].to_string(index=False)
    )


# ============================================================
# SAVE EVALUATED RESULTS
# ============================================================

def save_results(results):

    output_path = (
        RESULTS_DIR
        / "llm_evaluation.csv"
    )

    results.to_csv(
        output_path,
        index=False,
    )

    print()
    print(
        f"Saved evaluation: {output_path}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    llm, truth = load_data()

    results, review_mask = evaluate(
        llm,
        truth,
    )

    print_summary(
        results,
        review_mask,
    )

    print_matches(
        results
    )

    print_reviews(
        results
    )

    print_errors(
        results
    )

    save_results(
        results
    )

    print()
    print("=" * 60)
    print("LLM EVALUATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()