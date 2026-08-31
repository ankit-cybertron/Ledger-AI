"""
forecasting/ — Forward Cash Forecaster package (Part 24).

Isolated from matcher schema and config. Produces explainable,
rules-first cash flow projections from historical settled data.
"""

from forecasting.engine import build_forecast

__all__ = ["build_forecast"]
