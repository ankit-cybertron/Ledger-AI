"""
test_part13_realtime_sync.py — Test Suite for Real-Time Sync & Invalidation (Part 13).

Validates:
1. Tab endpoints return fresh data upon multiple consecutive calls.
2. Reconciliation run changes (run auto match, resolve exception, import/delete statement) reflect immediately in overview & status endpoints.
"""

import unittest
import json
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend import statement_store
from frontend.app import app


class TestPart13RealtimeSync(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        statement_store.clear_all_statements()

    def tearDown(self):
        statement_store.clear_all_statements()

    def test_t13_1_fresh_overview_endpoint(self):
        """T13.1: Verify /api/reconciliation endpoint returns fresh overview state without caching stale runs."""
        # Initial empty state
        res1 = self.client.get("/api/reconciliation")
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1["run"]["summary"]["total_transactions"], 0)

        # Upload a bank statement
        csv_data = "Date,Description,Amount,UTR\n2026-08-01,Test Deposit,5000.0,UTR100\n2026-08-02,Test Payment,-1200.0,UTR101\n"
        upload_res = self.client.post(
            "/api/statements/import",
            data={
                "file": (io.BytesIO(csv_data.encode("utf-8")), "sync_bank.csv"),
                "name": "Sync Test Statement",
                "is_primary": "true",
            },
            content_type="multipart/form-data"
        )
        self.assertEqual(upload_res.status_code, 200)

        # Immediate GET /api/reconciliation should return updated non-stale transaction data
        res2 = self.client.get("/api/reconciliation")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertGreater(data2["run"]["summary"]["total_transactions"], 0)

    def test_t13_2_state_invalidation_after_exception_and_delete(self):
        """T13.2: Verify state invalidation flow after running reconciliation and clearing statements."""
        # Upload primary statement
        csv_data = "Date,Description,Amount,UTR\n2026-08-01,Payment A,1000.0,UTR555\n"
        imp = self.client.post(
            "/api/statements/import",
            data={"file": (io.BytesIO(csv_data.encode("utf-8")), "stmt.csv"), "name": "Stmt 1"},
            content_type="multipart/form-data"
        )
        stmt_id = imp.get_json()["results"][0]["statement_id"]

        # Run Auto Match
        rec = self.client.post("/api/reconcile")
        self.assertEqual(rec.status_code, 200)

        # Clear/Delete statement
        del_res = self.client.delete(f"/api/statements/{stmt_id}")
        self.assertEqual(del_res.status_code, 200)

        # Fetch overview - should be 0 transactions immediately
        ov = self.client.get("/api/reconciliation")
        self.assertEqual(ov.status_code, 200)
        self.assertEqual(ov.get_json()["run"]["summary"]["total_transactions"], 0)


    def test_non_zero_transaction_amounts_and_dates(self):
        """Assert that transactions and exceptions populate real non-zero amounts and dates."""
        csv_data = "Date,Description,Amount,Bank Transaction ID\n2026-08-28,V2 01 Bank Statement,370850.25,UTR218242398173\n"
        imp = self.client.post(
            "/api/statements/import",
            data={
                "file": (io.BytesIO(csv_data.encode("utf-8")), "v2_01_bank.csv"),
                "name": "V2 01 Bank Statement",
                "is_primary": "true"
            },
            content_type="multipart/form-data"
        )
        self.assertEqual(imp.status_code, 200)

        # Run Auto Match
        rec = self.client.post("/api/reconcile")
        self.assertEqual(rec.status_code, 200)

        res = self.client.get("/api/reconciliation")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["run"]

        # Check transactions list
        self.assertGreater(len(data["transactions"]), 0)
        tx0 = data["transactions"][0]
        self.assertAlmostEqual(tx0["amount"], 370850.25)
        self.assertEqual(tx0["date"], "2026-08-28")

        # Check exceptions list if present
        if data["exceptions"]:
            exc0 = data["exceptions"][0]
            self.assertAlmostEqual(float(exc0["amount"]), 370850.25)


if __name__ == "__main__":
    unittest.main()
