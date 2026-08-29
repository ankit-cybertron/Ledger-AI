import unittest
import os
import json
import pandas as pd

from frontend import statement_store
from frontend.app import app

class TestPart12CleanState(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.app = app
        self.client = self.app.test_client()
        statement_store.clear_all_statements()

    def tearDown(self):
        statement_store.clear_all_statements()

    def test_t12_1_clean_state(self):
        """T12.1: Verify statements_db.json is empty when initialized/reset."""
        db_data = statement_store._load_db()
        self.assertEqual(db_data.get("statements"), [])

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gen_dir = os.path.join(base_dir, "data", "generated")
        for csv_name in ["bank_statement.csv", "primary_records.csv", "counterpart_records.csv", "razorpay_settlements.csv", "internal_orders.csv"]:
            path = os.path.join(gen_dir, csv_name)
            self.assertTrue(os.path.exists(path))
            df = pd.read_csv(path)
            self.assertEqual(len(df), 0)

    def test_t12_2_clear_all_data_endpoint(self):
        """T12.2: Test both /api/data/clear and /api/clear_all_data endpoints purge state."""
        res1 = self.client.post("/api/data/clear")
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.get_json().get("ok"))

        res2 = self.client.post("/api/clear_all_data")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json().get("ok"))

    def test_t12_3_empty_dashboard_persistence(self):
        """T12.3: Verify dashboard returns 0 transactions and empty charts when no statements exist."""
        res = self.client.get("/api/reconciliation")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        run = data.get("run", {})
        self.assertEqual(run.get("summary", {}).get("total_transactions"), 0)
        self.assertEqual(len(run.get("transactions", [])), 0)
        self.assertEqual(len(run.get("exceptions", [])), 0)

if __name__ == "__main__":
    unittest.main()
