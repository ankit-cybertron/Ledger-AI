from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIR = ROOT / "data" / "results"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"


def main():
    predictions = pd.read_csv(
        RESULTS_DIR / "exact_matches.csv"
    )

    ground_truth = pd.read_csv(
        GROUND_TRUTH_DIR / "relationships.csv"
    )

    # Only true settlement-to-bank relationships are
    # evaluated as positive matching targets.
    true_matches = ground_truth[
        ground_truth["is_match"] == True
    ][
        [
            "settlement_id",
            "bank_transaction_id",
        ]
    ].drop_duplicates()

    predicted_matches = predictions[
        [
            "settlement_id",
            "bank_transaction_id",
        ]
    ].drop_duplicates()

    true_pairs = set(
        zip(
            true_matches["settlement_id"],
            true_matches["bank_transaction_id"],
        )
    )

    predicted_pairs = set(
        zip(
            predicted_matches["settlement_id"],
            predicted_matches["bank_transaction_id"],
        )
    )

    true_positives = len(
        true_pairs & predicted_pairs
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
        else 0
    )

    recall = (
        true_positives
        / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0
    )

    f1 = (
        2 * precision * recall
        / (precision + recall)
        if precision + recall
        else 0
    )

    print("=" * 60)
    print("LEDGER - EXACT MATCH EVALUATION")
    print("=" * 60)

    print(f"Ground-truth matches : {len(true_pairs)}")
    print(f"Predicted matches    : {len(predicted_pairs)}")
    print(f"True positives       : {true_positives}")
    print(f"False positives      : {false_positives}")
    print(f"False negatives      : {false_negatives}")

    print()
    print(f"Precision : {precision:.4f}")
    print(f"Recall    : {recall:.4f}")
    print(f"F1 Score  : {f1:.4f}")


if __name__ == "__main__":
    main()