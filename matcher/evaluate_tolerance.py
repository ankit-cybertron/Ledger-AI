from pathlib import Path
import pandas as pd
from matcher.evaluation_metrics import compute_precision_recall_f1, extract_pairs

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"


def load_predictions():
    exact = pd.read_csv(RESULTS_DIR / "exact_matches.csv") if (RESULTS_DIR / "exact_matches.csv").exists() else pd.DataFrame()
    tolerance = pd.read_csv(RESULTS_DIR / "tolerance_matches.csv") if (RESULTS_DIR / "tolerance_matches.csv").exists() else pd.DataFrame()
    return exact, tolerance


def load_ground_truth():
    if not (GROUND_TRUTH_DIR / "relationships.csv").exists():
        return pd.DataFrame()
    gt = pd.read_csv(GROUND_TRUTH_DIR / "relationships.csv")
    return gt[gt["is_match"] == True] if "is_match" in gt.columns else gt


def evaluate(exact, tolerance, ground_truth):
    exact_pairs = extract_pairs(exact)
    tolerance_pairs = extract_pairs(tolerance)
    predicted_pairs = exact_pairs | tolerance_pairs
    true_pairs = extract_pairs(ground_truth)


    metrics = compute_precision_recall_f1(predicted_pairs, true_pairs)

    return (
        metrics["true_positives"],
        metrics["false_positives"],
        metrics["false_negatives"],
        metrics["precision"],
        metrics["recall"],
        metrics["f1"],
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
    ) = evaluate(exact, tolerance, ground_truth)

    unresolved = true_pairs - predicted_pairs

    print("=" * 60)
    print("LEDGER - EXACT + TOLERANCE EVALUATION")
    print("=" * 60)
    print(f"Ground-truth matches : {len(true_pairs)}")
    print(f"Exact matches        : {len(exact)}")
    print(f"Tolerance matches    : {len(tolerance)}")
    print(f"Combined predictions : {len(predicted_pairs)}")
    print()
    print(f"True positives       : {true_positives}")
    print(f"False positives      : {false_positives}")
    print(f"False negatives      : {false_negatives}")
    print()
    print(f"Precision : {precision:.4f}")
    print(f"Recall    : {recall:.4f}")
    print(f"F1 Score  : {f1:.4f}")

    print("\nUnresolved ground-truth matches:")
    if unresolved:
        for p_id, c_id in sorted(unresolved):
            print(f"  {p_id} -> {c_id}")
    else:
        print("  None")


if __name__ == "__main__":
    main()