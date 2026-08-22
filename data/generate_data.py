import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

SEED = 42
NUM_ORDERS = 220

# Fraction of NUM_ORDERS affected by each noise category.
NOISE_FRACTIONS = {
    "date_offset": 0.10,
    "rounding_drift": 0.08,
    "garbled_narration": 0.08,
    "missing_utr": 0.08,
    "partial_refund": 0.06,
    "split_settlement": 0.05,
}

# Standalone orphan / adversarial record counts (not tied to
# a specific order index).
NEAR_DUPLICATE_ORPHAN_COUNT = 6
ORPHAN_BANK_COUNT = 6
ORPHAN_SETTLEMENT_COUNT = 6

# "Look-alike" pairs: two unrelated, genuine settlements whose
# amount and date land close enough to each other to be
# confusable, but whose UTRs differ. These are the adversarial
# negatives a matcher/model must correctly reject.
ADVERSARIAL_LOOKALIKE_PAIRS = 18
ADVERSARIAL_AMOUNT_DELTA = 15.00
ADVERSARIAL_DATE_DELTA_DAYS = 2

ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"

random.seed(SEED)


# ============================================================
# HELPERS
# ============================================================

def generate_id(prefix, number):
    return f"{prefix}_{number:04d}"


def random_amount():
    return random.randint(500, 100000)


def random_date(start_date, end_date):
    days = (end_date - start_date).days
    return start_date + timedelta(
        days=random.randint(0, days)
    )


def iso_plus_days(iso_date, days):
    return (
        datetime.fromisoformat(iso_date)
        + timedelta(days=days)
    ).date().isoformat()


# ============================================================
# BASE DATA GENERATION
# ============================================================

def generate_base_records():
    start_date = datetime(2026, 6, 1)
    end_date = datetime(2026, 8, 15)

    orders = []
    settlements = []
    bank_transactions = []
    relationships = []

    for i in range(1, NUM_ORDERS + 1):

        order_id = generate_id("order", i)
        payment_id = generate_id("pay", i)
        settlement_id = generate_id("setl", i)
        bank_id = generate_id("bank", i)

        utr = f"UTR{random.randint(10**9, 10**10 - 1)}"

        order_date = random_date(
            start_date,
            end_date,
        )

        gross_amount = random_amount()

        # Controlled fee model.
        fee = round(
            gross_amount * 0.02,
            2,
        )

        tax = round(
            fee * 0.18,
            2,
        )

        settlement_amount = round(
            gross_amount - fee - tax,
            2,
        )

        settlement_date = (
            order_date + timedelta(days=2)
        )

        bank_date = (
            settlement_date + timedelta(days=1)
        )

        # ----------------------------------------------------
        # INTERNAL ORDER
        # ----------------------------------------------------

        orders.append(
            {
                "order_id": order_id,
                "payment_id": payment_id,
                "order_date": order_date.date().isoformat(),
                "gross_amount": gross_amount,
                "currency": "INR",
                "refund_amount": 0.0,
                "expected_settlement": settlement_amount,
            }
        )

        # ----------------------------------------------------
        # RAZORPAY-STYLE SETTLEMENT
        # ----------------------------------------------------

        settlements.append(
            {
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "order_id": order_id,
                "settlement_date": settlement_date.date().isoformat(),
                "amount": settlement_amount,
                "fee": fee,
                "tax": tax,
                "currency": "INR",
                "utr": utr,
            }
        )

        # ----------------------------------------------------
        # BANK STATEMENT
        # ----------------------------------------------------

        bank_transactions.append(
            {
                "bank_transaction_id": bank_id,
                "transaction_date": bank_date.date().isoformat(),
                "description": (
                    f"RAZORPAY SETTLEMENT {utr}"
                ),
                "utr": utr,
                "credit": settlement_amount,
                "debit": 0.0,
                "currency": "INR",
            }
        )

        # ----------------------------------------------------
        # GROUND TRUTH
        # ----------------------------------------------------

        relationships.append(
            {
                "order_id": order_id,
                "payment_id": payment_id,
                "settlement_id": settlement_id,
                "bank_transaction_id": bank_id,
                "relationship_type": "exact",
                "is_match": True,
            }
        )

    return (
        orders,
        settlements,
        bank_transactions,
        relationships,
    )


# ============================================================
# NOISE INDEX PLANNING
# ============================================================

