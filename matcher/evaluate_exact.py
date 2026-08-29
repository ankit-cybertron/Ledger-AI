from pathlib import Path
import pandas as pd
from matcher.evaluation_metrics import compute_precision_recall_f1, extract_pairs

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"


def main():
    predictions = pd.read_csv(RESULTS_DIR / "exact_matches.csv") if (RESULTS_DIR / "exact_matches.csv").exists() else pd.DataFrame()
    ground_truth = pd.read_csv(GROUND_TRUTH_DIR / "relationships.csv") if (GROUND_TRUTH_DIR / "relationships.csv").exists() else pd.DataFrame()

    true_matches_df = ground_truth[ground_truth["is_match"] == True] if not ground_truth.empty and "is_match" in ground_truth.columns else ground_truth

    true_pairs = extract_pairs(true_matches_df)
    predicted_pairs = extract_pairs(predictions)


    metrics = compute_precision_recall_f1(predicted_pairs, true_pairs)

    print("=" * 60)
    print("LEDGER - EXACT MATCH EVALUATION")
    print("=" * 60)

    print(f"Ground-truth matches : {metrics['ground_truth_count']}")
    print(f"Predicted matches    : {metrics['predicted_count']}")
    print(f"True positives       : {metrics['true_positives']}")
    print(f"False positives      : {metrics['false_positives']}")
    print(f"False negatives      : {metrics['false_negatives']}")

    print()
    print(f"Precision : {metrics['precision']:.4f}")
    print(f"Recall    : {metrics['recall']:.4f}")
    print(f"F1 Score  : {metrics['f1']:.4f}")


if __name__ == "__main__":
    main()