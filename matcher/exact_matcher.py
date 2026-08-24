from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"


def _safe_read_csv(path, default_cols=None):
    if not Path(path).exists():
        return pd.DataFrame(columns=default_cols or [])
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=default_cols or [])


def load_data():
    settlements = _safe_read_csv(
        GENERATED_DIR / "razorpay_settlements.csv",
        ["settlement_id", "order_id", "payment_id", "utr", "amount", "status", "created_at"]
    )
    orders = _safe_read_csv(
        GENERATED_DIR / "internal_orders.csv",
        ["order_id", "payment_id", "amount", "status", "created_at"]
    )
    bank = _safe_read_csv(
        GENERATED_DIR / "bank_statement.csv",
        ["bank_transaction_id", "date", "utr", "amount", "description"]
    )

    return settlements, bank, orders


def _norm_str(text):
    if pd.isna(text) or text is None:
        return ""
    return str(text).upper().replace(" ", "").replace("-", "").replace("_", "").replace("NEFTCR", "").strip()


def exact_match(settlements, bank, orders=None):
    """
    Match settlement, order, and bank records using multi-source rules:
        1. Internal Orders <---> UPI / Card / Cash Sub-Ledgers (Order ID, VPA, Particulars, Amount, Date)
        2. Internal Orders / Settlements <---> Direct Bank Transfers (NEFT, UTR, Customer Name)
        3. Gateway Settlements <---> Bank Statement Batch Lines (Batch UTR / Amount)
    """
    matches = []
    matched_bank_ids = set()
    matched_settlement_indices = set()
    matched_order_ids = set()

    # 1. Match Internal Orders against UPI / Card / Cash Sub-Ledger statements
    if orders is not None and not orders.empty and not settlements.empty:
        for _, o in orders.iterrows():
            oid = str(o.get("order_id") or o.get("settlement_id", "")).strip()
            oamt = round(float(pd.to_numeric(o.get("amount"), errors="coerce") or 0.0), 2)
            odate = str(o.get("date") or o.get("created_at") or "").strip()
            odesc = str(o.get("description") or o.get("Customer Name", "")).strip().lower()

            if not oid or oamt == 0.0:
                continue

            available_s = settlements[~settlements.index.isin(matched_settlement_indices)].copy()
            if available_s.empty:
                break

            for s_idx, s in available_s.iterrows():
                sid = str(s.get("settlement_id") or s.get("utr") or s.get("Gateway Ref") or s.get("Voucher No") or f"sub_{s_idx}")
                samt = round(float(pd.to_numeric(s.get("amount"), errors="coerce") or 0.0), 2)
                sdesc = str(s.get("description") or s.get("Particulars") or s.get("VPA") or "").strip().lower()
                sdt = str(s.get("date") or s.get("created_at") or "").strip()

                if oamt == samt:
                    # Match by Order ID in description or date + customer name match
                    if oid.lower() in sdesc or (odate and odate == sdt) or (odesc and any(w in sdesc for w in odesc.split() if len(w) > 3)):
                        matched_order_ids.add(oid)
                        matched_settlement_indices.add(s_idx)
                        matches.append({
                            "settlement_id": oid,
                            "bank_transaction_id": sid,
                            "amount": oamt,
                            "date": odate,
                            "match_type": "order_subledger_match",
                            "is_match": True,
                            "confidence": 1.0,
                        })
                        break

    # 2. Match Direct Bank Transfers (NEFT) & Remaining Settlements to Bank Statements
    combined_sources = settlements if settlements is not None else pd.DataFrame()
    if orders is not None and not orders.empty:
        unmatched_orders = orders[~orders["order_id"].astype(str).isin(matched_order_ids)].copy()
        if not unmatched_orders.empty:
            if "settlement_id" not in unmatched_orders.columns and "order_id" in unmatched_orders.columns:
                unmatched_orders["settlement_id"] = unmatched_orders["order_id"]
            combined_sources = pd.concat([combined_sources, unmatched_orders], ignore_index=True).drop_duplicates(subset=["settlement_id"], keep="first")

    if not combined_sources.empty and bank is not None and not bank.empty:
        for _, settlement in combined_sources.iterrows():
            settlement_id = str(settlement.get("settlement_id") or settlement.get("order_id", "")).strip()
            settlement_utr = _norm_str(settlement.get("utr"))
            
            raw_amt = settlement.get("amount")
            if pd.isna(raw_amt) or raw_amt is None:
                raw_amt = settlement.get("credit", 0)
            settlement_amount = round(float(pd.to_numeric(raw_amt, errors="coerce") or 0.0), 2)

            settlement_desc = _norm_str(settlement.get("description") or settlement.get("Customer Name"))
            settlement_date = str(settlement.get("date") or settlement.get("created_at") or "").strip()

            if not settlement_id or settlement_amount == 0.0:
                continue

            available_bank = bank[~bank["bank_transaction_id"].isin(matched_bank_ids)].copy()
            if available_bank.empty:
                break

            bank_amt_series = available_bank["amount"].round(2) if "amount" in available_bank.columns else available_bank["credit"].round(2)

            # A. Exact UTR + Amount
            if settlement_utr:
                utr_candidates = available_bank[
                    (available_bank["utr"].fillna("").apply(_norm_str) == settlement_utr)
                    & (bank_amt_series == settlement_amount)
                ]
                if len(utr_candidates) == 1:
                    cand = utr_candidates.iloc[0]
                    matched_bank_ids.add(cand["bank_transaction_id"])
                    matches.append({
                        "settlement_id": settlement_id,
                        "bank_transaction_id": cand["bank_transaction_id"],
                        "amount": settlement_amount,
                        "date": settlement_date,
                        "match_type": "exact_utr_amount",
                        "is_match": True,
                        "confidence": 1.0,
                    })
                    continue

            # B. Name / Description match + Exact Amount
            if settlement_desc and len(settlement_desc) >= 3:
                name_candidates = available_bank[
                    (bank_amt_series == settlement_amount) &
                    available_bank["description"].fillna("").apply(_norm_str).apply(lambda d: settlement_desc in d or d in settlement_desc)
                ]
                if len(name_candidates) == 1:
                    cand = name_candidates.iloc[0]
                    matched_bank_ids.add(cand["bank_transaction_id"])
                    matches.append({
                        "settlement_id": settlement_id,
                        "bank_transaction_id": cand["bank_transaction_id"],
                        "amount": settlement_amount,
                        "date": settlement_date,
                        "match_type": "exact_name_amount",
                        "is_match": True,
                        "confidence": 1.0,
                    })
                    continue

            # C. Single Unambiguous Amount & Date Match
            amt_candidates = available_bank[bank_amt_series == settlement_amount]
            if len(amt_candidates) == 1:
                cand = amt_candidates.iloc[0]
                matched_bank_ids.add(cand["bank_transaction_id"])
                matches.append({
                    "settlement_id": settlement_id,
                    "bank_transaction_id": cand["bank_transaction_id"],
                    "amount": settlement_amount,
                    "date": settlement_date,
                    "match_type": "exact_amount_single",
                    "is_match": True,
                    "confidence": 0.98,
                })

    if not matches:
        return pd.DataFrame(columns=["settlement_id", "bank_transaction_id", "match_type", "confidence"])

    return pd.DataFrame(matches)


def main():

    settlements, bank, orders = load_data()

    matches = exact_match(
        settlements,
        bank,
        orders,
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        RESULTS_DIR / "exact_matches.csv"
    )

    matches.to_csv(
        output_path,
        index=False,
    )

    print("=" * 60)
    print("LEDGER - EXACT MATCHING")
    print("=" * 60)

    print(
        f"Settlements: {len(settlements)}"
    )

    print(
        f"Bank records: {len(bank)}"
    )

    print(
        f"Exact matches: {len(matches)}"
    )

    print(
        "Unmatched settlements: "
        f"{len(settlements) - len(matches)}"
    )

    print(
        f"Saved: {output_path}"
    )


if __name__ == "__main__":
    main()
    