def build_noise_plan():
    """
    Assigns each noise category a disjoint set of order
    indices (0-based), sized as a fraction of NUM_ORDERS.
    Disjoint so no single record is hit by two noise types,
    keeping each ground-truth relationship_type unambiguous.
    """

    all_indices = list(range(NUM_ORDERS))
    random.shuffle(all_indices)

    plan = {}
    cursor = 0

    for category, fraction in NOISE_FRACTIONS.items():
        count = max(1, int(NUM_ORDERS * fraction))
        plan[category] = all_indices[cursor: cursor + count]
        cursor += count

    return plan


# ============================================================
# CONTROLLED NOISE INJECTION
# ============================================================

def inject_noise(
    orders,
    settlements,
    bank_transactions,
    relationships,
    plan,
):
    """
    Add realistic reconciliation problems while preserving
    ground truth. Each category is applied across a
    proportional slice of records (see NOISE_FRACTIONS)
    instead of a single hardcoded index.
    """

    # --------------------------------------------------------
    # 1. DATE OFFSET
    # --------------------------------------------------------

    for index in plan["date_offset"]:

        offset_days = random.choice([2, 3, 4])

        bank_transactions[index]["transaction_date"] = (
            iso_plus_days(
                bank_transactions[index]["transaction_date"],
                offset_days,
            )
        )

        relationships[index]["relationship_type"] = (
            "date_offset"
        )

    # --------------------------------------------------------
    # 2. ROUNDING DRIFT
    # --------------------------------------------------------

    for index in plan["rounding_drift"]:

        drift = random.choice([-0.50, -0.25, 0.25, 0.50, 0.75])

        bank_transactions[index]["credit"] = round(
            bank_transactions[index]["credit"] + drift,
            2,
        )

        relationships[index]["relationship_type"] = (
            "rounding_drift"
        )

    # --------------------------------------------------------
    # 3. GARBLED BANK NARRATION
    # --------------------------------------------------------

    for index in plan["garbled_narration"]:

        utr = bank_transactions[index]["utr"]

        style = random.choice(
            [
                f"RAZRPAY SETL {utr[-6:]}",
                f"RZRPY-STL/{utr[-5:]}/NEFT",
                f"SETL RZP {utr[3:9]}XX",
            ]
        )

        bank_transactions[index]["description"] = style

        relationships[index]["relationship_type"] = (
            "garbled_narration"
        )

    # --------------------------------------------------------
    # 4. MISSING UTR
    # --------------------------------------------------------

    for index in plan["missing_utr"]:

        bank_transactions[index]["utr"] = ""

        relationships[index]["relationship_type"] = (
            "missing_utr"
        )

    # --------------------------------------------------------
    # 5. PARTIAL REFUND
    # --------------------------------------------------------

    for index in plan["partial_refund"]:

        refund_pct = random.choice([0.10, 0.15, 0.20, 0.30])

        refund_amount = round(
            orders[index]["gross_amount"] * refund_pct,
            2,
        )

        orders[index]["refund_amount"] = refund_amount

        orders[index]["expected_settlement"] = round(
            orders[index]["expected_settlement"]
            - refund_amount,
            2,
        )

        settlements[index]["amount"] = round(
            settlements[index]["amount"]
            - refund_amount,
            2,
        )

        bank_transactions[index]["credit"] = (
            settlements[index]["amount"]
        )

        relationships[index]["relationship_type"] = (
            "partial_refund"
        )

    # --------------------------------------------------------
    # 6. SPLIT SETTLEMENT
    # --------------------------------------------------------

    split_counter = 1

    for index in plan["split_settlement"]:

        original = bank_transactions[index]

        original_amount = original["credit"]

        split_pct = random.choice([0.40, 0.50, 0.60, 0.70])

        first_amount = round(
            original_amount * split_pct,
            2,
        )

        second_amount = round(
            original_amount - first_amount,
            2,
        )

        split_id = generate_id("bank_split", split_counter)
        split_counter += 1

        original["credit"] = first_amount
        original["description"] = (
            f"RAZORPAY SETL PART 1 {original['utr']}"
        )

        second = original.copy()
        second["bank_transaction_id"] = split_id
        second["credit"] = second_amount
        second["description"] = (
            f"RAZORPAY SETL PART 2 {second['utr']}"
        )
        second["transaction_date"] = iso_plus_days(
            original["transaction_date"],
            random.choice([1, 2]),
        )

        bank_transactions.append(second)
        relationships.append(
            {
                "order_id": orders[index]["order_id"],
                "payment_id": orders[index]["payment_id"],
                "settlement_id": settlements[index]["settlement_id"],
                "bank_transaction_id": split_id,
                "relationship_type": "split_settlement",
                "is_match": True,
            }
        )
        relationships[index]["relationship_type"] = (
            "split_settlement"
        )

    # --------------------------------------------------------
    # 7. NEAR-DUPLICATE ORPHANS
    # --------------------------------------------------------
    # Real-looking bank credits that superficially resemble a
    # settlement (garbled RAZORPAY narration) but do not
    # correspond to any real settlement/order. Sourced only
    # from untouched baseline records -- if the source record
    # already carries other noise (e.g. missing_utr), cloning
    # it can leak the real UTR into the duplicate's narration
    # text even though its structured utr field reads empty,
    # producing an artificially "helpful" orphan.

    noised_indices = set().union(*plan.values())

    clean_pool = [
        i for i in range(NUM_ORDERS)
        if i not in noised_indices
    ]

    duplicate_sources = random.sample(
        clean_pool,
        min(NEAR_DUPLICATE_ORPHAN_COUNT, len(clean_pool)),
    )

    for n, source_index in enumerate(duplicate_sources, start=1):

        source = bank_transactions[source_index]
        duplicate = source.copy()

        duplicate_id = generate_id("bank_orphan_dup", n)
        duplicate["bank_transaction_id"] = duplicate_id

        duplicate["description"] = (
            duplicate["description"].replace(
                "RAZORPAY", "RAZRPAY"
            )
        )

        drift = random.uniform(10.0, 40.0)
        duplicate["credit"] = round(
            duplicate["credit"] + drift, 2
        )

        bank_transactions.append(duplicate)

        relationships.append(
            {
                "order_id": "",
                "payment_id": "",
                "settlement_id": "",
                "bank_transaction_id": duplicate_id,
                "relationship_type": "near_duplicate_orphan",
                "is_match": False,
            }
        )

    # --------------------------------------------------------
    # 8. GENUINE ORPHAN BANK RECORDS
    # --------------------------------------------------------

    for n in range(1, ORPHAN_BANK_COUNT + 1):

        orphan_id = generate_id("bank_orphan", n)
        orphan_date = random_date(
            datetime(2026, 6, 1), datetime(2026, 8, 15)
        ).date().isoformat()
        orphan_utr = f"UTR{random.randint(10**9, 10**10 - 1)}"

        bank_transactions.append(
            {
                "bank_transaction_id": orphan_id,
                "transaction_date": orphan_date,
                "description": (
                    f"RAZORPAY SETL UNKNOWN {orphan_utr}"
                ),
                "utr": orphan_utr,
                "credit": round(random.uniform(1000, 9000), 2),
                "debit": 0.0,
                "currency": "INR",
            }
        )

        relationships.append(
            {
                "order_id": "",
                "payment_id": "",
                "settlement_id": "",
                "bank_transaction_id": orphan_id,
                "relationship_type": "orphan_bank",
                "is_match": False,
            }
        )

    # --------------------------------------------------------
    # 9. GENUINE ORPHAN SETTLEMENTS
    # --------------------------------------------------------

    for n in range(1, ORPHAN_SETTLEMENT_COUNT + 1):

        orphan_settlement_id = generate_id(
            "setl_orphan", n
        )
        orphan_payment_id = generate_id("pay_orphan", n)
        orphan_order_id = generate_id("order_orphan", n)
        orphan_utr = f"UTR{random.randint(10**9, 10**10 - 1)}"

        orphan_date = random_date(
            datetime(2026, 6, 1), datetime(2026, 8, 15)
        ).date().isoformat()

        settlements.append(
            {
                "settlement_id": orphan_settlement_id,
                "payment_id": orphan_payment_id,
                "order_id": orphan_order_id,
                "settlement_date": orphan_date,
                "amount": round(random.uniform(1000, 9000), 2),
                "fee": 0.0,
                "tax": 0.0,
                "currency": "INR",
                "utr": orphan_utr,
            }
        )

        relationships.append(
            {
                "order_id": orphan_order_id,
                "payment_id": orphan_payment_id,
                "settlement_id": orphan_settlement_id,
                "bank_transaction_id": "",
                "relationship_type": "orphan_settlement",
                "is_match": False,
            }
        )

    # --------------------------------------------------------
    # 10. ADVERSARIAL LOOK-ALIKE PAIRS
    # --------------------------------------------------------
    # Nudges pairs of genuine, already-matched settlements so
    # their amount and settlement date land close to each
    # other. This forces exact/tolerance/ML matching to rely
    # on UTR and narration rather than amount+date alone,
    # since a naive amount+date matcher would be tempted to
    # cross-match them. No ground-truth rows are added here —
    # the existing "exact" pairs for these orders stay correct;
    # this step only makes the candidate *pool* harder to
    # search.

    clean_indices = [
        i for i in range(NUM_ORDERS)
        if i not in plan["partial_refund"]
        and i not in plan["split_settlement"]
    ]

    random.shuffle(clean_indices)

    pairs_made = 0
    used = set()

    for i in clean_indices:

        if pairs_made >= ADVERSARIAL_LOOKALIKE_PAIRS:
            break

        if i in used:
            continue

        target_amount = settlements[i]["amount"]
        target_date = settlements[i]["settlement_date"]

        for j in clean_indices:

            if j == i or j in used:
                continue

            amount_gap = abs(
                settlements[j]["amount"] - target_amount
            )

            date_gap = abs(
                (
                    datetime.fromisoformat(
                        settlements[j]["settlement_date"]
                    )
                    - datetime.fromisoformat(target_date)
                ).days
            )

            if (
                amount_gap <= ADVERSARIAL_AMOUNT_DELTA
                and date_gap <= ADVERSARIAL_DATE_DELTA_DAYS
            ):
                # Nudge j's amount slightly closer without
                # making it identical, so it's a hard-but-
                # distinguishable negative, never a true dup.
                nudge = random.choice([-1, 1]) * random.uniform(
                    2.0, ADVERSARIAL_AMOUNT_DELTA
                )
                settlements[j]["amount"] = round(
                    settlements[j]["amount"] + nudge, 2
                )

                used.add(i)
                used.add(j)
                pairs_made += 1
                break


