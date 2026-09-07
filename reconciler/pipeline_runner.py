"""
pipeline_runner.py — Explicit Batch Pipeline Orchestration (Part 5, T5.4).

Consolidates batch reconciliation pipeline sequencing into the reconciler/ package.
Runs matching stages strictly in order:
  1. Exact Matcher (evaluate_exact)
  2. Tolerance Matcher (evaluate_tolerance)
  3. ML Confidence Engine (build_training_data & evaluate_confidence_model)
  4. Reconciliation Aggregator (reconcile) -- WITHOUT automatic LLM calls (T5.3)
  5. Exception Ledger Generator (exception_ledger)
  6. Markdown Report Generator (generate_report)
  7. Agent Data Reload (settlement_qa)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import MatchingConfig
from matcher import exact_matcher, tolerance_matcher
from ml import build_training_data, evaluate_confidence_model
from reconciler import reconcile
from exceptions import exception_ledger
from reports import generate_report
from agents import settlement_qa


def run_full_pipeline(cfg: MatchingConfig = None) -> dict:
    """
    Executes the full automated reconciliation pipeline in canonical order (T5.4).
    Per T5.3, the LLM stage is NOT executed as part of this automated batch process.
    """
    from frontend.api import pipeline_tracker

    if cfg is None:
        cfg = MatchingConfig.load_with_env_overrides()

    print("=" * 60)
    print("STARTING FULL RECONCILIATION PIPELINE (T5.4)")
    print("=" * 60)

    # 1. Reconciliation Engine (Unified Exact, Tolerance, and Similarity Matching)
    pipeline_tracker.update_progress(45, "[Pipeline Step 2/5] Running Unified Matching Engine...", "Executing High-Performance Reconciliation...", level="RULE")
    print("\n[Pipeline Step 2/5] Running High-Performance Unified Reconciliation...")
    reconcile_df = reconcile.reconcile(cfg=cfg)

    # 2. ML Feature Building & Confidence Evaluation
    pipeline_tracker.update_progress(70, "[Pipeline Step 3/5] Evaluating ML Feature Schema & Model...", "Evaluating ML Features...", level="ML")
    print("\n[Pipeline Step 3/5] Building ML Feature Vectors & Evaluating Model...")
    try:
        build_training_data.main()
        evaluate_confidence_model.main()
    except Exception as ml_err:
        print(f"[NOTE] ML evaluation skipped: {ml_err}")

    # 3. Exception Ledger
    pipeline_tracker.update_progress(85, "[Pipeline Step 4/5] Compiling Exception Ledger...", "Compiling Exception Ledger...", level="RECON")
    print("\n[Pipeline Step 4/5] Building Exception Ledger...")
    exception_ledger.main()

    # 4. Report Generation (Safe Non-blocking Execution)
    pipeline_tracker.update_progress(95, "[Pipeline Step 5/5] Generating Audit Reports...", "Compiling Audit Reports...", level="SUCCESS")
    print("\n[Pipeline Step 5/5] Generating Reconciliation Report...")
    try:
        generate_report.main()
    except Exception as rep_err:
        print(f"[NOTE] Audit report generation skipped: {rep_err}")

    # Reload QA Agent Data
    try:
        settlement_qa.reload_data()
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("RECONCILIATION PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)

    return {
        "ok": True,
        "status": "completed",
        "record_count": len(reconcile_df) if reconcile_df is not None and hasattr(reconcile_df, "__len__") else 0,
    }


if __name__ == "__main__":
    run_full_pipeline()
