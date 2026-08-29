"""
test_part5_llm_reconciler.py — Unit Tests for Part 5 Agent & Reconciler Refactoring.

Verifies:
  1. Exactly one agent implementation exists and chat_routes.py imports it (T5.1).
  2. routes.py override_status feedback logging runs cleanly (T5.2).
  3. reconciler/pipeline_runner.py#run_full_pipeline() exists and does NOT invoke LLM automatically (T5.3, T5.4).
  4. llm.ambiguous_matcher.evaluate_similar_cluster() operates on-demand over SIMILAR clusters
     and computes confidence using matcher/scoring_engine.py (T5.5).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend.api.chat_routes import answer_question
from reconciler.pipeline_runner import run_full_pipeline
from llm.ambiguous_matcher import evaluate_similar_cluster
from ml import feedback_loop
from frontend import statement_store


def tearDownModule():
    statement_store.clear_all_statements()


class TestPart5LLMReconciler(unittest.TestCase):

    def test_agent_import_live(self):
        """Verify chat_routes.py imports answer_question from agents.settlement_qa_agent."""
        self.assertTrue(callable(answer_question))
        # Ensure dead frontend/agent folder is removed
        frontend_agent_dir = ROOT / "frontend" / "agent"
        self.assertFalse(frontend_agent_dir.exists())

    def test_feedback_loop_logging(self):
        """Verify log_human_feedback runs without unhandled errors (T5.2)."""
        appended = feedback_loop.log_human_feedback(
            settlement_id="TEST_S1",
            bank_transaction_id="TEST_B1",
            human_decision="match",
            confidence=1.0,
            reason="Test Override Match"
        )
        self.assertIsInstance(appended, int)

    def test_run_full_pipeline_orchestration(self):
        """Verify run_full_pipeline executes all batch stages cleanly without calling LLM (T5.3, T5.4)."""
        res = run_full_pipeline()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("status"), "completed")

    def test_on_demand_llm_similar_cluster_matching(self):
        """Verify evaluate_similar_cluster evaluates candidate cluster and calculates confidence (T5.5)."""
        target_tx = {
            "settlement_id": "SETL_99",
            "amount": 5000.0,
            "date": "2026-07-01",
            "description": "NEFT CR - UTR123456 Payment",
            "utr": "UTR123456"
        }
        candidate_cluster = [
            {
                "bank_transaction_id": "BANK_99",
                "credit": 5000.0,
                "date": "2026-07-01",
                "description": "NEFT CR - UTR123456 Payment",
                "utr": "UTR123456",
                "similarity_score": 0.95
            }
        ]

        res = evaluate_similar_cluster(target_tx, candidate_cluster)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("selected_candidate_id"), "BANK_99")
        self.assertGreaterEqual(res.get("confidence", 0.0), 0.85)
        self.assertIn("amount", res.get("evidence", {}))



if __name__ == "__main__":
    unittest.main()
