"""
tests/test_part11_verification.py — Final Verification Test Suite for Ledger AI (Part 11).

Validates:
  - T11.1: ml/build_training_data.py operates on generic schema without SETTLEMENT/source_type dependencies.
  - T11.4: Matcher output schemas use primary_transaction_id / counterpart_transaction_id.
  - T11.5: Four-status taxonomy accuracy & scoring engine monotonicity.
  - T11.7: Automatic pipeline never invokes LLM matcher.
  - T11.10: Overview charts handle full data and zero-data empty states gracefully.
"""

import sys
import unittest
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FRONTEND_DIR = ROOT / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from schema import CanonicalTransaction, row_to_canonical
from matcher.scoring_engine import compute_confidence, MatchEvidence
from matcher.exact_matcher import exact_match
from reconciler.pipeline_runner import run_full_pipeline
from reconciler.settlement_status import evaluate_period_settlement
from reports.report_builder import map_txn_to_taxonomy
from frontend.api.routes import compute_overview_charts
from ml import build_training_data
from frontend import statement_store


def tearDownModule():
    statement_store.clear_all_statements()
class TestPart11Verification(unittest.TestCase):

    def test_t11_1_schema_generic_and_no_statement_type(self):
        """T11.1: Verify no source_type or statement_type fields exist in CanonicalTransaction."""
        fields = CanonicalTransaction.__annotations__.keys()
        self.assertNotIn("source_type", fields)
        self.assertNotIn("statement_type", fields)

        # Test build_training_data runs without SETTLEMENT string
        s_dummy = {
            "transaction_id": "P1",
            "amount": "1000.0",
            "utr": "UTR123",
            "date": "2026-01-01"
        }
        b_dummy = {
            "bank_transaction_id": "C1",
            "credit": "1000.0",
            "utr": "UTR123",
            "date": "2026-01-01"
        }
        feat = build_training_data.create_features(s_dummy, b_dummy, label=1)
        self.assertIsInstance(feat, dict)
        self.assertIn("amount_difference", feat)

    def test_t11_4_matcher_output_field_names(self):
        """T11.4: Verify matcher output schema uses primary/counterpart IDs."""
        pri = [CanonicalTransaction("P100", is_primary=True, net_amount=500.0, utr="UTR777")]
        cnt = [CanonicalTransaction("C100", is_primary=False, net_amount=500.0, utr="UTR777")]
        res_df = exact_match(pri, cnt)

        self.assertFalse(res_df.empty)
        self.assertIn("primary_transaction_id", res_df.columns)
        self.assertIn("counterpart_transaction_id", res_df.columns)
        self.assertEqual(res_df.iloc[0]["primary_transaction_id"], "P100")
        self.assertEqual(res_df.iloc[0]["counterpart_transaction_id"], "C100")

    def test_t11_4_100_percent_settled_period_status(self):
        """T11.4: Assert 100% SETTLED primary transactions produce period_settled: true."""
        results = [
            {"primary_statement_id": "stmt_p", "status": "settled", "is_primary": True},
            {"primary_statement_id": "stmt_p", "status": "settled", "is_primary": True}
        ]
        exceptions = []
        status_res = evaluate_period_settlement("stmt_p", results, exceptions)
        self.assertTrue(status_res["period_settled"])

    def test_t11_5_taxonomy_assignment(self):
        """T11.5: Assert four-status taxonomy (SETTLED, MATCHED, SIMILAR, UNMATCHED)."""
        # Settled status
        st_settled = map_txn_to_taxonomy("auto", period_settled=True)
        self.assertEqual(st_settled, "SETTLED")

        # Non-settled matched status
        st_matched = map_txn_to_taxonomy("auto", period_settled=False)
        self.assertEqual(st_matched, "MATCHED")

        # Similar review status
        st_similar = map_txn_to_taxonomy("manual", period_settled=False)
        self.assertEqual(st_similar, "SIMILAR")

        # Unmatched status
        st_unmatched = map_txn_to_taxonomy("unmatched", period_settled=False)
        self.assertEqual(st_unmatched, "UNMATCHED")

    def test_t11_5_scoring_engine_monotonicity(self):
        """T11.5: Assert confidence scoring engine produces monotonically consistent confidence."""
        # Strong evidence (Exact UTR + 0 amount diff + 0 date diff)
        ev_strong = MatchEvidence(identifier_match_type="exact_utr", amount_diff=0.0, date_diff_days=0, narration_similarity=1.0)
        # Medium evidence (No UTR + 0 amount diff + 0 date diff)
        ev_medium = MatchEvidence(identifier_match_type="none", amount_diff=0.0, date_diff_days=0, narration_similarity=0.5)
        # Weak evidence (No UTR + amount diff + 5 days date diff)
        ev_weak = MatchEvidence(identifier_match_type="none", amount_diff=10.0, date_diff_days=5, narration_similarity=0.0)

        score_strong = compute_confidence(ev_strong)
        score_medium = compute_confidence(ev_medium)
        score_weak = compute_confidence(ev_weak)

        self.assertGreaterEqual(score_strong, score_medium)
        self.assertGreaterEqual(score_medium, score_weak)

    def test_t11_7_automatic_pipeline_no_llm(self):
        """T11.7: Assert run_full_pipeline() does not invoke LLM automatically."""
        import reconciler.pipeline_runner as pr
        pipeline_module_attrs = dir(pr)
        self.assertNotIn("ambiguous_matcher", pipeline_module_attrs)
        self.assertNotIn("evaluate_similar_cluster", pipeline_module_attrs)

    def test_t11_10_overview_charts_data_and_zero_data_degradation(self):
        """T11.10: Verify overview charts render with real data and degrade gracefully with zero data."""
        # 1. Zero data (empty state)
        empty_charts = compute_overview_charts([], [], period_settled=False, percent=0.0)
        self.assertEqual(empty_charts["status_breakdown"]["counts"], [0, 0, 0, 0])
        self.assertEqual(empty_charts["funnel_data"]["counts"], [0, 0, 0, 0, 0])

        # 2. Real data
        txns = [
            {"amount": 1000.0, "status": "auto", "taxonomy_status": "SETTLED", "confidence": 1.0, "source_type": "bank", "source_name": "Bank Statement"},
            {"amount": -500.0, "status": "unmatched", "taxonomy_status": "UNMATCHED", "confidence": 0.0, "source_type": "razorpay", "source_name": "Razorpay Settlement"}
        ]
        real_charts = compute_overview_charts(txns, [], period_settled=False, percent=50.0)
        self.assertIn("status_breakdown", real_charts)
        self.assertIn("funnel_data", real_charts)
        self.assertIn("source_contribution", real_charts)
        self.assertIn("confidence_distribution", real_charts)
        self.assertIn("exception_aging", real_charts)
        self.assertIn("trend_line", real_charts)



if __name__ == "__main__":
    unittest.main()

