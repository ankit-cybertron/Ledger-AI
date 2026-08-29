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

INTERNAL_ORDERS_PATH = (
    GENERATED_DIR / "internal_orders.csv"
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
_internal_orders = None
_reconciliation = None
_exceptions = None


def _load():
    global _settlements, _bank, _internal_orders, _reconciliation, _exceptions

    if _settlements is None:
        _settlements = pd.read_csv(
            SETTLEMENTS_PATH
        ).set_index("settlement_id", drop=False)

    if _bank is None:
        _bank = pd.read_csv(
            BANK_PATH
        ).set_index("bank_transaction_id", drop=False)

    if _internal_orders is None:
        if INTERNAL_ORDERS_PATH.exists():
            _internal_orders = pd.read_csv(
                INTERNAL_ORDERS_PATH
            ).set_index("order_id", drop=False)
        else:
            _internal_orders = pd.DataFrame()

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
    global _settlements, _bank, _internal_orders, _reconciliation, _exceptions
    _settlements = None
    _bank = None
    _internal_orders = None
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


# ============================================================
# TOOL 6 -- GET INTERNAL ORDER
# ============================================================

def get_order(order_id):
    """
    Returns details for an internal order by order_id or Bill No.
    """
    _load()
    order_id_str = str(order_id).strip().lower()
    if _internal_orders is not None and not _internal_orders.empty:
        for idx, row in _internal_orders.iterrows():
            if (
                str(row.get("order_id", "")).lower() == order_id_str
                or str(row.get("Bill No", "")).lower() == order_id_str
                or str(idx).lower() == order_id_str
            ):
                return {"found": True, "order": _clean(row.to_dict())}
    return {
        "found": False,
        "order_id": order_id,
        "message": f"No internal order with reference '{order_id}' exists in the dataset."
    }


# ============================================================
# TOOL 7 -- SEARCH BY KEYWORD OR IDENTIFIER (UTR, UPI ID, ETC)
# ============================================================

def search_by_keyword_or_identifier(query):
    """
    Search for a UTR number, UPI ID, settlement ID, bank transaction ID,
    order ID, narration string, or reference code across all reconciliation data.
    Returns full details and key statistics.
    """
    import re
    _load()
    query_str = str(query).strip().lower()
    if not query_str:
        return {"found": False, "query": query, "message": "Search query was empty."}

    stop_words = {"tell", "me", "about", "the", "from", "in", "book", "for", "a", "an", "is", "was", "show", "get", "find", "transaction", "transactions", "detail", "details"}
    tokens = [t for t in re.findall(r'\w+', query_str) if t not in stop_words and len(t) > 2]

    matched_settlement_ids = set()
    matched_bank_ids = set()
    matched_order_ids = set()

    # Search Settlements
    for idx, row in _settlements.iterrows():
        row_str = " ".join([str(v).lower() for k, v in row.items() if pd.notna(v)]) + " " + str(idx).lower()
        if query_str in row_str or (tokens and all(t in row_str for t in tokens)):
            matched_settlement_ids.add(str(row["settlement_id"]).strip())
        elif "refund" in query_str and ("refund" in row_str or "return" in row_str):
            matched_settlement_ids.add(str(row["settlement_id"]).strip())

    # Search Bank Statements
    for idx, row in _bank.iterrows():
        row_str = " ".join([str(v).lower() for k, v in row.items() if pd.notna(v)]) + " " + str(idx).lower()
        if query_str in row_str or (tokens and all(t in row_str for t in tokens)):
            matched_bank_ids.add(str(row["bank_transaction_id"]).strip())
            if pd.notna(row.get("settlement_id")):
                matched_settlement_ids.add(str(row["settlement_id"]).strip())

    # Search Internal Orders
    if _internal_orders is not None and not _internal_orders.empty:
        for idx, row in _internal_orders.iterrows():
            row_str = " ".join([str(v).lower() for k, v in row.items() if pd.notna(v)]) + " " + str(idx).lower()
            if query_str in row_str or (tokens and all(t in row_str for t in tokens)):
                matched_order_ids.add(str(row["order_id"]).strip())
            elif "refund" in query_str and ("refunded" in row_str or "return" in row_str):
                matched_order_ids.add(str(row["order_id"]).strip())

    # Search Reconciliation Results
    recon_matches = _reconciliation[
        _reconciliation["settlement_id"].astype(str).str.lower().str.contains(query_str, na=False)
        | _reconciliation["bank_transaction_id"].astype(str).str.lower().str.contains(query_str, na=False)
        | _reconciliation["reason"].astype(str).str.lower().str.contains(query_str, na=False)
    ]

    for _, r in recon_matches.iterrows():
        if pd.notna(r.get("settlement_id")):
            matched_settlement_ids.add(str(r["settlement_id"]).strip())
        if pd.notna(r.get("bank_transaction_id")):
            matched_bank_ids.add(str(r["bank_transaction_id"]).strip())

    if not matched_settlement_ids and not matched_bank_ids and not matched_order_ids:
        return {
            "found": False,
            "query": query,
            "message": f"No records found matching identifier or keyword '{query}'."
        }

    results = []
    total_amount_settled = 0.0
    total_bank_credited = 0.0
    total_order_amount = 0.0
    matched_count = 0
    exception_count = 0
    stages_found = set()

    for sid in matched_settlement_ids:
        s_data = get_settlement(sid)
        if s_data.get("found"):
            results.append(s_data)
            s_rec = s_data.get("settlement", {})
            total_amount_settled += float(s_rec.get("amount") or 0.0)
            if s_data.get("overall_status") == "matched":
                matched_count += 1
            if s_data.get("open_exception"):
                exception_count += 1
            for rel in s_data.get("relationships", []):
                if rel.get("stage"):
                    stages_found.add(rel["stage"])

    bank_records = []
    for bid in matched_bank_ids:
        b_data = get_bank_transaction(bid)
        if b_data.get("found"):
            bank_records.append(b_data)
            b_rec = b_data.get("bank_transaction", {})
            total_bank_credited += float(b_rec.get("amount") or b_rec.get("Credit (INR)") or 0.0)

    order_records = []
    for oid in matched_order_ids:
        o_data = get_order(oid)
        if o_data.get("found"):
            order_records.append(o_data)
            o_rec = o_data.get("order", {})
            total_order_amount += float(o_rec.get("amount") or 0.0)

    total_found = len(matched_settlement_ids) + len(bank_records) + len(matched_order_ids)
    match_rate = round((matched_count / len(matched_settlement_ids) * 100), 2) if matched_settlement_ids else 0.0
    amount_diff = round(total_amount_settled - total_bank_credited, 2)

    stats = {
        "total_records_found": total_found,
        "settlements_count": len(matched_settlement_ids),
        "bank_transactions_count": len(bank_records),
        "internal_orders_count": len(matched_order_ids),
        "reconciliation_match_rate": f"{match_rate}%",
        "total_settlement_amount": total_amount_settled,
        "total_bank_credit_amount": total_bank_credited,
        "total_internal_order_amount": total_order_amount,
        "net_amount_variance": amount_diff,
        "open_exceptions_count": exception_count,
        "stages_involved": list(stages_found)
    }

    return {
        "found": True,
        "query": query,
        "stats": stats,
        "settlements": results,
        "bank_transactions": bank_records,
        "internal_orders": order_records
    }