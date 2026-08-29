"""
test_api_contract.py — Contract Test Suite for Ledger AI v2 (Phase 8 / T6.2).

Validates top-level JSON structure and type requirements for every endpoint defined in api/CONTRACT.md.
Acts as a regression gate: any change to internal engines or schemas must maintain backward-compatible
API response shapes for the frontend.
"""

import sys
import unittest
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FRONTEND_DIR = ROOT / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from frontend.app import app
from frontend import statement_store


def tearDownModule():
    statement_store.clear_all_statements()


class TestApiContract(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        statement_store.clear_all_statements()

    def tearDown(self):
        statement_store.clear_all_statements()

    # ============================================================
    # 1. STATEMENT STORE API CONTRACT TESTS (T6.2)
    # ============================================================

    def test_get_statements_contract(self):
        res = self.client.get("/api/statements")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("statements"), list)

    def test_statement_import_contract(self):
        csv_data = "Date,Description,Amount,UTR\n2026-08-01,Test Entry,1000.0,UTR9999\n"
        data = {
            "file": (io.BytesIO(csv_data.encode("utf-8")), "import_test.csv"),
            "name": "Contract Test Statement",
            "source_type": "bank",
            "color": "#3b82f6",
            "statement_type_label": "Bank Statement",
            "rules": ""
        }
        res = self.client.post("/api/statements/import", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("ok"))
        self.assertIn("statement", res_json)
        stmt = res_json["statement"]
        self.assertIn("id", stmt)
        self.assertEqual(stmt.get("name"), "Contract Test Statement")

    def test_statement_crud_contract(self):
        # 1. Import temporary statement
        csv_data = "Date,Description,Amount,UTR\n2026-08-01,CRUD Entry,500.0,UTR0001\n"
        imp_data = {
            "file": (io.BytesIO(csv_data.encode("utf-8")), "crud_test.csv"),
            "name": "CRUD Test Statement",
            "source_type": "bank",
        }
        imp_res = self.client.post("/api/statements/import", data=imp_data, content_type="multipart/form-data")
        stmt_id = imp_res.get_json()["statement"]["id"]

        # 2. GET statement
        get_res = self.client.get(f"/api/statements/{stmt_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue(get_res.get_json().get("ok"))

        # 3. Rename statement
        rename_res = self.client.post(f"/api/statements/{stmt_id}/rename", json={"name": "Renamed Statement"})
        self.assertEqual(rename_res.status_code, 200)
        self.assertTrue(rename_res.get_json().get("ok"))

        # 4. Append statement
        app_csv = "Date,Description,Amount,UTR\n2026-08-02,Appended Entry,750.0,UTR0002\n"
        app_res = self.client.post(f"/api/statements/{stmt_id}/append", data={"file": (io.BytesIO(app_csv.encode("utf-8")), "app.csv")}, content_type="multipart/form-data")
        self.assertEqual(app_res.status_code, 200)
        self.assertTrue(app_res.get_json().get("ok"))

        # 5. Update rows
        up_res = self.client.post(f"/api/statements/{stmt_id}/update-rows", json={"rows": [{"row_index": 0, "updates": {"Description": "Updated Entry"}}]})
        self.assertEqual(up_res.status_code, 200)
        self.assertTrue(up_res.get_json().get("ok"))

        # 6. Delete columns
        del_col_res = self.client.post(f"/api/statements/{stmt_id}/delete-columns", json={"columns": ["UTR"]})
        self.assertEqual(del_col_res.status_code, 200)
        self.assertTrue(del_col_res.get_json().get("ok"))

        # 7. DELETE statement
        del_res = self.client.delete(f"/api/statements/{stmt_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json().get("ok"))

    def test_clear_data_contract(self):
        res = self.client.post("/api/data/clear")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("message", data)

    # ============================================================
    # 2. LEGACY UPLOAD API CONTRACT TESTS (T6.2)
    # ============================================================

    def test_legacy_upload_bank_contract(self):
        csv_data = "Date,Description,Amount,UTR\n2026-08-01,Bank Entry,1000.0,UTR111\n"
        data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "legacy_bank.csv")}
        res = self.client.post("/api/upload/bank", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("ok"))
        self.assertEqual(res_json.get("source"), "bank")

    def test_legacy_upload_razorpay_contract(self):
        csv_data = "Date,Settlement ID,Amount,UTR\n2026-08-01,SETL001,1000.0,UTR222\n"
        data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "legacy_rzp.csv")}
        res = self.client.post("/api/upload/razorpay", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("ok"))
        self.assertEqual(res_json.get("source"), "razorpay")

    def test_legacy_upload_orders_contract(self):
        csv_data = "Order ID,Date,Amount\nORD001,2026-08-01,1000.0\n"
        data = {"file": (io.BytesIO(csv_data.encode("utf-8")), "legacy_orders.csv")}
        res = self.client.post("/api/upload/orders", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("ok"))
        self.assertEqual(res_json.get("source"), "orders")

    # ============================================================
    # 3. RECONCILIATION & DASHBOARD CONTRACT TESTS (T6.2)
    # ============================================================

    def test_reconcile_trigger_contract(self):
        res = self.client.post("/api/reconcile", json={"period_label": "Test Period"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("run_id", data)

    def test_reconciliation_contract(self):
        res = self.client.get("/api/reconciliation")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("ok"))
        self.assertIn("run", data)

    def test_reconciliation_runs_contract(self):
        res = self.client.get("/api/reconciliation/runs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("runs"), list)

    def test_transactions_contract(self):
        res = self.client.get("/api/transactions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("transactions"), list)

    def test_exceptions_contract(self):
        res = self.client.get("/api/exceptions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("exceptions"), list)

    def test_dashboard_summary_contract(self):
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("summary"), dict)

    def test_report_html_contract(self):
        res = self.client.get("/api/report-html")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

    def test_pipeline_status_contract(self):
        res = self.client.get("/api/pipeline/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("stage", data)


    def test_config_contract(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("config"), dict)

    # ============================================================
    # 4. MANUAL OVERRIDES & SIMILARITY CONTRACT TESTS (T6.2)
    # ============================================================

    def test_similar_payments_contract(self):
        res = self.client.get("/api/similar-payments?settlement_id=SETL100&amount=1000")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

    def test_flag_manual_contract(self):
        res = self.client.post("/api/transactions/flag-manual", json={"transaction_id": "SETL100", "reason": "Audit"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

    def test_rematch_llm_contract(self):
        res = self.client.post("/api/transactions/rematch-llm", json={"settlement_id": "SETL100", "bank_transaction_id": "BANK100"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

    def test_override_status_contract(self):
        res = self.client.post("/api/transactions/override-status", json={"settlement_id": "SETL100", "bank_transaction_id": "BANK100", "target_status": "matched"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))

    # ============================================================
    # 5. CHAT Q&A CONTRACT TESTS (T6.2)
    # ============================================================

    def test_chat_sessions_contract(self):
        res = self.client.get("/api/chat/sessions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("sessions"), list)

    def test_chat_create_and_delete_session_contract(self):
        # 1. Create session
        res = self.client.post("/api/chat/sessions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        sess_id = data["session"]["id"]

        # 2. Get session
        get_res = self.client.get(f"/api/chat/sessions/{sess_id}")
        self.assertEqual(get_res.status_code, 200)

        # 3. Post message
        msg_res = self.client.post(f"/api/chat/sessions/{sess_id}/messages", json={"message": "Hello Ledger"})
        self.assertEqual(msg_res.status_code, 200)

        # 4. Delete session
        del_res = self.client.delete(f"/api/chat/sessions/{sess_id}")
        self.assertEqual(del_res.status_code, 200)

    def test_direct_chat_contract(self):
        res = self.client.post("/api/chat", json={"message": "What is the settlement status?"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("answer", data)

    # ============================================================
    # 6. REPORT EXPORT CONTRACT TESTS (T10.4)
    # ============================================================

    def test_reports_export_pdf_contract(self):
        payload = {
            "format": "pdf",
            "statuses": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"],
            "sources": ["all"],
            "sections": ["summary", "charts", "transactions", "exceptions", "integrity"]
        }
        res = self.client.post("/api/reports/export", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/pdf")
        self.assertTrue(res.data.startswith(b"%PDF"))

    def test_reports_export_markdown_contract(self):
        payload = {
            "format": "markdown",
            "statuses": ["SETTLED", "MATCHED"],
            "sources": ["all"],
            "sections": ["summary", "transactions"]
        }
        res = self.client.post("/api/reports/export", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "text/markdown")
        self.assertIn(b"# Ledger Reconciliation Report", res.data)


if __name__ == "__main__":
    unittest.main()

