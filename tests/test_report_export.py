"""
tests/test_report_export.py — Comprehensive unit tests for Part 10 Report Builder & PDF Export.

Validates:
  - Numerical parity between Markdown report stats and PDF report data (T10.2 / T10.3).
  - Status, source, and date filtering logic.
  - PDF generation binary integrity.
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

from reports.report_builder import build_filtered_report_data
from reports.generate_report import build_markdown_report
from reports.pdf_generator import generate_pdf_report
from frontend import statement_store


def tearDownModule():
    statement_store.clear_all_statements()


class TestReportExport(unittest.TestCase):

    def test_report_builder_defaults(self):
        data = build_filtered_report_data()
        self.assertIn("summary", data)
        self.assertIn("transactions", data)
        self.assertIn("exceptions", data)
        self.assertIn("charts", data)
        self.assertIn("integrity", data)
        self.assertTrue(data["integrity"]["pass"])

    def test_status_filtering_numerical_parity(self):
        filters = {
            "statuses": ["SETTLED", "MATCHED"],
            "sources": ["all"],
            "sections": ["summary", "transactions"]
        }
        data = build_filtered_report_data(filters)
        md_text = build_markdown_report(filters=filters)
        pdf_bytes = generate_pdf_report(filters=filters)

        # Check PDF binary
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # Verify Markdown numerical parity
        summary = data["summary"]
        self.assertIn(f"| Transactions Processed | {summary['total_transactions']} |", md_text)
        self.assertIn(f"| Settled / Auto-Matched | {summary['settled_count'] + summary['matched_count']} |", md_text)

    def test_date_range_filtering(self):
        filters = {
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "statuses": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]
        }
        data = build_filtered_report_data(filters)
        self.assertIsInstance(data["transactions"], list)

    def test_statement_source_filtering(self):
        filters = {
            "sources": ["NonExistentSource"],
            "statuses": ["SETTLED", "MATCHED", "SIMILAR", "UNMATCHED"]
        }
        data = build_filtered_report_data(filters)
        self.assertEqual(len(data["transactions"]), 0)
        self.assertEqual(data["summary"]["total_transactions"], 0)

    def test_currency_symbol_inr(self):
        md_text = build_markdown_report()
        self.assertIn("₹", md_text)
        self.assertNotIn("Deposits Total | $", md_text)

    def test_engine_decision_formatting(self):
        from reports.pdf_generator import format_engine_decision
        exact_t = {"status": "auto", "stage": "exact"}
        tol_t = {"status": "tolerance", "stage": "tolerance"}
        ml_t = {"status": "ml", "stage": "ml", "confidence": 0.95}
        llm_t = {"status": "llm", "stage": "llm"}
        man_t = {"status": "manual", "stage": "manual"}
        unm_t = {"status": "unmatched", "stage": "unmatched"}

        self.assertEqual(format_engine_decision(exact_t), "Rule Engine: Exact UTR Match")
        self.assertEqual(format_engine_decision(tol_t), "Rule Engine: Tolerance Match")
        self.assertEqual(format_engine_decision(ml_t), "ML Model (0.95)")
        self.assertEqual(format_engine_decision(llm_t), "Groq LLM Agent")
        self.assertEqual(format_engine_decision(man_t), "Manual Review Override")
        self.assertEqual(format_engine_decision(unm_t), "Unmatched Exception")


if __name__ == "__main__":
    unittest.main()

