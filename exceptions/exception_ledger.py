from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIR = ROOT / "data" / "results"

RECONCILIATION_PATH = (
    RESULTS_DIR / "reconciliation_results.csv"
)

EXCEPTION_OUTPUT_PATH = (
    RESULTS_DIR / "exception_ledger.csv"
)


# ============================================================
# EXCEPTION CLASSIFICATION
# ============================================================

def classify_exception(row):
    stage = str(row["stage"])
    decision = str(row["decision"])
    reason = str(row["reason"]).lower()

    if decision == "review":
        if stage == "llm":
            return "llm_review"

        if "no llm result" in reason:
            return "llm_unavailable"

        if stage == "reconciler":
            return "unresolved"

        return "manual_review"

    if decision == "non_match":
        return "non_match"

    return "unknown"


def determine_priority(exception_type, confidence):
    confidence = float(confidence)

    if exception_type in {
        "llm_unavailable",
        "unresolved",
    }:
        return "high"

    if confidence < 0.70:
        return "high"

    if confidence < 0.85:
        return "medium"

    return "low"


# ============================================================
# BUILD EXCEPTION LEDGER
# ============================================================

def build_exception_ledger(reconciliation):

    exceptions = reconciliation[
        reconciliation["status"]
        == "manual_review"
    ].copy()

    if exceptions.empty:
        return pd.DataFrame(
            columns=[
                "exception_id",
                "created_at",
                "settlement_id",
                "bank_transaction_id",
                "description",
                "amount",
                "stage",
                "decision",
                "confidence",
                "exception_type",
                "priority",
                "reason",
                "resolution_status",
            ]
        )

    # Load source records to populate real amount, description, date
    sources = {}
    gen_dir = ROOT / "data" / "generated"
    for fname in ["razorpay_settlements.csv", "internal_orders.csv"]:
        fpath = gen_dir / fname
        if fpath.exists():
            try:
                sdf = pd.read_csv(fpath)
                sid_col = "settlement_id" if "settlement_id" in sdf.columns else ("order_id" if "order_id" in sdf.columns else None)
                if sid_col:
                    for _, srow in sdf.iterrows():
                        sid = str(srow[sid_col])
                        amt = srow.get("amount") if pd.notna(srow.get("amount")) else srow.get("credit", 0)
                        desc_val = srow.get("description")
                        if pd.isna(desc_val) or not str(desc_val).strip() or str(desc_val).strip() == "nan":
                            desc_val = srow.get("customer") or srow.get("order_id") or sid
                        dt = srow.get("date") or srow.get("created_at") or srow.get("settlement_date") or ""
                        stype = "Orders" if "order_id" in fname or "order_id" in str(srow) else "Settlement"
                        sources[sid] = {"amount": float(pd.to_numeric(amt, errors="coerce") or 0.0), "description": str(desc_val), "date": str(dt), "source": stype}
            except Exception:
                pass

    rows = []

    for number, (_, row) in enumerate(
        exceptions.iterrows(),
        start=1,
    ):

        exception_type = classify_exception(row)
        priority = determine_priority(exception_type, row["confidence"])

        sid = str(row.get("settlement_id", ""))
        sinfo = sources.get(sid, {})

        amt = sinfo.get("amount", float(pd.to_numeric(row.get("amount"), errors="coerce") or 0.0))
        desc = sinfo.get("description") or row.get("description") or sid or "Unresolved Settlement"
        dt = sinfo.get("date") or row.get("created_at") or ""
        stype = sinfo.get("source") or row.get("stage") or "reconciler"

        rows.append(
            {
                "exception_id": f"EXC-{number:04d}",
                "created_at": dt or datetime.now(timezone.utc).isoformat(),
                "settlement_id": sid,
                "bank_transaction_id": row["bank_transaction_id"],
                "description": desc,
                "amount": amt,
                "source": stype,
                "stage": row["stage"],
                "decision": row["decision"],
                "confidence": float(row["confidence"]),
                "exception_type": exception_type,
                "priority": priority,
                "reason": row["reason"],
                "resolution_status": "open",
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    reconciliation,
    exceptions,
):

    total_settlements = (
        reconciliation[
            "settlement_id"
        ].nunique()
    )

    total_exceptions = len(
        exceptions
    )

    print("=" * 60)
    print("LEDGER - EXCEPTION LEDGER")
    print("=" * 60)

    print(
        f"Settlements processed : "
        f"{total_settlements}"
    )

    print(
        f"Exceptions created    : "
        f"{total_exceptions}"
    )

    print()

    if exceptions.empty:
        print(
            "No manual-review exceptions."
        )
        return

    print("Exception types:")

    print(
        exceptions[
            "exception_type"
        ]
        .value_counts()
        .to_string()
    )

    print()

    print("Priorities:")

    print(
        exceptions[
            "priority"
        ]
        .value_counts()
        .to_string()
    )

    print()

    print("Resolution status:")

    print(
        exceptions[
            "resolution_status"
        ]
        .value_counts()
        .to_string()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not RECONCILIATION_PATH.exists():
        raise FileNotFoundError(
            "Reconciliation results not found:\n"
            f"{RECONCILIATION_PATH}\n\n"
            "Run first:\n"
            "python reconciler/reconcile.py"
        )

    reconciliation = pd.read_csv(
        RECONCILIATION_PATH
    )

    required_columns = {
        "settlement_id",
        "bank_transaction_id",
        "stage",
        "decision",
        "confidence",
        "reason",
        "status",
    }

    missing = (
        required_columns
        - set(reconciliation.columns)
    )

    if missing:
        raise ValueError(
            "reconciliation_results.csv "
            "is missing columns: "
            f"{sorted(missing)}"
        )

    exceptions = build_exception_ledger(
        reconciliation
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    exceptions.to_csv(
        EXCEPTION_OUTPUT_PATH,
        index=False,
    )

    print_summary(
        reconciliation,
        exceptions,
    )

    print()
    print(
        f"Saved: {EXCEPTION_OUTPUT_PATH}"
    )

    print("=" * 60)
    print("EXCEPTION LEDGER COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()