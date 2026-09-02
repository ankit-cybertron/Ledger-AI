"""
forecasting/engine.py — Core Forward Cash Forecaster Engine (T24.1 / T24.2).

Fully isolated from matcher schema and config.  Uses only pandas + stdlib.

Approach (rules-first, no ML):
  1. Aggregate historical SETTLED daily net cash flow from statement data.
  2. Detect recurring patterns (weekly payroll, monthly vendor payments)
     by analysing description frequency clusters and cadence.
  3. Project pending gateway settlements using observed settlement lag.
  4. Simple moving-average + seasonal decomposition for headline forecast.
  5. Confidence bands computed from historical variance.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# 1. DATA PREPARATION
# ---------------------------------------------------------------------------

def _parse_date(val: Any) -> Optional[datetime]:
    """Best-effort date parser.  Returns None on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("nat", "none", "nan", ""):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S",
                "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    try:
        import dateutil.parser
        return dateutil.parser.parse(s, dayfirst=True)
    except Exception:
        return None


def _parse_amount(val: Any) -> float:
    """Robust currency-string → float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = re.sub(r"[₹$€£,\s]", "", str(val))
    try:
        return float(s)
    except Exception:
        return 0.0


def _detect_currency(item: Dict[str, Any], text_sample: str = "") -> str:
    """Detect currency code from item dict or text sample."""
    if not isinstance(item, dict):
        item = {}
    for k in ("currency", "Currency", "currency_code", "curr"):
        val = item.get(k)
        if val:
            return str(val).upper().strip()
    combo = (text_sample + " " + str(item.get("description") or "") + " " + str(item.get("sample_desc") or "") + " " + str(item.get("source") or "")).upper()
    if "$" in combo or "USD" in combo or "GLOBALPAY" in combo or "STRIPE" in combo or "PAYPAL" in combo:
        return "USD"
    if "€" in combo or "EUR" in combo:
        return "EUR"
    if "£" in combo or "GBP" in combo:
        return "GBP"
    if "CAD" in combo:
        return "CAD"
    if "AUD" in combo:
        return "AUD"
    return "INR"


def _build_daily_series(
    transactions: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    Convert raw transaction dicts → daily aggregated DataFrame.

    Returns DataFrame with columns: [date, net_inflow, tx_count]
    sorted by date ascending.
    """
    rows: List[Dict[str, Any]] = []
    for tx in transactions:
        dt = _parse_date(tx.get("transaction_date") or tx.get("date"))
        amt = _parse_amount(tx.get("net_amount") or tx.get("amount") or 0)
        if dt is None:
            continue
        rows.append({"date": dt.date(), "amount": amt})

    if not rows:
        return pd.DataFrame(columns=["date", "net_inflow", "tx_count"])

    df = pd.DataFrame(rows)
    daily = (
        df.groupby("date")
        .agg(net_inflow=("amount", "sum"), tx_count=("amount", "count"))
        .reset_index()
        .sort_values("date")
    )
    # Fill missing dates with zero
    if len(daily) >= 2:
        full_range = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
        daily = daily.set_index("date").reindex(full_range, fill_value=0).rename_axis("date").reset_index()

    return daily


# ---------------------------------------------------------------------------
# 2. RECURRING PATTERN DETECTION
# ---------------------------------------------------------------------------

