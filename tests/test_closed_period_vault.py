import json
import pytest
import os
from frontend.app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_closed_period_vault_flow(client):
    # 1. Get closed periods list (should return list)
    resp = client.get('/api/closed_periods')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert isinstance(data['periods'], list)

    # 2. Trigger Close Period for test run
    close_resp = client.post('/api/close_period', json={'run_id': 'test-run-123'})
    assert close_resp.status_code == 200
    close_data = close_resp.get_json()
    assert close_data['ok'] is True
    assert 'period_id' in close_data
    period_id = close_data['period_id']
    assert close_data['pdf_url'] == f'/api/closed_periods/{period_id}/download/pdf'
    assert close_data['xlsx_url'] == f'/api/closed_periods/{period_id}/download/xlsx'

    # 3. Verify period appears in index
    resp_after = client.get('/api/closed_periods')
    assert resp_after.status_code == 200
    periods = resp_after.get_json()['periods']
    assert len(periods) >= 1
    assert periods[0]['period_id'] == period_id

    # 4. Download PDF & XLSX
    pdf_resp = client.get(f'/api/closed_periods/{period_id}/download/pdf')
    assert pdf_resp.status_code == 200

    xlsx_resp = client.get(f'/api/closed_periods/{period_id}/download/xlsx')
    assert xlsx_resp.status_code == 200

    # 5. Clear all past records
    clear_resp = client.post('/api/closed_periods/clear_all')
    assert clear_resp.status_code == 200
    assert clear_resp.get_json()['ok'] is True

    # 6. Index should now be empty
    resp_cleared = client.get('/api/closed_periods')
    assert len(resp_cleared.get_json()['periods']) == 0