# ============================================================
# SAVE DATA
# ============================================================

def save_data(
    orders,
    settlements,
    bank_transactions,
    relationships,
):
    GENERATED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    GROUND_TRUTH_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    pd.DataFrame(orders).to_csv(
        GENERATED_DIR / "internal_orders.csv",
        index=False,
    )

    pd.DataFrame(settlements).to_csv(
        GENERATED_DIR / "razorpay_settlements.csv",
        index=False,
    )

    pd.DataFrame(bank_transactions).to_csv(
        GENERATED_DIR / "bank_statement.csv",
        index=False,
    )

    pd.DataFrame(relationships).to_csv(
        GROUND_TRUTH_DIR / "relationships.csv",
        index=False,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    (
        orders,
        settlements,
        bank_transactions,
        relationships,
    ) = generate_base_records()

    plan = build_noise_plan()

    inject_noise(
        orders,
        settlements,
        bank_transactions,
        relationships,
        plan,
    )

    save_data(
        orders,
        settlements,
        bank_transactions,
        relationships,
    )

    print("=" * 60)
    print("LEDGER DATA GENERATION")
    print("=" * 60)

    print(f"Internal orders: {len(orders)}")
    print(f"Settlements:     {len(settlements)}")
    print(f"Bank records:    {len(bank_transactions)}")
    print(f"Ground truth:    {len(relationships)}")

    print("\nNoise counts:")
    for category, indices in plan.items():
        print(f"  - {category:<26} {len(indices)}")

    print(f"  - {'near_duplicate_orphan':<26} {NEAR_DUPLICATE_ORPHAN_COUNT}")
    print(f"  - {'orphan_bank':<26} {ORPHAN_BANK_COUNT}")
    print(f"  - {'orphan_settlement':<26} {ORPHAN_SETTLEMENT_COUNT}")
    print(f"  - {'adversarial_lookalike_pairs':<26} {ADVERSARIAL_LOOKALIKE_PAIRS}")

    print(
        "\nGenerated under "
        "data/generated/ and data/ground_truth/"
    )


if __name__ == "__main__":
    main()