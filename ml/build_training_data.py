"""
build_training_data.py — ML Training Dataset Builder (v2 extended) for Ledger AI v2.

Generates positive and negative training pairs with an expanded 20+ feature vector:
  - Relative amount difference
  - UTR/RRN/Order/Gateway/Auth/Name/VPA similarities & exact match indicators
  - Direction, status compatibility, candidate count, split indicators
  - Fee-adjusted settlement equation difference
  - Explicit digit-transposition indicator
  - Dynamic one-hot encoding for present source_type and channel fields.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from matcher.tolerance_matcher import narration_similarity, _row_to_canonical
from matcher.eligibility_guards import candidates_compatible
from matcher.settlement_equation import expected_net

GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
ML_DIR = ROOT / "data" / "ml"

SEED = 42
NEGATIVE_RATIO = 4


def normalize_text(value):
    if pd.isna(value) or value is None:
        return ""
    return str(value).upper().strip().replace(" ", "")


def text_similarity(left, right):
    return narration_similarity(left, right)


def date_difference_days(left, right):
    try:
        left_dt = pd.to_datetime(left)
        right_dt = pd.to_datetime(right)
        return abs((left_dt - right_dt).days)
    except Exception:
        return 999


def load_data():
    settlements = pd.read_csv(GENERATED_DIR / "razorpay_settlements.csv", dtype={"settlement_id": str})
    bank = pd.read_csv(GENERATED_DIR / "bank_statement.csv", dtype={"bank_transaction_id": str})
    ground_truth = pd.read_csv(GROUND_TRUTH_DIR / "relationships.csv", dtype={"settlement_id": str, "bank_transaction_id": str})

    orders_path = GENERATED_DIR / "internal_orders.csv"
    if orders_path.exists():
        try:
            orders = pd.read_csv(orders_path, dtype={"order_id": str, "settlement_id": str})
            if not orders.empty:
                if "settlement_id" not in orders.columns and "order_id" in orders.columns:
                    orders["settlement_id"] = orders["order_id"]
                settlements = pd.concat([settlements, orders], ignore_index=True).drop_duplicates(subset=["settlement_id"], keep="first")
        except Exception:
            pass

    return settlements, bank, ground_truth


def build_ground_truth_pairs(ground_truth):
    true_pairs = set()
    for _, row in ground_truth.iterrows():
        is_m = str(row.get("is_match")).strip().lower() in ("true", "1")
        if not is_m:
            continue
        sid = str(row.get("settlement_id") or "").strip()
        bid = str(row.get("bank_transaction_id") or "").strip()
        if sid and bid and sid != "nan" and bid != "nan":
            true_pairs.add((sid, bid))
    return true_pairs


def create_features(settlement, bank_transaction, label):
    tx_s = _row_to_canonical(settlement, "settlement_id")
    tx_b = _row_to_canonical(bank_transaction, "bank_transaction_id")

    settlement_utr = normalize_text(settlement.get("utr"))
    bank_utr = normalize_text(bank_transaction.get("utr"))

    setl_amt_raw = settlement.get("amount") if pd.notna(settlement.get("amount")) else settlement.get("credit", 0)
    settlement_amount = float(pd.to_numeric(setl_amt_raw, errors="coerce") or 0.0)

    bank_amt_raw = bank_transaction.get("credit") if pd.notna(bank_transaction.get("credit")) else bank_transaction.get("amount", 0)
    bank_amount = float(pd.to_numeric(bank_amt_raw, errors="coerce") or 0.0)

    amount_difference = abs(settlement_amount - bank_amount)
    amount_difference_pct = (amount_difference / settlement_amount) if settlement_amount else 0.0
    relative_amount_difference = (amount_difference / max(abs(settlement_amount), abs(bank_amount), 1e-5))

    setl_date = settlement.get("settlement_date") or settlement.get("date") or settlement.get("created_at") or "2026-01-01"
    bank_date = bank_transaction.get("transaction_date") or bank_transaction.get("date") or "2026-01-01"
    date_difference = date_difference_days(setl_date, bank_date)

    utr_match = int(bool(settlement_utr) and bool(bank_utr) and settlement_utr == bank_utr)
    utr_missing = int(not settlement_utr or not bank_utr)
    utr_similarity = text_similarity(settlement.get("utr"), bank_transaction.get("utr"))

    rrn_s = normalize_text(settlement.get("rrn"))
    rrn_b = normalize_text(bank_transaction.get("rrn"))
    rrn_exact = int(bool(rrn_s) and bool(rrn_b) and rrn_s == rrn_b)
    rrn_similarity = text_similarity(settlement.get("rrn"), bank_transaction.get("rrn"))

    oid_s = normalize_text(settlement.get("order_id"))
    oid_b = normalize_text(bank_transaction.get("order_id"))
    order_id_exact = int(bool(oid_s) and bool(oid_b) and oid_s == oid_b)

    sid_s = normalize_text(settlement.get("settlement_id"))
    sid_b = normalize_text(bank_transaction.get("settlement_id"))
    settlement_id_exact = int(bool(sid_s) and bool(sid_b) and sid_s == sid_b)

    gw_s = normalize_text(settlement.get("gateway_reference") or settlement.get("Gateway Ref"))
    gw_b = normalize_text(bank_transaction.get("gateway_reference") or bank_transaction.get("Gateway Ref"))
    gateway_ref_exact = int(bool(gw_s) and bool(gw_b) and gw_s == gw_b)

    auth_s = normalize_text(settlement.get("auth_code"))
    auth_b = normalize_text(bank_transaction.get("auth_code"))
    auth_code_exact = int(bool(auth_s) and bool(auth_b) and auth_s == auth_b)

    cust_s = settlement.get("Customer Name") or settlement.get("customer_name")
    cust_b = bank_transaction.get("Customer Name") or bank_transaction.get("customer_name")
    customer_name_similarity = text_similarity(cust_s, cust_b)

    vpa_s = settlement.get("VPA") or settlement.get("vpa")
    vpa_b = bank_transaction.get("VPA") or bank_transaction.get("vpa")
    vpa_similarity = text_similarity(vpa_s, vpa_b)

    narration_sim = text_similarity(
        settlement.get("description") or settlement_utr,
        bank_transaction.get("description") or bank_utr
    )

    setl_curr = str(settlement.get("currency", "INR") or "INR").upper()
    bank_curr = str(bank_transaction.get("currency", "INR") or "INR").upper()
    currency_match = int(setl_curr == bank_curr)

    same_direction = int(str(tx_s.direction or "CREDIT").upper() == str(tx_b.direction or "CREDIT").upper())
    status_compatible = int(candidates_compatible(tx_s, tx_b))

    candidate_count = int(settlement.get("candidate_count", 1))
    split_candidate = int(bool(settlement.get("is_split") or bank_transaction.get("is_split")))

    fee_adj_diff = round(abs(expected_net(tx_s) - bank_amount), 2)
    expected_settlement_date_gap = date_difference

    duplicate_risk = int(bool(settlement.get("duplicate_risk") or bank_transaction.get("duplicate_risk")))

    # Digit Transposition feature (T4.1)
    a = settlement_amount
    b = bank_amount
    is_digit_transposition = int(
        sorted(str(int(round(a * 100)))) == sorted(str(int(round(b * 100))))
        and a != b
    )

    src_type = str(settlement.get("source_type") or "SETTLEMENT").upper()
    channel = str(settlement.get("channel") or "BANK_TRANSFER").upper()

    return {
        "settlement_id": str(settlement.get("settlement_id") or settlement.get("order_id") or "S_UNK"),
        "bank_transaction_id": str(bank_transaction.get("bank_transaction_id") or "B_UNK"),
        "settlement_amount": settlement_amount,
        "bank_amount": bank_amount,
        "amount_difference": round(amount_difference, 2),
        "amount_difference_pct": round(amount_difference_pct, 6),
        "relative_amount_difference": round(relative_amount_difference, 6),
        "date_difference_days": date_difference,
        "utr_match": utr_match,
        "utr_missing": utr_missing,
        "utr_similarity": round(utr_similarity, 4),
        "rrn_exact": rrn_exact,
        "rrn_similarity": round(rrn_similarity, 4),
        "order_id_exact": order_id_exact,
        "settlement_id_exact": settlement_id_exact,
        "gateway_ref_exact": gateway_ref_exact,
        "auth_code_exact": auth_code_exact,
        "customer_name_similarity": round(customer_name_similarity, 4),
        "vpa_similarity": round(vpa_similarity, 4),
        "narration_similarity": round(narration_sim, 6),
        "currency_match": currency_match,
        "same_direction": same_direction,
        "status_compatible": status_compatible,
        "candidate_count": candidate_count,
        "split_candidate": split_candidate,
        "fee_adjusted_difference": fee_adj_diff,
        "expected_settlement_date_gap": expected_settlement_date_gap,
        "duplicate_risk": duplicate_risk,
        "is_digit_transposition": is_digit_transposition,
        "source_type": src_type,
        "channel": channel,
        "label": label,
    }


def build_examples(settlements, bank, true_pairs):
    settlement_lookup = settlements.set_index("settlement_id") if "settlement_id" in settlements.columns else pd.DataFrame()
    bank_lookup = bank.set_index("bank_transaction_id") if "bank_transaction_id" in bank.columns else pd.DataFrame()

    positives = []
    negatives = []

    # 1. Attempt exact ground-truth pair resolution
    for sid, bid in sorted(true_pairs):
        if not settlement_lookup.empty and sid in settlement_lookup.index and not bank_lookup.empty and bid in bank_lookup.index:
            s_row = settlement_lookup.loc[sid]
            b_row = bank_lookup.loc[bid]
            if isinstance(s_row, pd.DataFrame): s_row = s_row.iloc[0]
            if isinstance(b_row, pd.DataFrame): b_row = b_row.iloc[0]

            s_dict = s_row.to_dict()
            s_dict["settlement_id"] = sid
            b_dict = b_row.to_dict()
            b_dict["bank_transaction_id"] = bid

            positives.append(create_features(s_dict, b_dict, label=1))

    # 2. Fallback candidate pairing if ground truth IDs did not yield positive pairs
    if not positives:
        for _, s in settlements.iterrows():
            s_dict = s.to_dict()
            s_utr = normalize_text(s_dict.get("utr"))
            s_amt = float(pd.to_numeric(s_dict.get("amount") or s_dict.get("credit"), errors="coerce") or 0.0)
            s_date = s_dict.get("date") or s_dict.get("settlement_date") or s_dict.get("created_at") or "2026-01-01"

            for _, b in bank.iterrows():
                b_dict = b.to_dict()
                b_utr = normalize_text(b_dict.get("utr"))
                b_amt = float(pd.to_numeric(b_dict.get("credit") or b_dict.get("amount"), errors="coerce") or 0.0)
                b_date = b_dict.get("date") or b_dict.get("transaction_date") or "2026-01-01"

                utr_m = bool(s_utr) and bool(b_utr) and s_utr == b_utr
                amt_m = (abs(s_amt - b_amt) <= 1.0)
                date_m = (date_difference_days(s_date, b_date) <= 3)

                is_match = 1 if (utr_m or (amt_m and date_m)) else 0
                feat = create_features(s_dict, b_dict, label=is_match)
                if is_match == 1:
                    positives.append(feat)
                else:
                    negatives.append(feat)

    # 3. Subsample negatives to maintain target ratio if ground truth positives were found
    if positives and not negatives:
        np.random.seed(SEED)
        for _, s in settlements.iterrows():
            s_dict = s.to_dict()
            sid = str(s_dict.get("settlement_id", ""))
            true_bids = {bid for sp_id, bid in true_pairs if sp_id == sid}
            avail_b = bank[~bank["bank_transaction_id"].isin(true_bids)] if "bank_transaction_id" in bank.columns else bank
            if avail_b.empty:
                continue

            sample_sz = min(NEGATIVE_RATIO, len(avail_b))
            sampled_b = avail_b.sample(n=sample_sz, random_state=SEED)
            for _, b in sampled_b.iterrows():
                b_dict = b.to_dict()
                negatives.append(create_features(s_dict, b_dict, label=0))

    return positives, negatives


def main():
    settlements, bank, ground_truth = load_data()
    true_pairs = build_ground_truth_pairs(ground_truth)

    positives, negatives = build_examples(settlements, bank, true_pairs)
    all_examples = positives + negatives
    df = pd.DataFrame(all_examples)

    # Dynamic One-Hot Encoding for source_type and channel
    if "source_type" in df.columns and "channel" in df.columns:
        df = pd.get_dummies(df, columns=["source_type", "channel"], prefix=["source_type", "channel"], dtype=int)

    ML_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ML_DIR / "matching_training_data.csv"
    df.to_csv(out_path, index=False)

    print("=" * 60)
    print("LEDGER - ML TRAINING DATA BUILDER (v2 Extended)")
    print("=" * 60)
    print(f"Positives: {len(positives)}")
    print(f"Negatives: {len(negatives)}")
    print(f"Total Rows: {len(df)}")
    print(f"Columns ({len(df.columns)}): {list(df.columns)}")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()