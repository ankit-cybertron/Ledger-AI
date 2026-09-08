import io
import unittest
import pandas as pd
from pathlib import Path
from frontend.app import app
from frontend import statement_store
from ingestion.file_reader import read_source_file


def tearDownModule():
    statement_store.clear_all_statements()


class TestPdfAndMultiFileImport(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        statement_store.clear_all_statements()

    def tearDown(self):
        statement_store.clear_all_statements()

    def test_multi_file_import_resilience(self):
        """
        Acceptance Criteria Test:
        Uploading 3 files at once (2 good CSV files + 1 malformed/invalid file)
        succeeds for the 2 good files and reports a clear per-file error for the bad one.
        """
        good_csv_1 = (io.BytesIO(b"Date,Amount,Description\n2026-01-01,100.00,Test Payment 1\n"), "good_1.csv")
        good_csv_2 = (io.BytesIO(b"Date,Amount,Description\n2026-01-02,200.00,Test Payment 2\n"), "good_2.csv")
        bad_file = (io.BytesIO(b"binary garbage content"), "corrupted.xyz")

        response = self.client.post(
            "/api/statements/import",
            data={
                "file": [good_csv_1, good_csv_2, bad_file],
                "is_primary": "true",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("ok"))
        results = data.get("results", [])
        self.assertEqual(len(results), 3)

        success_results = [r for r in results if r["status"] == "success"]
        error_results = [r for r in results if r["status"] == "error"]

        self.assertEqual(len(success_results), 2)
        self.assertEqual(len(error_results), 1)

        self.assertIn("corrupted.xyz", error_results[0]["filename"])
        self.assertIsNotNone(error_results[0]["error_message"])

    def test_pdf_parsing_flow(self):
        """
        Test PDF reader fallback / handling in ingestion.file_reader
        """
        # Test file_reader returns empty list or valid RawTable without raising NotImplementedError
        test_pdf_path = Path(__file__).parent / "test_sample.pdf"
        if test_pdf_path.exists():
            tables = read_source_file(str(test_pdf_path))
            self.assertIsInstance(tables, list)
            if tables:
                table = tables[0]
                if table.rows:
                    self.assertIn("source_page", table.rows[0])
                    self.assertIn("source_row_number", table.rows[0])


if __name__ == "__main__":
    unittest.main()
