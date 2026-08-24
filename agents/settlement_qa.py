from pathlib import Path

import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"

SETTLEMENTS_PATH = (
    GENERATED_DIR / "razorpay_settlements.csv"
)

BANK_PATH = (
    GENERATED_DIR / "bank_statement.csv"
)

RECONCILIATION_PATH = (
    RESULTS_DIR / "reconciliation_results.csv"
)

EXCEPTION_LEDGER_PATH = (
    RESULTS_DIR / "exception_ledger.csv"
)


# ============================================================
# DATA LOADING
# ============================================================
# Loaded once per process and reused across tool calls. This
# module intentionally has no write path -- the Q&A agent is
# read-only and can never alter reconciliation results.

_settlements = None
_bank = None
_reconciliation = None
_exceptions = None


def _load():
    global _settlements, _bank, _reconciliation, _exceptions

    if _settlements is None:
        _settlements = pd.read_csv(
            SETTLEMENTS_PATH
        ).set_index("settlement_id", drop=False)

    if _bank is None:
        _bank = pd.read_csv(
            BANK_PATH
        ).set_index("bank_transaction_id", drop=False)

    if _reconciliation is None:
        _reconciliation = pd.read_csv(
            RECONCILIATION_PATH
        )

    if _exceptions is None:
        if EXCEPTION_LEDGER_PATH.exists():
            _exceptions = pd.read_csv(
                EXCEPTION_LEDGER_PATH
            )
        else:
            _exceptions = pd.DataFrame(
                columns=[
                    "exception_id", "created_at",
                    "settlement_id", "bank_transaction_id",
                    "stage", "decision", "confidence",
                    "exception_type", "priority", "reason",
                    "resolution_status",
                ]
            )


def reload_data():
    """
    Forces a fresh read of every source file. Call this if
    the reconciliation pipeline has been re-run since this
    process started.
    """
    global _settlements, _bank, _reconciliation, _exceptions
    _settlements = None
    _bank = None
    _reconciliation = None
    _exceptions = None
    _load()


def _clean(value):
    """
    Recursively replaces pandas/numpy NaN with None so every
    tool result is valid, standard JSON -- pandas' to_dict()
    otherwise leaves float('nan') in place, which serializes
    to the non-standard 'NaN' token instead of 'null'.
    """
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


# ============================================================
# SETTLEMENT-LEVEL STATUS
# ============================================================
# A settlement can have multiple reconciliation_results rows
# (a split settlement maps to several bank transactions), so
# the settlement-level outcome is derived the same way
# reconciler/generate_report.py derives it: "matched" wins if
# any row matched, else "manual_review" if any row needs
# review, else "unmatched".

def _settlement_level_status(rows):
    statuses = set(rows["status"])

    if "matched" in statuses:
        return "matched"
    if "manual_review" in statuses:
        return "manual_review"
    return "unmatched"


# ============================================================
# TOOL 1 -- GET SETTLEMENT
# ============================================================

def get_settlement(settlement_id):
    """
    Returns everything grounded and known about one
    settlement: its source record, every reconciliation row
    associated with it, the linked bank transaction(s) if
    any, and its exception-ledger entry if it currently has
    one open.

    Returns {"found": False} if the settlement_id does not
    exist in the dataset -- this is the tool's own explicit
    "I don't have that" signal, so the agent never has to
    guess.
    """

    _load()

    settlement_id = str(settlement_id).strip()

    if settlement_id not in _settlements.index:
        return {
            "found": False,
            "settlement_id": settlement_id,
            "message": (
                "No settlement with this ID exists in "
                "the dataset."
            ),
        }

    settlement_row = _clean(
        _settlements.loc[
            settlement_id
        ].to_dict()
    )
    reconciliation_rows = _reconciliation[
        _reconciliation["settlement_id"] == settlement_id
    ]

    relationships = []

    for _, row in reconciliation_rows.iterrows():

        bank_transaction_id = row["bank_transaction_id"]
        bank_record = None

        if (
            pd.notna(bank_transaction_id)
            and str(bank_transaction_id).strip()
            and str(bank_transaction_id)
            in _bank.index
        ):
            bank_record = _clean(
                _bank.loc[
                    str(bank_transaction_id)
                ].to_dict()
            )

        relationships.append(
            {
                "bank_transaction_id": (
                    str(bank_transaction_id)
                    if pd.notna(bank_transaction_id)
                    and str(bank_transaction_id).strip()
                    else None
                ),
                "stage": row["stage"],
                "decision": row["decision"],
                "confidence": float(row["confidence"]),
                "reason": row["reason"],
                "status": row["status"],
                "bank_record": bank_record,
            }
        )

    overall_status = (
        _settlement_level_status(reconciliation_rows)
        if not reconciliation_rows.empty
        else "unknown"
    )

    exception_rows = _exceptions[
        (_exceptions["settlement_id"] == settlement_id)
        & (
            _exceptions["resolution_status"]
            == "open"
        )
    ]

    open_exception = None

    if not exception_rows.empty:
        open_exception = _clean(
            exception_rows.iloc[0].to_dict()
        )

    return {
        "found": True,
        "settlement": settlement_row,
        "overall_status": overall_status,
        "relationships": relationships,
        "open_exception": open_exception,
    }


