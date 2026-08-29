"""
settlement_status.py — Period settlement status evaluator (T3.7).

Calculates whether a primary statement's period is fully settled.
"""

from typing import Dict, Any, Union
import pandas as pd


def evaluate_period_settlement(primary_statement_id: str, results_df: Union[pd.DataFrame, list], exceptions_df: Union[pd.DataFrame, list]) -> Dict[str, Any]:
    """
    Evaluates whether a statement period is completely settled per T3.7.
    A period is settled when ALL primary statement transactions are matched and 0 open exceptions exist.
    """
    if isinstance(results_df, list):
        results_df = pd.DataFrame(results_df)
    if isinstance(exceptions_df, list):
        exceptions_df = pd.DataFrame(exceptions_df)

    if results_df is None or results_df.empty:
        primary_rows = pd.DataFrame()
    else:
        if "primary_statement_id" in results_df.columns:
            primary_rows = results_df[results_df["primary_statement_id"] == primary_statement_id]
        elif "statement_id" in results_df.columns:
            primary_rows = results_df[results_df["statement_id"] == primary_statement_id]
        else:
            primary_rows = pd.DataFrame()

    if exceptions_df is None or exceptions_df.empty:
        open_exceptions = pd.DataFrame()
    else:
        status_col = "resolution_status" if "resolution_status" in exceptions_df.columns else "status"
        if status_col in exceptions_df.columns:
            open_exceptions = exceptions_df[exceptions_df[status_col] == "open"]
        else:
            open_exceptions = pd.DataFrame()

    primary_total = len(primary_rows)
    primary_matched = int((primary_rows["status"].isin(["SETTLED", "settled", "matched"])).sum()) if not primary_rows.empty and "status" in primary_rows.columns else 0
    all_matched = (primary_total > 0) and (primary_matched == primary_total)
    zero_open_exceptions = (len(open_exceptions) == 0)


    return {
        "period_settled": all_matched and zero_open_exceptions,
        "primary_total": primary_total,
        "primary_matched": primary_matched,
        "open_exceptions_count": len(open_exceptions),
    }
