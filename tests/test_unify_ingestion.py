import io
import os
import unittest
import pandas as pd
from pathlib import Path

from frontend.app import app
from frontend import statement_store
from ingestion.duplicate_columns import detect_duplicate_columns
from ingestion.column_mapper import map_columns, RawTable
from ingestion.normalizer import normalize_row


def tearDownModule():
    statement_store.clear_all_statements()


class TestUnifyIngestion(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        statement_store.clear_all_statements()

    def tearDown(self):
        statement_store.clear_all_statements()

    def test_duplicate_column_detection(self):
        """
        T2.7 Acceptance Criteria:
        Uploading a statement with two columns containing identical values in every row
        results in exactly one of them being kept, and the import result clearly states which
        column was dropped and why.
        """
        rows = [
            {"UTR Number": "UTR999888777 ", "Reference No": "utr999888777", "Amount": "1000.00", "Date": "2026-01-01"},
            {"UTR Number": "UTR111222333", "Reference No": "UTR111222333 ", "Amount": "2500.50", "Date": "2026-01-02"},
        ]

        col_mapping = {
            "UTR Number": "utr",
            "Reference No": "utr",
            "Amount": "net_amount",
            "Date": "transaction_date"
        }

        dropped_cols, explanations = detect_duplicate_columns(rows, col_mapping)

        self.assertEqual(len(dropped_cols), 1)
        self.assertIn("Reference No", dropped_cols)
        self.assertIn("Column 'Reference No' was dropped — identical to 'UTR Number' for every row.", explanations[0])

    def test_statement_store_unification(self):
        """
        T2.1-T2.6 Acceptance Criteria:
        statement_store.py delegates normalization and deduplication to ingestion/*.py
        and rebuild_generated_csv writes primary_records.csv and counterpart_records.csv.
        """
        df = pd.DataFrame([
            {"Date": "2026-01-05", "Credit": "5000.00", "Debit": "0.00", "UTR": "UTR555444333", "Particulars": "Test Income"},
            {"Date": "2026-01-06", "Credit": "0.00", "Debit": "1200.00", "UTR": "UTR111222333", "Particulars": "Test Expense"},
        ])

        stmt = statement_store.save_imported_statement(
            name="Test Unified Store",
            filename="test_unified.csv",
            df=df,
            is_primary=True,
            color="#6f89ff"
        )

        self.assertIsNotNone(stmt.get("id"))
        self.assertEqual(stmt.get("row_count"), 2)

        # Check generated CSV outputs
        gen_dir = Path(__file__).resolve().parents[1] / "data" / "generated"
        pri_file = gen_dir / "primary_records.csv"
        cnt_file = gen_dir / "counterpart_records.csv"

        self.assertTrue(pri_file.exists())
        self.assertTrue(cnt_file.exists())

        pri_df = pd.read_csv(pri_file)
        self.assertFalse(pri_df.empty)
        self.assertIn("net_amount", pri_df.columns)
        self.assertIn("transaction_id", pri_df.columns)


if __name__ == "__main__":
    unittest.main()