# ============================================================
# TOOL 2 -- SEARCH SETTLEMENTS BY AMOUNT
# ============================================================

def search_settlements_by_amount(amount, tolerance=50.0):
    """
    Finds settlements whose amount falls within +/- tolerance
    of the given value. Useful for "where is my ~95,000
    settlement" style questions where the user doesn't have
    the exact ID.
    """

    _load()

    amount = float(amount)
    tolerance = float(tolerance)

    matches = _settlements[
        (_settlements["amount"] >= amount - tolerance)
        & (_settlements["amount"] <= amount + tolerance)
    ]

    if matches.empty:
        return {
            "found": False,
            "query_amount": amount,
            "tolerance": tolerance,
            "message": (
                "No settlements found within this amount "
                "range."
            ),
        }

    results = []

    for settlement_id in matches["settlement_id"]:
        summary = get_settlement(settlement_id)
        results.append(
            {
                "settlement_id": settlement_id,
                "amount": float(
                    matches.loc[
                        matches["settlement_id"]
                        == settlement_id,
                        "amount",
                    ].iloc[0]
                ),
                "overall_status": summary.get(
                    "overall_status"
                ),
            }
        )

    return {
        "found": True,
        "query_amount": amount,
        "tolerance": tolerance,
        "matches": results,
    }


# ============================================================
# TOOL 3 -- LIST EXCEPTIONS
# ============================================================

def list_exceptions(priority=None):
    """
    Returns open exception-ledger entries, optionally
    filtered by priority ('high' / 'medium' / 'low').
    """

    _load()

    exceptions = _exceptions.copy()

    if priority:
        exceptions = exceptions[
            exceptions["priority"]
            == str(priority).lower()
        ]

    if exceptions.empty:
        return {
            "count": 0,
            "priority_filter": priority,
            "exceptions": [],
        }

    return {
        "count": len(exceptions),
        "priority_filter": priority,
        "exceptions": _clean(
            exceptions.to_dict(orient="records")
        ),
    }


# ============================================================
# TOOL 4 -- RECONCILIATION SUMMARY
# ============================================================

def get_reconciliation_summary():
    """
    Settlement-level summary across the whole dataset --
    counts by status and by resolving stage. Grounds
    aggregate questions like "how many settlements are
    unresolved" without the agent having to eyeball a table.
    """

    _load()

    settlement_status = (
        _reconciliation.groupby("settlement_id")[
            "status"
        ]
        .agg(
            lambda statuses: (
                "matched"
                if "matched" in set(statuses)
                else (
                    "manual_review"
                    if "manual_review" in set(statuses)
                    else "unmatched"
                )
            )
        )
    )

    status_counts = (
        settlement_status.value_counts().to_dict()
    )

    total = len(settlement_status)

    matched = status_counts.get("matched", 0)

    match_rate = (
        round(matched / total, 4) if total else 0.0
    )

    stage_counts = (
        _reconciliation["stage"]
        .value_counts()
        .to_dict()
    )

    return {
        "total_settlements": total,
        "matched": matched,
        "manual_review": status_counts.get(
            "manual_review", 0
        ),
        "unmatched": status_counts.get("unmatched", 0),
        "match_rate": match_rate,
        "relationship_records_by_stage": stage_counts,
        "open_exceptions": len(_exceptions),
    }


# ============================================================
# TOOL 5 -- GET BANK TRANSACTION
# ============================================================

def get_bank_transaction(bank_transaction_id):
    """
    Returns a bank transaction record and, if it's linked to
    a settlement in reconciliation_results.csv, that link too.
    Returns found=False if the ID doesn't exist -- covers
    questions about a specific bank credit rather than a
    settlement.
    """

    _load()

    bank_transaction_id = str(bank_transaction_id).strip()

    if bank_transaction_id not in _bank.index:
        return {
            "found": False,
            "bank_transaction_id": bank_transaction_id,
            "message": (
                "No bank transaction with this ID exists "
                "in the dataset."
            ),
        }

    bank_record = _clean(
        _bank.loc[
            bank_transaction_id
        ].to_dict()
    )

    linked_rows = _reconciliation[
        _reconciliation["bank_transaction_id"]
        == bank_transaction_id
    ]

    linked = (
        _clean(
            linked_rows.to_dict(
                orient="records"
            )
        )
        if not linked_rows.empty
        else []
    )

    return {
        "found": True,
        "bank_transaction": bank_record,
        "linked_reconciliation_rows": linked,
    }