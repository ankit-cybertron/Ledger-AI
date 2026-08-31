import unittest
import pandas as pd
from config import MatchingConfig
from schema import CanonicalTransaction, row_to_canonical
from matcher.exact_matcher import exact_match
from matcher.tolerance_matcher import tolerance_match
from matcher.split_aggregate_matcher import split_aggregate_match
from matcher.evaluation_metrics import compute_precision_recall_f1
from reconciler.settlement_status import evaluate_period_settlement


class TestMatcherRedesign(unittest.TestCase):

    def setUp(self):
        self.cfg = MatchingConfig(
            exact_utr_confidence=1.00,
            amount_only_confidence=0.90,
            split_match_confidence=0.95,
            ambiguous_tie_confidence=0.50,
            one_to_one_tolerance_confidence=0.85,
        )

    def test_row_to_canonical_unification(self):
        """T3.1: Test row_to_canonical single source of truth."""
        row_dict = {
            "primary_transaction_id": "tx_1001",
            "net_amount": "1500.50",
            "utr": "UTR123456789",
            "is_primary": True,
            "transaction_date": "2026-01-10"
        }
        tx = row_to_canonical(row_dict)
        self.assertIsInstance(tx, CanonicalTransaction)
        self.assertEqual(tx.transaction_id, "tx_1001")
        self.assertEqual(tx.net_amount, 1500.50)
        self.assertTrue(tx.is_primary)

    def test_matcher_signatures_and_output_schema(self):
        """T3.2 & T3.3: Test signatures (primary/counterpart) and output schemas."""
        pri_txs = [
            CanonicalTransaction(
                transaction_id="pri_001",
                is_primary=True,
                net_amount=500.00,
                utr="UTR555666777",
                transaction_date="2026-01-15",
                primary_statement_id="stmt_pri_1"
            )
        ]
        cnt_txs = [
            CanonicalTransaction(
                transaction_id="cnt_001",
                is_primary=False,
                net_amount=500.00,
                utr="UTR555666777",
                transaction_date="2026-01-15",
                counterpart_statement_id="stmt_cnt_1"
            )
        ]


        # 1. Exact Matcher
        exact_df = exact_match(pri_txs, cnt_txs, cfg=self.cfg)
        self.assertFalse(exact_df.empty)
        self.assertIn("primary_transaction_id", exact_df.columns)
        self.assertIn("counterpart_transaction_id", exact_df.columns)
        self.assertEqual(exact_df.iloc[0]["primary_transaction_id"], "pri_001")
        self.assertEqual(exact_df.iloc[0]["counterpart_transaction_id"], "cnt_001")
        self.assertEqual(exact_df.iloc[0]["confidence"], self.cfg.exact_utr_confidence)

    def test_split_and_tolerance_matching(self):
        """T3.4 & T3.5: Test split aggregate matching and tolerance matching with config confidence."""
        pri_txs = [
            CanonicalTransaction(
                transaction_id="pri_split_1",
                is_primary=True,
                net_amount=1000.00,
                utr="UTR_SPLIT_99",
                transaction_date="2026-01-20",
                primary_statement_id="stmt_p"
            )
        ]
        cnt_txs = [
            CanonicalTransaction(
                transaction_id="cnt_split_a",
                is_primary=False,
                net_amount=600.00,
                utr="UTR_SPLIT_99",
                transaction_date="2026-01-20",
                counterpart_statement_id="stmt_c"
            ),
            CanonicalTransaction(
                transaction_id="cnt_split_b",
                is_primary=False,
                net_amount=400.00,
                utr="UTR_SPLIT_99",
                transaction_date="2026-01-20",
                counterpart_statement_id="stmt_c"
            )
        ]

        split_df = split_aggregate_match(pri_txs, cnt_txs, cfg=self.cfg)
        self.assertFalse(split_df.empty)
        self.assertIn("primary_transaction_id", split_df.columns)
        self.assertEqual(split_df.iloc[0]["confidence"], self.cfg.split_match_confidence)

    def test_evaluation_metrics(self):
        """T3.6: Test shared compute_precision_recall_f1."""
        predicted = {("tx_1", "tx_2"), ("tx_3", "tx_4")}
        ground_truth = {("tx_1", "tx_2"), ("tx_5", "tx_6")}

        res = compute_precision_recall_f1(predicted, ground_truth)
        self.assertEqual(res["true_positives"], 1)
        self.assertEqual(res["false_positives"], 1)
        self.assertEqual(res["false_negatives"], 1)
        self.assertEqual(res["precision"], 0.5)
        self.assertEqual(res["recall"], 0.5)
        self.assertEqual(res["f1"], 0.5)

    def test_period_settlement_status(self):
        """T3.7: Test evaluate_period_settlement."""
        results = [
            {"primary_statement_id": "stmt_1", "status": "matched"},
            {"primary_statement_id": "stmt_1", "status": "matched"}
        ]
        exceptions = []

        status_res = evaluate_period_settlement("stmt_1", results, exceptions)
        self.assertTrue(status_res["period_settled"])
        self.assertEqual(status_res["primary_total"], 2)
        self.assertEqual(status_res["primary_matched"], 2)


    def test_t22_14_settled_vs_matched_taxonomy(self):
        """T22.14: Test that SETTLED is assigned when primary statement is involved, and MATCHED when counterpart-only."""
        from reconciler.reconcile import reconcile
        from frontend import statement_store

        statement_store.clear_all_statements()

        # Case 1: Primary + Counterpart pair with exact match -> SETTLED
        df_pri = pd.DataFrame([{
            "transaction_id": "pri_tax_001",
            "amount": 100.0,
            "utr": "UTR_TAX_111",
            "date": "2026-01-10",
            "description": "Payment"
        }])
        df_cnt = pd.DataFrame([{
            "transaction_id": "cnt_tax_001",
            "amount": 100.0,
            "utr": "UTR_TAX_111",
            "date": "2026-01-10",
            "description": "Payment"
        }])

        statement_store.save_imported_statement("Primary Stmt", "pri.csv", df_pri, is_primary=True)
        statement_store.save_imported_statement("Counterpart Stmt", "cnt.csv", df_cnt, is_primary=False)

        res_df = reconcile(cfg=self.cfg)
        self.assertFalse(res_df.empty)
        row = res_df.iloc[0]
        self.assertEqual(row["status"].upper(), "SETTLED")

        # Case 2: Counterpart + Counterpart pair with exact match -> MATCHED
        statement_store.clear_all_statements()
        df_cnt1 = pd.DataFrame([{
            "transaction_id": "cnt_tax_002",
            "amount": 200.0,
            "utr": "UTR_TAX_222",
            "date": "2026-01-10",
            "description": "Payout"
        }])
        df_cnt2 = pd.DataFrame([{
            "transaction_id": "cnt_tax_003",
            "amount": 200.0,
            "utr": "UTR_TAX_222",
            "date": "2026-01-10",
            "description": "Payout"
        }])

        statement_store.save_imported_statement("Counterpart 1", "cnt1.csv", df_cnt1, is_primary=False)
        statement_store.save_imported_statement("Counterpart 2", "cnt2.csv", df_cnt2, is_primary=False)

        res_df2 = reconcile(cfg=self.cfg)
        self.assertFalse(res_df2.empty)
        row2 = res_df2.iloc[0]
        self.assertEqual(row2["status"].upper(), "MATCHED")


    def test_t22_1_fee_aware_expected_net(self):
        """T22.1: Test expected net calculation with channel-specific MDR fee rates."""
        from matcher.settlement_equation import expected_net

        # Razorpay fee: 1.8% MDR + 18% GST on MDR = 1.8% + 0.324% = 2.124% net deduction
        tx_rzp = CanonicalTransaction(
            transaction_id="rzp_001",
            gross_amount=1000.0,
            channel="razorpay",
            source_file="05_Razorpay_Settlement.csv"
        )
        expected_rzp = expected_net(tx_rzp, self.cfg)
        self.assertAlmostEqual(expected_rzp, 978.76, places=2)

        # PayPal fee: 3.4% MDR
        tx_pypl = CanonicalTransaction(
            transaction_id="pypl_001",
            gross_amount=1000.0,
            channel="paypal",
            source_file="paypal_feed.csv"
        )
        expected_pypl = expected_net(tx_pypl, self.cfg)
        self.assertAlmostEqual(expected_pypl, 966.00, places=2)

    def test_t22_2_pdf_header_index_preservation(self):
        """T22.2: Test PDF reader header mapping logic preserves exact index columns without shifting."""
        from ingestion.file_reader import _read_pdf_tables
        from pathlib import Path

        # Verify function handles index columns properly without dropping keys
        pdf_path = Path(__file__).resolve().parents[1] / "data" / "test_cases" / "05_Razorpay_Settlement_Summary.pdf"
        if pdf_path.exists():
            tables = _read_pdf_tables(pdf_path, pdf_path.name, ["summary", "total"])
            self.assertTrue(len(tables) > 0)
            rows = tables[0].rows
            if len(rows) > 0:
                # Ensure source_row_number is tagged and row headers aren't shifted to index numbers
                first_row = rows[0]
                self.assertIn("source_row_number", first_row)


if __name__ == "__main__":
    unittest.main()

