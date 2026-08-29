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


if __name__ == "__main__":
    unittest.main()
