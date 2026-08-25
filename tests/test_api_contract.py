"""
test_api_contract.py — Contract Test Suite for Ledger AI v2 (Phase 8 / T8.2).

Validates top-level JSON structure and type requirements for every endpoint defined in api/CONTRACT.md.
Acts as a regression gate: any change to internal engines or schemas must maintain backward-compatible
API response shapes for the frontend.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FRONTEND_DIR = ROOT / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from frontend.app import app


class TestApiContract(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    # ============================================================
    # 1. STATEMENT STORE API CONTRACT TESTS (T8.4)
    # ============================================================

    def test_get_statements_contract(self):
        res = self.client.get("/api/statements")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("statements"), list)

    # ============================================================
    # 2. LEGACY UPLOAD API CONTRACT TESTS (T8.4)
    # ============================================================

    def test_legacy_upload_contract(self):
        sample_path = ROOT / "data" / "generated" / "bank_statement.csv"
        if sample_path.exists():
            with open(sample_path, "rb") as f:
                data = {"file": (f, "test_bank.csv")}
                res = self.client.post("/api/upload/bank", data=data, content_type="multipart/form-data")
                self.assertEqual(res.status_code, 200)
                res_json = res.get_json()
                self.assertTrue(res_json.get("ok"))
                self.assertEqual(res_json.get("source"), "bank")
                self.assertIn("upload_id", res_json)
                self.assertIn("filename", res_json)
                self.assertIn("uploaded_at", res_json)

    # ============================================================
    # 3. RECONCILIATION & DASHBOARD CONTRACT TESTS (T8.3)
    # ============================================================

    def test_reconciliation_contract(self):
        res = self.client.get("/api/reconciliation")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIn("run", data)

        run = data["run"]
        if run is not None:
            self.assertIsInstance(run.get("run_id"), str)
            self.assertIsInstance(run.get("summary"), dict)
            self.assertIsInstance(run.get("transactions"), list)
            self.assertIsInstance(run.get("exceptions"), list)

    def test_transactions_contract(self):
        res = self.client.get("/api/transactions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("count"), int)
        self.assertIsInstance(data.get("transactions"), list)

        if data["transactions"]:
            tx = data["transactions"][0]
            self.assertIn("status", tx)
            self.assertIn("resolved_by", tx)
            self.assertIn("confidence", tx)
            self.assertIn("evidence", tx)
            ev = tx["evidence"]
            self.assertIn("amount_difference", ev)
            self.assertIn("date_difference_days", ev)
            self.assertIn("identifier_matched", ev)
            self.assertIn("candidate_count", ev)

    def test_exceptions_contract(self):
        res = self.client.get("/api/exceptions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("exceptions"), list)

    def test_dashboard_summary_contract(self):
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("summary"), dict)

    def test_config_contract(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("config"), dict)
        cfg = data["config"]
        self.assertIn("schema_version", cfg)
        self.assertIn("absolute_amount_tolerance", cfg)
        self.assertIn("ml_match_threshold", cfg)

    # ============================================================
    # 4. CHAT Q&A CONTRACT TESTS (T8.5)
    # ============================================================

    def test_chat_sessions_contract(self):
        res = self.client.get("/api/chat/sessions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("sessions"), list)

    def test_chat_create_session_contract(self):
        res = self.client.post("/api/chat/sessions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIn("session", data)
        sess = data["session"]
        self.assertIn("id", sess)
        self.assertIn("title", sess)
        self.assertIn("message_count", sess)


if __name__ == "__main__":
    unittest.main()
