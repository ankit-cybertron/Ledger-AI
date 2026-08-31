import pytest
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
RESULTS_DIR = ROOT / "data" / "results"

SETTLEMENTS_PATH = GENERATED_DIR / "razorpay_settlements.csv"
GROUND_TRUTH_PATH = GROUND_TRUTH_DIR / "relationships.csv"
RECONCILIATION_PATH = RESULTS_DIR / "reconciliation_results.csv"
EXCEPTION_PATH = RESULTS_DIR / "exception_ledger.csv"

@pytest.fixture
def settlements():
    if SETTLEMENTS_PATH.exists():
        return pd.read_csv(SETTLEMENTS_PATH)
    pytest.skip("Pipeline generated settlements benchmark CSV missing")

@pytest.fixture
def ground_truth():
    if GROUND_TRUTH_PATH.exists():
        return pd.read_csv(GROUND_TRUTH_PATH)
    pytest.skip("Pipeline ground truth benchmark CSV missing")

@pytest.fixture
def reconciliation():
    if RECONCILIATION_PATH.exists():
        return pd.read_csv(RECONCILIATION_PATH)
    pytest.skip("Pipeline reconciliation results CSV missing")

@pytest.fixture
def exceptions():
    if EXCEPTION_PATH.exists():
        return pd.read_csv(EXCEPTION_PATH)
    pytest.skip("Pipeline exception ledger CSV missing")
