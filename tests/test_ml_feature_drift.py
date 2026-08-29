"""
test_ml_feature_drift.py — Unit Tests for ML Feature Drift & Schema Validation (Part 4)

Verifies:
  1. FEATURE_COLUMNS is exported as the single canonical feature schema from ml.feature_schema (T4.1).
  2. validate_feature_schema() in ml/evaluate_confidence_model.py raises an explicit ValueError
     when unexpected extra columns or missing required columns are present (T4.3).
  3. No silent zero-filling or reindex-and-continue behavior occurs on schema mismatch.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from ml.feature_schema import FEATURE_COLUMNS
from ml.evaluate_confidence_model import validate_feature_schema, generate_predictions


class TestMLFeatureDrift(unittest.TestCase):

    def test_canonical_feature_schema_imported(self):
        """Verify FEATURE_COLUMNS is a non-empty list of string feature names."""
        self.assertIsInstance(FEATURE_COLUMNS, list)
        self.assertGreater(len(FEATURE_COLUMNS), 20)
        self.assertIn("settlement_amount", FEATURE_COLUMNS)
        self.assertIn("is_digit_transposition", FEATURE_COLUMNS)

    def test_valid_schema_passes_validation(self):
        """Verify exact canonical feature set validates without error."""
        valid_cols = ["settlement_id", "bank_transaction_id", "label"] + FEATURE_COLUMNS
        validated = validate_feature_schema(valid_cols)
        self.assertEqual(validated, FEATURE_COLUMNS)

    def test_bogus_extra_column_raises_value_error(self):
        """Verify adding a bogus column raises a ValueError naming the extra column (T4.3)."""
        invalid_cols = ["settlement_id", "bank_transaction_id", "label"] + FEATURE_COLUMNS + ["bogus_extra_feature"]
        with self.assertRaises(ValueError) as ctx:
            validate_feature_schema(invalid_cols)

        err_msg = str(ctx.exception)
        self.assertIn("ML Feature Schema Mismatch Detected", err_msg)
        self.assertIn("bogus_extra_feature", err_msg)

    def test_missing_feature_column_raises_value_error(self):
        """Verify omitting a required feature column raises a ValueError naming the missing column (T4.3)."""
        incomplete_cols = ["settlement_id", "bank_transaction_id", "label"] + FEATURE_COLUMNS[:-1]
        missing_col_name = FEATURE_COLUMNS[-1]

        with self.assertRaises(ValueError) as ctx:
            validate_feature_schema(incomplete_cols)

        err_msg = str(ctx.exception)
        self.assertIn("ML Feature Schema Mismatch Detected", err_msg)
        self.assertIn(missing_col_name, err_msg)

    def test_generate_predictions_fails_fast_on_feature_drift(self):
        """Verify generate_predictions fails fast with ValueError on DataFrame with feature drift."""
        data_dict = {
            "settlement_id": ["S1"],
            "bank_transaction_id": ["B1"],
            "label": [1],
            "bogus_feature": [999.0]
        }
        for col in FEATURE_COLUMNS:
            data_dict[col] = [1.0]

        df = pd.DataFrame(data_dict)
        mock_model = None
        mock_scaler = None

        with self.assertRaises(ValueError) as ctx:
            generate_predictions(df, mock_model, mock_scaler)

        self.assertIn("bogus_feature", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
