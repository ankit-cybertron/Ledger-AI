# Forward Cash Forecaster — Technical Specification & Architecture Guide

## 1. Executive Summary

The **Forward Cash Forecaster** is a rules-first financial projection engine built for the Ledger AI platform (`forecasting/engine.py`). It predicts future cash flow trajectories, estimates settlement dates for open gateway batches, overlay recurring cash flow patterns, and computes 30-day liquid cash availability starting from the platform's **Beginning Balance**.

The module operates on canonical transaction data from `statement_store`, ensuring complete transparency and auditability.

---

## 2. Core Architectural Philosophy

Consistent with Ledger AI's architecture, the forecaster follows a **rules-first, explainable logic** hierarchy:

1. **Observed Historical Settlement Lag**: Near-term expected gateway settlements are computed using empirical channel settlement cycles (e.g., Razorpay T+2 lag, Stripe T+3 lag) derived from historical statement data.
2. **Deterministic Pattern Detection**: Recurring cash debits and credits (payroll, retainers, subscription batches) are identified using string similarity and calendar interval matching.
3. **Seasonal Decomposition & WMA Projection**: Baseline daily cash flows are decomposed into trend and weekly seasonal components, projected using a 14-day weighted moving average with confidence bands.
4. **Beginning Balance Integration**: Cumulative cash balance series start from the globally configured Beginning Balance ($B_0$).

---

## 3. Mathematical Specifications

### 3.1 Daily Net Cash Flow & Cumulative Balance
Transactions are aggregated by calendar day $d$:

$$\text{Net Cash Flow}(d) = \sum_{t \in \text{Deposits}(d)} \text{Amount}(t) - \sum_{t \in \text{Payments}(d)} |\text{Amount}(t)|$$

Cumulative liquid cash balance $C(d)$ starts from Beginning Balance $B_0$:

$$C(d) = B_0 + \sum_{k=d_0}^{d} \text{Net Cash Flow}(k)$$

### 3.2 Pending Gateway Settlement Estimation
For open gateway batches, expected settlement date $d_{\text{expected}}$ is computed as:

$$d_{\text{expected}} = d_{\text{batch}} + L_{\text{channel}}$$

Default channel lags $L_{\text{channel}}$:
- **Razorpay**: $T + 2$ business days
- **Stripe / Card Gateways**: $T + 3$ business days
- **UPI Direct**: $T + 0$ / $T + 1$ business days

### 3.3 Seasonal Decomposition & Moving Average Forecasting
Daily net inflows are decomposed into trend $T(d)$ and weekly seasonal component $S(d)$ (7-day period):

$$\text{Trend}(d) = \text{RollingMean}_7(\text{NetInflow}(d))$$

Future projections for day $t > \text{today}$ combine last trend level, seasonal component, recurring pattern overlay, and expected pending settlements:

$$\text{Projected}(t) = T_{\text{last}} + S(t \bmod 7) + \text{PatternOverlay}(t) + \text{PendingSettlement}(t)$$

Confidence bands are calculated using standard deviation of residuals $\sigma$:

$$\text{Upper Band}(t) = \text{Projected}(t) + 1.5 \cdot \sigma \cdot \sqrt{\frac{t}{7}}$$

$$\text{Lower Band}(t) = \text{Projected}(t) - 1.5 \cdot \sigma \cdot \sqrt{\frac{t}{7}}$$

---

## 4. API Endpoints

### 4.1 GET `/api/forecast`
Returns the 30-day historical series, forward forecast projections, recurring patterns, pending settlements, and summary stats.

**Query Parameters**:
- `days` (optional, default: `30`, max: `90`): Forecast horizon in days.

**Response Schema**:
```json
{
  "ok": true,
  "summary": {
    "avg_daily_net": 1250.50,
    "total_inflow": 450000.00,
    "total_outflow": 120000.00,
    "current_balance": 5557602.99,
    "forecast_30d_projected": 6133842.10,
    "detected_patterns": 2,
    "pending_count": 4,
    "forecast_days": 30,
    "confidence_std": 450.25
  },
  "historical": [
    { "date": "2026-08-01", "net_inflow": 12000.0, "cumulative": 1012000.0, "tx_count": 14 }
  ],
  "forecast": [
    { "date": "2026-09-01", "projected": 4500.0, "upper_band": 5200.0, "lower_band": 3800.0, "cumulative": 6133842.10 }
  ],
  "pending_settlements": [
    { "amount": 125000.0, "initiated_date": "2026-08-28", "expected_settlement": "2026-08-30", "status": "PENDING", "currency": "INR" }
  ]
}
```

### 4.2 GET `/api/forecast/day-details`
Provides itemized transaction lookups for any selected chart date.

**Query Parameters**:
- `date` (required): ISO date string (`YYYY-MM-DD`).

**Response Schema**:
```json
{
  "ok": true,
  "date": "2026-08-15",
  "total_settled_cumulative": 4379515.88,
  "total_pending_cumulative": 576239.00,
  "transactions": [
    {
      "source": "Razorpay",
      "description": "Batch Settlement #RZP-992",
      "ref": "PAY-88192",
      "settled_amount": 125000.00,
      "pending_amount": 0.00,
      "status": "SETTLED"
    }
  ]
}
```

---

## 5. UI & Report Integration

1. **Forecast Tab (`#sub-forecast`)**: Displays Chart.js cash flow visualizations with confidence band shading and interactive click handler.
2. **Day Details Modal (`#forecastDayDetailsModalBackdrop`)**: Displays itemized daily transaction lists, settled vs. pending amounts, and cumulative totals when clicking any historical or projected date.
3. **Overview KPI Card**: Renders `30D Projected Ending Cash` KPI card in the main overview dashboard.
4. **PDF & Filtered Audit Reports (`reports/report_builder.py`)**: Includes forward 30-day cash projections in generated PDF audit reports (`GET /report/pdf`).
