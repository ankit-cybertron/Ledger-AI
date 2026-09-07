"""
test_state_reset.py — Tests for State Reset on Reload and Session Invalidation.
Verifies that loading/reloading the dashboard clears existing statements,
reconciliation results, runs, and caches, ensuring user lands on an empty workspace.
"""

import os
import json
import pytest
import pandas as pd

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FRONTEND_DIR = ROOT / "frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from frontend.app import app
from frontend.api.routes import clear_all_data_state, _RUNS
from frontend import statement_store



@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["TESTING_DISABLE_AUTO_RESET"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = "demo"
        yield client


def test_clear_all_data_state_resets_everything():
    """Verify clear_all_data_state wipes store, runs, and results."""
    # Seed a dummy run
    _RUNS["test_run"] = {"status": "completed"}
    
    # Execute clear
    res = clear_all_data_state()
    assert res is True
    assert len(_RUNS) == 0
    
    # Check statements list is empty
    stmts = statement_store.list_statements()
    assert len(stmts) == 0


def test_dashboard_load_triggers_state_reset(client):
    """Verify GET /dashboard automatically clears state and renders HTTP 200."""
    # Populate a fake statement in statement store
    df = pd.DataFrame([{"transaction_date": "2024-01-01", "net_amount": 100.0, "description": "Test"}])
    statement_store.save_imported_statement(
        name="Test Statement",
        filename="test.csv",
        df=df,
        is_primary=True,
    )
    assert len(statement_store.list_statements()) >= 1

    # Request dashboard
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Import Statements" in resp.data

    # Verify statement store is now empty
    stmts_after = statement_store.list_statements()
    assert len(stmts_after) == 0


def test_overview_route_renders_200(client):
    """Verify GET /overview renders successfully without Jinja errors or redirects."""
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert b"Reconciliation" in resp.data
    assert b"Talk to Ledger" in resp.data

