"""
date_utils.py — Business-Day-Aware Date Utilities (T3.6) for Ledger AI v2.

Calculates business days between dates by skipping weekends (Saturday & Sunday)
and optional configurable holiday lists.
"""

from datetime import datetime, timedelta
from typing import Optional, List
import dateutil.parser


def business_days_between(d1: Optional[str], d2: Optional[str], holidays: Optional[List[str]] = None) -> int:
    """
    Calculates number of business days between two date strings (excluding weekends and holidays).
    Friday -> Tuesday = 1 business day (skips Sat & Sun).
    """
    if not d1 or not d2:
        return 999

    try:
        dt1 = dateutil.parser.parse(str(d1)).date()
        dt2 = dateutil.parser.parse(str(d2)).date()
    except Exception:
        return 999

    if dt1 > dt2:
        dt1, dt2 = dt2, dt1

    holiday_dates = set()
    if holidays:
        for h in holidays:
            try:
                holiday_dates.add(dateutil.parser.parse(str(h)).date())
            except Exception:
                pass

    business_days = 0
    cur = dt1 + timedelta(days=1)
    while cur <= dt2:
        # 5 = Saturday, 6 = Sunday
        if cur.weekday() < 5 and cur not in holiday_dates:
            business_days += 1
        cur += timedelta(days=1)

    return business_days
