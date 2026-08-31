"""
exception_ledger.py — Manual Review Exception Engine for Ledger AI v2.

Enhancements:
  - T7.1: Extended Exception Ledger schema with additive types:
          ambiguous_tie, insufficient_data, failed_status_excluded, duplicate_detected
          while preserving llm_review, llm_unavailable, unresolved, manual_review, non_match.
  - T7.2: Added resolved_outcome (confirmed_match | confirmed_non_match | null) and
          resolved_by (human identifier) for human-in-the-loop adaptation (T4.6).
"""

from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"
RECONCILIATION_PATH = RESULTS_DIR / "reconciliation_results.csv"
EXCEPTION_OUTPUT_PATH = RESULTS_DIR / "exception_ledger.csv"


# ============================================================
# EXCEPTION CLASSIFICATION (T7.1)
# ============================================================

def classify_exception(row):
    """Classifies exception category based on decision stage, reason keywords, and exception metadata."""
    stage = str(row.get("stage", ""))
    decision = str(row.get("decision", ""))
    reason = str(row.get("reason", "")).lower()
    exc_type = str(row.get("exception_type", ""))

    # T7.1 Explicit / Direct Enum Classification
    if exc_type == "open_refund" or "refund" in reason or "chargeback" in reason:
        return "open_refund"

    if exc_type == "ambiguous_tie" or "ambiguous tie" in reason or "ambiguous_tie" in reason:
        return "ambiguous_tie"

    if exc_type == "insufficient_data" or decision == "insufficient_data" or "insufficient data" in reason or "insufficient_data" in reason:
        return "insufficient_data"

    if exc_type == "failed_status_excluded" or "status excluded" in reason or "status_excluded" in reason:
        return "failed_status_excluded"

    if exc_type == "duplicate_detected" or "duplicate" in reason or "duplicate_detected" in reason:
        return "duplicate_detected"

    # Additive legacy handling (T7.1)
    if decision == "review":
        if stage == "llm":
            return "llm_review"
        if "no llm result" in reason:
            return "llm_unavailable"
        if stage in ("reconciler", "tolerance_matcher"):
            return "unresolved"
        return "manual_review"

    if decision == "non_match":
        return "non_match"

    return "unknown"


def determine_priority(exception_type, confidence):
    """Determines exception review priority (high, medium, low) based on exception type and model confidence."""
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0.0

    if exception_type in {
        "llm_unavailable",
        "unresolved",
        "ambiguous_tie",
        "insufficient_data",
        "duplicate_detected",
    }:
        return "high"

    if confidence < 0.70:
        return "high"

    if confidence < 0.85:
        return "medium"

    return "low"


# ============================================================
# BUILD EXCEPTION LEDGER (T7.2)
# ============================================================

