from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIR = ROOT / "data" / "results"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"


def load_predictions():
    exact = pd.read_csv(
        RESULTS_DIR / "exact_matches.csv"
    )

    tolerance = pd.read_csv(
        RESULTS_DIR / "tolerance_matches.csv"
    )

    return exact, tolerance


def load_ground_truth():
    ground_truth = pd.read_csv(
        GROUND_TRUTH_DIR / "relationships.csv"
    )

    return ground_truth[
        ground_truth["is_match"] == True
    ][
        [
            "settlement_id",
            "bank_transaction_id",
        ]
    ].drop_duplicates()


def expand_predictions(df):
    pairs = set()

    for _, row in df.iterrows():
        settlement_id = row["settlement_id"]

        bank_ids = str(
            row["bank_transaction_id"]
        ).split("|")

        for bank_id in bank_ids:
            pairs.add(
                (
                    settlement_id,
                    bank_id,
                )
            )

    return pairs


def evaluate(exact, tolerance, ground_truth):

    exact_pairs = expand_predictions(exact)

    tolerance_pairs = expand_predictions(
        tolerance
    )

    predicted_pairs = (
        exact_pairs | tolerance_pairs
    )

    true_pairs = set(
        zip(
            ground_truth["settlement_id"],
            ground_truth["bank_transaction_id"],
        )
    )

    true_positives = len(
        predicted_pairs & true_pairs
    )

    false_positives = len(
        predicted_pairs - true_pairs
    )

    false_negatives = len(
        true_pairs - predicted_pairs
    )

    precision = (
        true_positives
        / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )

    recall = (
        true_positives
        / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )

    f1 = (
        2 * precision * recall
        / (precision + recall)
        if precision + recall
        else 0.0
    )

    return (
        true_positives,
        false_positives,
        false_negatives,
        precision,
        recall,
        f1,
        predicted_pairs,
        true_pairs,
    )

def main():
    exact, tolerance = load_predictions()

    ground_truth = load_ground_truth()

    (
        true_positives,
        false_positives,
        false_negatives,
        precision,
        recall,
        f1,
        predicted_pairs,
        true_pairs,
    ) = evaluate(
        exact,
        tolerance,
        ground_truth,
    )

    unresolved = (
        true_pairs - predicted_pairs
    )

    print("=" * 60)
    print("LEDGER - EXACT + TOLERANCE EVALUATION")
    print("=" * 60)

    print(
        f"Ground-truth matches : {len(true_pairs)}"
    )

    print(
        f"Exact matches        : {len(exact)}"
    )

    print(
        f"Tolerance matches    : {len(tolerance)}"
    )

    print(
        f"Combined predictions : {len(predicted_pairs)}"
    )

    print()

    print(
        f"True positives       : {true_positives}"
    )

    print(
        f"False positives      : {false_positives}"
    )

    print(
        f"False negatives      : {false_negatives}"
    )

    print()

    print(
        f"Precision : {precision:.4f}"
    )

    print(
        f"Recall    : {recall:.4f}"
    )

    print(
        f"F1 Score  : {f1:.4f}"
    )

    print(
        "\nUnresolved ground-truth matches:"
    )

    if unresolved:
        for settlement_id, bank_id in sorted(
            unresolved
        ):
            print(
                f"  {settlement_id} -> {bank_id}"
            )
    else:
        print("  None")


if __name__ == "__main__":
    main()