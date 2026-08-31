import pytest
from datetime import datetime, timedelta
from forecasting.engine import build_forecast, detect_recurring_patterns, estimate_pending_settlements

def test_forecaster_weekly_payroll():
    # Generate 4 weeks of synthetic data with weekly payroll (every Monday, -50000.0)
    txns = []
    start_date = datetime(2026, 8, 3)  # Monday
    
    # 4 weeks of data
    for week in range(4):
        monday = start_date + timedelta(weeks=week)
        # Payroll debit
        txns.append({
            "date": monday.strftime("%Y-%m-%d"),
            "amount": -50000.0,
            "description": "Weekly Payroll Transfer - Salary Account",
            "status": "SETTLED"
        })
        
        # Add daily business revenues
        for day in range(7):
            current_day = monday + timedelta(days=day)
            txns.append({
                "date": current_day.strftime("%Y-%m-%d"),
                "amount": 8000.0,
                "description": "Customer Payment Gateway settlement",
                "status": "SETTLED"
            })
            
    # Calculate forecast starting on August 31st (Monday)
    today = datetime(2026, 8, 31)
    
    # Run the pattern detector directly
    patterns = detect_recurring_patterns(txns)
    
    # Assert payroll pattern is detected
    payroll_patterns = [p for p in patterns if "payroll" in p["label"]]
    assert len(payroll_patterns) == 1, "Should detect exactly one payroll pattern"
    
    pat = payroll_patterns[0]
    assert pat["cadence_days"] == 7, "Payroll pattern should have a weekly cadence (7 days)"
    assert pat["avg_amount"] == -50000.0, "Average payroll amount should be -50000.0"
    assert pat["next_expected"] == "2026-08-31", "Next expected date should align on Monday, Aug 31"
    
    # Run the full forecast engine
    res = build_forecast(txns, forecast_days=30, today=today)
    
    assert res["summary"]["detected_patterns"] >= 1
    assert res["summary"]["current_balance"] > 0
    
    # Check that forecast contains projected rows
    forecast_rows = res["forecast"]
    assert len(forecast_rows) == 30
    
    # On Mondays (2026-09-07, 2026-09-14, 2026-09-21, 2026-09-28), the forecast should reflect payroll
    # Let's verify that projected net flow on these days is negative due to payroll blend
    monday_forecasts = [row for row in forecast_rows if row["date"] in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28")]
    assert len(monday_forecasts) > 0
    for row in monday_forecasts:
        # Without payroll, daily flow is +8000. With payroll overlay (blended by 0.5), it's 8000 + (-50000 * 0.5) = -17000
        assert row["projected"] < 0, f"Expected negative flow on Monday {row['date']}, got {row['projected']}"


def test_forecaster_pending_settlements():
    # Test pending settlement detection based on lag T+2
    today = datetime(2026, 8, 10)
    txns = [
        # Settled history to compute T+2 typical lag
        {"date": "2026-08-01", "amount": 1000.0, "status": "SETTLED"},
        {"date": "2026-08-02", "amount": 1000.0, "status": "SETTLED"},
        {"date": "2026-08-03", "amount": 1000.0, "status": "SETTLED"},
        # Unsettled batches dated 2 days ago (T-2, i.e., 2026-08-08)
        {"date": "2026-08-08", "amount": 12500.0, "status": "PROCESSING", "description": "Razorpay settlement batch RP_XYZ"}
    ]
    
    pending = estimate_pending_settlements(txns, today=today)
    
    assert len(pending) == 1
    assert pending[0]["amount"] == 12500.0
    assert pending[0]["expected_settlement"] == "2026-08-10", "Should expect settlement on T+2 (Aug 10)"
