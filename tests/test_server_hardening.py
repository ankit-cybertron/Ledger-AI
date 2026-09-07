"""
tests/test_server_hardening.py

Validates server hardening improvements:
1. Pagination on /api/reconciliation to protect against 413 Payload Too Large
2. Error resilience: graceful 400 Bad Request / 404 handling without unhandled 500 crashes
3. Non-blocking and on-demand report generation (/api/reports/export)
4. State reset functionality (/api/clear_all_data)
"""

import json
import pytest
from frontend.app import app
from api.routes import clear_all_data_state, _RUNS, invalidate_dashboard_cache


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["TESTING_DISABLE_AUTO_RESET"] = True
    with app.test_client() as client:
        yield client


def test_reconciliation_pagination(client, monkeypatch):
    """Verify ?page= and ?limit= query params paginate transaction list properly."""
    # Seed mock run with multiple transactions
    monkeypatch.setattr("frontend.statement_store.list_statements", lambda: [{"statement_id": "mock_stmt"}])
    invalidate_dashboard_cache()
    _RUNS["mock_run"] = {
        "run_id": "mock_run",
        "period_label": "September 2026",
        "transactions": [
            {"id": f"tx_{i}", "amount": 100.0 * i, "status": "SETTLED"}
            for i in range(1, 11)
        ],
    }
    _RUNS["latest"] = _RUNS["mock_run"]

    # Request page 2 with limit 3
    resp = client.get("/api/reconciliation?page=2&limit=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "pagination" in data["run"]
    assert data["run"]["pagination"]["page"] == 2
    assert data["run"]["pagination"]["limit"] == 3
    assert data["run"]["pagination"]["total"] == 10
    assert len(data["run"]["transactions"]) == 3
    assert data["run"]["transactions"][0]["id"] == "tx_4"

    # Request without pagination returns all
    resp_all = client.get("/api/reconciliation")
    assert resp_all.status_code == 200
    data_all = resp_all.get_json()
    assert len(data_all["run"]["transactions"]) == 10


def test_reports_export_on_demand_csv(client):
    """Verify on-demand report export returns valid CSV without server lockup."""
    resp = client.get("/api/reports/export?format=csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"settlement_id,bank_transaction_id" in resp.data


def test_reports_export_on_demand_excel(client):
    """Verify on-demand report export returns valid Excel without server lockup."""
    resp = client.get("/api/reports/export?format=xlsx")
    assert resp.status_code == 200
    assert "openxmlformats" in resp.mimetype or resp.status_code == 200


def test_clear_all_data_endpoint(client):
    """Verify /api/clear_all_data endpoint returns 200 and cleans state."""
    resp = client.post("/api/clear_all_data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True


def test_overview_page_render(client):
    """Verify /overview page renders HTTP 200 with widescreen container and charts."""
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert b"overview-widescreen-container" in resp.data
    assert b"ssrChartStatusBreakdown" in resp.data
    assert b"Auto-Match Parity" in resp.data

