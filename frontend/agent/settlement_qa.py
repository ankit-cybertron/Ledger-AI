"""
settlement_qa.py — read-only data access layer for the Settlement Q&A agent.

NOTE: This file was NOT provided alongside the agent orchestrator
(ledger_agent.py). The functions below are placeholders so the app can
run end-to-end during frontend development — each one currently returns
`found: False` / empty results instead of touching a real database.

Replace every function body here with the real lookup against your
reconciliation store (the same one the matching pipeline writes to).
Do not change the function names or return shapes — ledger_agent.py
and its system prompt already assume this exact contract:

    get_settlement(settlement_id) -> dict
    search_settlements_by_amount(amount, tolerance) -> list[dict]
    list_exceptions(priority=None) -> list[dict]
    get_reconciliation_summary() -> dict
    get_bank_transaction(bank_transaction_id) -> dict

Every result the agent is allowed to state as fact comes from these
functions — so once they're wired to real data, the agent's answers
are automatically grounded in it. No changes needed in ledger_agent.py.
"""


def get_settlement(settlement_id):
    """Return full reconciliation info for one settlement.

    TODO: query your settlement/reconciliation store, e.g.:
        record = db.settlements.find_one({"settlement_id": settlement_id})
        if not record:
            return {"found": False, "settlement_id": settlement_id}
        return {"found": True, **record}
    """
    return {
        "found": False,
        "settlement_id": settlement_id,
        "message": "settlement_qa.get_settlement is not wired to real data yet.",
    }


def search_settlements_by_amount(amount, tolerance=50.0):
    """Return settlements whose amount is within `tolerance` of `amount`.

    TODO: query your store, e.g.:
        return db.settlements.find_amount_range(amount - tolerance, amount + tolerance)
    """
    return {
        "found": False,
        "query": {"amount": amount, "tolerance": tolerance},
        "results": [],
        "message": "settlement_qa.search_settlements_by_amount is not wired to real data yet.",
    }


def list_exceptions(priority=None):
    """Return currently open reconciliation exceptions, optionally filtered.

    TODO: query your exception ledger, e.g.:
        query = {"status": "open"}
        if priority:
            query["priority"] = priority
        return db.exceptions.find(query)
    """
    return {
        "found": False,
        "priority_filter": priority,
        "results": [],
        "message": "settlement_qa.list_exceptions is not wired to real data yet.",
    }


def get_reconciliation_summary():
    """Return aggregate reconciliation statistics.

    TODO: compute/query real aggregates, e.g.:
        return {
            "found": True,
            "total_settlements": ...,
            "matched": ...,
            "manual_review": ...,
            "unmatched": ...,
            "match_rate": ...,
            "stage_counts": {...},
            "open_exceptions": ...,
        }
    """
    return {
        "found": False,
        "message": "settlement_qa.get_reconciliation_summary is not wired to real data yet.",
    }


def get_bank_transaction(bank_transaction_id):
    """Return one bank transaction and any linked reconciliation relationships.

    TODO: query your store, e.g.:
        record = db.bank_transactions.find_one({"bank_transaction_id": bank_transaction_id})
        if not record:
            return {"found": False, "bank_transaction_id": bank_transaction_id}
        return {"found": True, **record}
    """
    return {
        "found": False,
        "bank_transaction_id": bank_transaction_id,
        "message": "settlement_qa.get_bank_transaction is not wired to real data yet.",
    }