def build_exception_ledger(reconciliation):
    """Builds structured Exception Ledger DataFrame from reconciliation results, preserving prior human audit resolutions."""
    exceptions = reconciliation[
        reconciliation["status"].isin(["SIMILAR", "similar", "manual_review", "review", "UNMATCHED", "unmatched", "EXCEPTION", "exception"])
    ].copy()


    # Load existing exception ledger if present to preserve human resolution fields (T7.2)
    existing_lookup = {}
    if EXCEPTION_OUTPUT_PATH.exists():
        try:
            edf = pd.read_csv(EXCEPTION_OUTPUT_PATH)
            if not edf.empty and "exception_id" in edf.columns:
                for _, erow in edf.iterrows():
                    key = (str(erow.get("settlement_id")), str(erow.get("bank_transaction_id")))
                    existing_lookup[key] = erow
        except Exception:
            pass

    if exceptions.empty:
        return pd.DataFrame(
            columns=[
                "exception_id",
                "created_at",
                "settlement_id",
                "bank_transaction_id",
                "description",
                "amount",
                "source",
                "stage",
                "decision",
                "confidence",
                "exception_type",
                "priority",
                "reason",
                "resolution_status",
                "resolved_outcome",  # T7.2
                "resolved_by",       # T7.2
            ]
        )

    # Load source records to populate real amount, description, date
    sources = {}
    gen_dir = ROOT / "data" / "generated"
    for fname in ["primary_records.csv", "bank_statement.csv", "counterpart_records.csv", "razorpay_settlements.csv", "internal_orders.csv"]:
        fpath = gen_dir / fname
        if fpath.exists():
            try:
                sdf = pd.read_csv(fpath)
                id_cols = ["primary_transaction_id", "transaction_id", "settlement_id", "bank_transaction_id", "order_id"]
                found_id_cols = [c for c in id_cols if c in sdf.columns]
                if found_id_cols:
                    for _, srow in sdf.iterrows():
                        for id_c in found_id_cols:
                            sid = str(srow[id_c]).strip()
                            if not sid or sid == "nan":
                                continue
                            raw_amt = srow.get("amount") if pd.notna(srow.get("amount")) else (srow.get("net_amount") if pd.notna(srow.get("net_amount")) else srow.get("credit", 0))
                            amt_val = float(pd.to_numeric(raw_amt, errors="coerce") or 0.0)
                            desc_val = srow.get("description") if pd.notna(srow.get("description")) else srow.get("narration")
                            if pd.isna(desc_val) or not str(desc_val).strip() or str(desc_val).strip() == "nan":
                                desc_val = srow.get("customer") or srow.get("order_id") or sid
                            dt = srow.get("date") or srow.get("transaction_date") or srow.get("created_at") or srow.get("settlement_date") or ""
                            stype = "Orders" if "order_id" in fname or "order_id" in str(srow) else ("Bank Statement" if "primary" in fname or "bank" in fname else "Settlement")
                            if sid not in sources or (sources[sid]["amount"] == 0.0 and amt_val != 0.0):
                                sources[sid] = {
                                    "amount": amt_val,
                                    "description": str(desc_val),
                                    "date": str(dt),
                                    "source": stype
                                }
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
        bid = str(row.get("bank_transaction_id", ""))
        sinfo = sources.get(sid, {})

        amt = sinfo.get("amount", float(pd.to_numeric(row.get("amount"), errors="coerce") or 0.0))
        desc = sinfo.get("description") or row.get("description") or sid or "Unresolved Settlement"
        dt = sinfo.get("date") or row.get("created_at") or ""
        stype = sinfo.get("source") or row.get("stage") or "reconciler"

        # Check if existing resolution status/outcome exists (T7.2)
        prev = existing_lookup.get((sid, bid), {})
        res_status = str(prev.get("resolution_status") or "open")
        res_outcome = prev.get("resolved_outcome") if pd.notna(prev.get("resolved_outcome")) else None
        res_by = prev.get("resolved_by") if pd.notna(prev.get("resolved_by")) else None

        rows.append(
            {
                "exception_id": f"EXC-{number:04d}",
                "created_at": dt or datetime.now(timezone.utc).isoformat(),
                "settlement_id": sid,
                "bank_transaction_id": bid,
                "description": desc,
                "amount": amt,
                "source": stype,
                "stage": row["stage"],
                "decision": row["decision"],
                "confidence": float(row["confidence"]),
                "exception_type": exception_type,
                "priority": priority,
                "reason": row["reason"],
                "resolution_status": res_status,
                "resolved_outcome": res_outcome,  # T7.2 (confirmed_match | confirmed_non_match | null)
                "resolved_by": res_by,            # T7.2 (human identifier)
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# SUMMARY
# ============================================================

def print_summary(reconciliation, exceptions):
    """Prints a formatted console summary of exception ledger breakdown."""
    total_settlements = reconciliation["settlement_id"].nunique()
    total_exceptions = len(exceptions)

    print("=" * 60)
    print("LEDGER - EXCEPTION LEDGER (v2 Extended)")
    print("=" * 60)
    print(f"Settlements processed : {total_settlements}")
    print(f"Exceptions created    : {total_exceptions}")
    print()

    if exceptions.empty:
        print("No manual-review exceptions.")
        return

    print("Exception types:")
    print(exceptions["exception_type"].value_counts().to_string())
    print()

    print("Priorities:")
    print(exceptions["priority"].value_counts().to_string())
    print()

    print("Resolution status:")
    print(exceptions["resolution_status"].value_counts().to_string())


# ============================================================
# MAIN
# ============================================================

def main():
    """CLI execution entrypoint for building exception ledger standalone."""
    if not RECONCILIATION_PATH.exists():
        raise FileNotFoundError(
            "Reconciliation results not found:\n"
            f"{RECONCILIATION_PATH}\n\n"
            "Run first:\n"
            "python reconciler/reconcile.py"
        )

    reconciliation = pd.read_csv(RECONCILIATION_PATH)

    required_columns = {
        "settlement_id",
        "bank_transaction_id",
        "stage",
        "decision",
        "confidence",
        "reason",
        "status",
    }

    missing = required_columns - set(reconciliation.columns)
    if missing:
        raise ValueError(
            f"reconciliation_results.csv is missing columns: {sorted(missing)}"
        )

    exceptions = build_exception_ledger(reconciliation)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    exceptions.to_csv(EXCEPTION_OUTPUT_PATH, index=False)

    print_summary(reconciliation, exceptions)
    print(f"\nSaved: {EXCEPTION_OUTPUT_PATH}")
    print("=" * 60)
    print("EXCEPTION LEDGER COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()