def _normalise_desc(desc: str) -> str:
    """Normalise description for grouping (lowercase, strip digits/IDs)."""
    s = str(desc).lower().strip()
    # Remove long hex/numeric IDs
    s = re.sub(r"\b[a-f0-9]{8,}\b", "", s)
    s = re.sub(r"\b\d{6,}\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detect_recurring_patterns(
    transactions: List[Dict[str, Any]],
    min_occurrences: int = 3,
) -> List[Dict[str, Any]]:
    """
    Detect recurring payment patterns from description similarity.

    Reuses the same token-overlap logic as matcher/similarity_engine.py
    (Jaccard set similarity on whitespace-tokenised descriptions) rather
    than building a second clustering algorithm.

    Returns list of detected patterns:
      { label, cadence_days, avg_amount, occurrences, next_expected, confidence }
    """
    desc_groups: Dict[str, List[Dict]] = defaultdict(list)

    for tx in transactions:
        desc = tx.get("description") or tx.get("bank_description") or ""
        dt = _parse_date(tx.get("transaction_date") or tx.get("date"))
        amt = _parse_amount(tx.get("net_amount") or tx.get("amount") or 0)
        if dt is None or not desc.strip():
            continue
        key = _normalise_desc(desc)
        if len(key) < 3:
            continue
        desc_groups[key].append({"date": dt, "amount": amt, "desc": desc})

    # Merge similar groups using Jaccard token overlap (reusing similarity_engine philosophy)
    merged: Dict[str, List[Dict]] = {}
    keys = list(desc_groups.keys())
    assigned = set()

    for i, k1 in enumerate(keys):
        if k1 in assigned:
            continue
        cluster = list(desc_groups[k1])
        assigned.add(k1)
        t1 = set(k1.split())
        for j in range(i + 1, len(keys)):
            k2 = keys[j]
            if k2 in assigned:
                continue
            t2 = set(k2.split())
            if not t1 or not t2:
                continue
            jaccard = len(t1 & t2) / len(t1 | t2)
            if jaccard >= 0.6:
                cluster.extend(desc_groups[k2])
                assigned.add(k2)
        if len(cluster) >= min_occurrences:
            merged[k1] = cluster

    patterns: List[Dict[str, Any]] = []
    for label, entries in merged.items():
        entries.sort(key=lambda e: e["date"])
        dates = [e["date"] for e in entries]
        amounts = [e["amount"] for e in entries]
        avg_amt = sum(amounts) / len(amounts)

        # Compute cadence (median inter-occurrence gap)
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        gaps = [g for g in gaps if 1 <= g <= 180]
        if not gaps:
            continue
        gaps.sort()
        median_gap = gaps[len(gaps) // 2]

        # Snap to nearest business cadence
        cadence = _snap_cadence(median_gap)
        if cadence is None:
            continue

        last_date = max(dates)
        next_expected = last_date + timedelta(days=cadence)

        # Confidence: how consistent is the cadence?
        deviations = [abs(g - cadence) for g in gaps]
        avg_dev = sum(deviations) / len(deviations) if deviations else cadence
        confidence = max(0.0, min(1.0, 1.0 - (avg_dev / cadence)))

        # Compute history occurrences list
        history = [
            {
                "date": e["date"].strftime("%Y-%m-%d"),
                "amount": round(float(e["amount"]), 2),
                "description": str(e["desc"])[:140]
            }
            for e in entries
        ]

        # Compute projected future occurrences (next 5 occurrences)
        future_projections = []
        proj_date = last_date
        for step in range(1, 6):
            proj_date += timedelta(days=cadence)
            future_projections.append({
                "date": proj_date.strftime("%Y-%m-%d"),
                "estimated_amount": round(avg_amt, 2),
                "status": "Expected" if step == 1 else "Projected",
                "confidence": max(10, min(99, round(confidence * 100 - (step - 1) * 3)))
            })

        patterns.append({
            "label": label[:80],
            "sample_desc": entries[0]["desc"][:120],
            "cadence_days": cadence,
            "cadence_label": _cadence_label(cadence),
            "avg_amount": round(avg_amt, 2),
            "min_amount": round(min(amounts), 2),
            "max_amount": round(max(amounts), 2),
            "total_volume": round(sum(amounts), 2),
            "occurrences": len(entries),
            "last_date": last_date.strftime("%Y-%m-%d"),
            "next_expected": next_expected.strftime("%Y-%m-%d"),
            "confidence": round(confidence, 3),
            "currency": _detect_currency(entries[0], label + " " + entries[0]["desc"]),
            "history": history,
            "future_projections": future_projections,
        })

    patterns.sort(key=lambda p: abs(p["avg_amount"]), reverse=True)
    return patterns


def _snap_cadence(median_days: int) -> Optional[int]:
    """Snap a median gap to known business cadences, or return None."""
    if median_days <= 0:
        return None
    snaps = [
        (1, "daily"),
        (7, "weekly"),
        (14, "biweekly"),
        (30, "monthly"),
        (90, "quarterly"),
    ]
    for target, _ in snaps:
        if abs(median_days - target) <= max(2, target * 0.25):
            return target
    return median_days if 2 <= median_days <= 120 else None


def _cadence_label(days: int) -> str:
    labels = {1: "Daily", 7: "Weekly", 14: "Bi-Weekly", 30: "Monthly", 90: "Quarterly"}
    return labels.get(days, f"Every {days} days")


# ---------------------------------------------------------------------------
# 3. PENDING SETTLEMENT PROJECTION
# ---------------------------------------------------------------------------

def estimate_pending_settlements(
    transactions: List[Dict[str, Any]],
    today: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Identify open gateway batches that haven't yet settled based on
    observed historical settlement lag.

    Transactions with status containing 'pending', 'initiated', 'processing'
    (or not 'settled'/'success') dated within observed lag window are flagged
    as "expected any day now."
    """
    if today is None:
        today = datetime.utcnow()

    settled, unsettled = [], []
    gateway_settled = []
    bank_credits = []

    for tx in transactions:
        status = str(tx.get("status") or "").upper()
        dt = _parse_date(tx.get("transaction_date") or tx.get("date"))
        amt = _parse_amount(tx.get("net_amount") or tx.get("amount") or 0)
        desc = str(tx.get("description") or "").upper()
        if dt is None:
            continue
        if status in ("SETTLED", "MATCHED", "AUTO", "SUCCESS", "COMPLETED", "PAID", "CREDIT"):
            settled.append({"date": dt, "amount": amt})
            # Check if it looks like a gateway transaction
            is_gateway = any(k in desc for k in ("RAZORPAY", "STRIPE", "PAYPAL", "GATEWAY", "PAYU", "BATCH", "SETTLEMENT"))
            if is_gateway:
                gateway_settled.append({"date": dt, "amount": amt, "desc": desc})
            else:
                if amt > 0:
                    bank_credits.append({"date": dt, "amount": amt, "desc": desc})
        elif status not in ("REFUND", "REVERSED", "CANCELLED", "VOID"):
            unsettled.append({"date": dt, "amount": amt, "status": status,
                              "desc": tx.get("description", "")[:80]})

    # Compute typical settlement lag from settled transactions (T+N)
    lags = []
    for gt in gateway_settled:
        best_bank_tx = None
        min_lag = 999
        for bt in bank_credits:
            if bt["date"] >= gt["date"]:
                lag = (bt["date"] - gt["date"]).days
                if lag <= 14:  # typical lag is under 2 weeks
                    # Check amount similarity (e.g., within 5%)
                    diff_pct = abs(bt["amount"] - gt["amount"]) / max(1.0, abs(gt["amount"]))
                    if diff_pct < 0.05:
                        if lag < min_lag:
                            min_lag = lag
                            best_bank_tx = bt
        if best_bank_tx is not None:
            lags.append(min_lag)

    if lags:
        typical_lag = max(1, int(sum(lags) / len(lags)))
    else:
        # Fallback to T+2 or explicit field check
        typical_lag = 2

    pending = []
    for tx in unsettled:
        age_days = (today - tx["date"]).days
        if 0 <= age_days <= typical_lag + 3:
            expected_date = tx["date"] + timedelta(days=typical_lag)
            pending.append({
                "amount": tx["amount"],
                "initiated_date": tx["date"].strftime("%Y-%m-%d"),
                "expected_settlement": expected_date.strftime("%Y-%m-%d"),
                "age_days": age_days,
                "status": tx["status"],
                "description": tx["desc"],
                "currency": _detect_currency(tx, tx["desc"]),
            })

    return pending


# ---------------------------------------------------------------------------
# 4. MOVING-AVERAGE + SEASONAL FORECAST
# ---------------------------------------------------------------------------

def _seasonal_decompose(
    series: pd.Series,
    period: int = 7,
) -> Tuple[pd.Series, pd.Series]:
    """
    Simple additive seasonal decomposition.
    Returns (trend, seasonal_component).
    """
    n = len(series)
    if n < period * 2:
        trend = series.rolling(window=min(n, 3), min_periods=1, center=True).mean()
        seasonal = pd.Series(0.0, index=series.index)
        return trend, seasonal

    trend = series.rolling(window=period, min_periods=1, center=True).mean()
    detrended = series - trend

    # Average seasonal effect per day-of-week (or position in cycle)
    seasonal_avg = {}
    for i, val in enumerate(detrended):
        pos = i % period
        if pos not in seasonal_avg:
            seasonal_avg[pos] = []
        if not math.isnan(val):
            seasonal_avg[pos].append(val)

    seasonal_vals = []
    for i in range(n):
        pos = i % period
        vals = seasonal_avg.get(pos, [0])
        seasonal_vals.append(sum(vals) / len(vals) if vals else 0.0)

    seasonal = pd.Series(seasonal_vals, index=series.index)
    return trend, seasonal


def build_forecast(
    transactions: List[Dict[str, Any]],
    forecast_days: int = 30,
    beginning_balance: float = 0.0,
    today: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Main entry point — builds a complete cash flow forecast.

    Returns:
      {
        historical: [{date, net_inflow, cumulative}],
        forecast:   [{date, projected, upper_band, lower_band, cumulative}],
        recurring_patterns: [...],
        pending_settlements: [...],
        summary: { ... }
      }
    """
    if today is None:
        today = datetime.utcnow()
    today_date = today.date() if isinstance(today, datetime) else today

    # --- Historical daily series ---
    daily = _build_daily_series(transactions)
    if daily.empty:
        return _empty_result()

    daily["date"] = pd.to_datetime(daily["date"]).dt.date

    # Cumulative balance starting from beginning_balance
    daily["cumulative"] = beginning_balance + daily["net_inflow"].cumsum()

    # --- Recurring pattern detection ---
    patterns = detect_recurring_patterns(transactions)

    # --- Pending settlement projection ---
    pending = estimate_pending_settlements(transactions, today)

    # --- Seasonal decomposition on net_inflow ---
    series = daily["net_inflow"].astype(float)
    period = 7  # weekly seasonality
    trend, seasonal = _seasonal_decompose(series, period)

    # --- Historical variance for confidence band ---
    residuals = series - trend - seasonal
    std_dev = residuals.std() if len(residuals) > 1 else abs(series.mean()) * 0.2
    if math.isnan(std_dev) or std_dev == 0:
        std_dev = max(abs(series.mean()) * 0.15, 1.0)

    # --- Project forward ---
    last_trend = trend.iloc[-1] if not trend.empty else 0
    n_hist = len(series)
    last_cumulative = float(daily["cumulative"].iloc[-1])

    # Build recurring pattern overlay
    pattern_overlay: Dict[str, float] = {}
    for pat in patterns:
        if pat["confidence"] >= 0.4:
            cad = pat["cadence_days"]
            amt = pat["avg_amount"]
            try:
                next_dt = datetime.strptime(pat["next_expected"], "%Y-%m-%d").date()
            except Exception:
                continue
            # Project recurring hits into forecast window
            dt = next_dt
            for _ in range(forecast_days):
                key = dt.strftime("%Y-%m-%d")
                pattern_overlay[key] = pattern_overlay.get(key, 0) + amt
                dt += timedelta(days=cad)
                if dt > today_date + timedelta(days=forecast_days):
                    break

    forecast_rows = []
    cumulative = last_cumulative
    for d in range(1, forecast_days + 1):
        fdate = today_date + timedelta(days=d)
        pos = (n_hist + d - 1) % period
        seasonal_component = seasonal.iloc[pos % len(seasonal)] if len(seasonal) > 0 else 0

        # Base projection = trend + seasonal
        base = last_trend + seasonal_component

        # Add recurring pattern overlay if present
        fdate_key = fdate.strftime("%Y-%m-%d")
        if fdate_key in pattern_overlay:
            base += pattern_overlay[fdate_key] * 0.5  # Blend (don't double-count)

        # Add pending settlement bump
        for ps in pending:
            if ps["expected_settlement"] == fdate_key:
                base += ps["amount"]

        cumulative += base
        band_width = std_dev * 1.5 * math.sqrt(d / 7)  # Widen with time

        forecast_rows.append({
            "date": fdate_key,
            "projected": round(base, 2),
            "upper_band": round(base + band_width, 2),
            "lower_band": round(base - band_width, 2),
            "cumulative": round(cumulative, 2),
        })

    # --- Format historical for chart ---
    historical = []
    for _, row in daily.iterrows():
        historical.append({
            "date": str(row["date"]),
            "net_inflow": round(float(row["net_inflow"]), 2),
            "cumulative": round(float(row["cumulative"]), 2),
            "tx_count": int(row.get("tx_count", 0)),
        })

    # --- Summary stats ---
    avg_daily = float(series.mean())
    total_inflow = float(series[series > 0].sum())
    total_outflow = float(series[series < 0].sum())

    return {
        "historical": historical,
        "forecast": forecast_rows,
        "recurring_patterns": patterns,
        "pending_settlements": pending,
        "summary": {
            "avg_daily_net": round(avg_daily, 2),
            "total_inflow": round(total_inflow, 2),
            "total_outflow": round(total_outflow, 2),
            "current_balance": round(last_cumulative, 2),
            "forecast_30d_projected": round(cumulative, 2) if forecast_rows else 0,
            "detected_patterns": len(patterns),
            "pending_count": len(pending),
            "forecast_days": forecast_days,
            "confidence_std": round(std_dev, 2),
        },
    }


def _empty_result() -> Dict[str, Any]:
    return {
        "historical": [],
        "forecast": [],
        "recurring_patterns": [],
        "pending_settlements": [],
        "summary": {
            "avg_daily_net": 0,
            "total_inflow": 0,
            "total_outflow": 0,
            "current_balance": 0,
            "forecast_30d_projected": 0,
            "detected_patterns": 0,
            "pending_count": 0,
            "forecast_days": 30,
            "confidence_std": 0,
        },
    }
