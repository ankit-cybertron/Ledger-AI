from pathlib import Path
from difflib import SequenceMatcher
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
ML_DIR = ROOT / "data" / "ml"

SEED = 42
NEGATIVE_RATIO = 4



# ============================================================
# HELPERS
# ============================================================

def normalize_text(value):
    if pd.isna(value):
        return ""

    return (
        str(value)
        .upper()
        .strip()
        .replace(" ", "")
    )


def text_similarity(left, right):
    left = normalize_text(left)
    right = normalize_text(right)

    if not left or not right:
        return 0.0

    return SequenceMatcher(
        None,
        left,
        right,
    ).ratio()


def date_difference_days(left, right):
    left = pd.to_datetime(left)
    right = pd.to_datetime(right)

    return abs(
        (left - right).days
    )


# ============================================================
# LOAD DATA
# ============================================================

def load_data():
    settlements = pd.read_csv(
        GENERATED_DIR / "razorpay_settlements.csv"
    )

    bank = pd.read_csv(
        GENERATED_DIR / "bank_statement.csv"
    )

    ground_truth = pd.read_csv(
        GROUND_TRUTH_DIR / "relationships.csv"
    )

    return settlements, bank, ground_truth


# ============================================================
# GROUND-TRUTH PAIRS
# ============================================================

def build_ground_truth_pairs(ground_truth):
    """
    Ground truth can contain multiple bank transactions
    for one settlement because of split settlements.
    """

    true_pairs = set()

    for _, row in ground_truth.iterrows():

        if not bool(row["is_match"]):
            continue

        settlement_id = row["settlement_id"]
        bank_id = row["bank_transaction_id"]

        if not settlement_id or not bank_id:
            continue

        true_pairs.add(
            (
                settlement_id,
                bank_id,
            )
        )

    return true_pairs


# ============================================================
# FEATURE ENGINEERING
# ============================================================

def create_features(
    settlement,
    bank_transaction,
    label,
):
    settlement_utr = normalize_text(settlement.get("utr"))
    bank_utr = normalize_text(bank_transaction.get("utr"))

    setl_amt_raw = settlement.get("amount") if pd.notna(settlement.get("amount")) else settlement.get("credit", 0)
    settlement_amount = float(pd.to_numeric(setl_amt_raw, errors="coerce") or 0.0)

    bank_amt_raw = bank_transaction.get("credit") if pd.notna(bank_transaction.get("credit")) else bank_transaction.get("amount", 0)
    bank_amount = float(pd.to_numeric(bank_amt_raw, errors="coerce") or 0.0)

    amount_difference = abs(settlement_amount - bank_amount)
    amount_difference_pct = (
        amount_difference / settlement_amount
        if settlement_amount
        else 0.0
    )

    setl_date = settlement.get("settlement_date") or settlement.get("date") or settlement.get("created_at") or "2026-01-01"
    bank_date = bank_transaction.get("transaction_date") or bank_transaction.get("date") or "2026-01-01"

    date_difference = date_difference_days(setl_date, bank_date)

    utr_match = int(
        bool(settlement_utr)
        and bool(bank_utr)
        and settlement_utr == bank_utr
    )

    utr_missing = int(
        not settlement_utr
        or not bank_utr
    )

    narration_similarity = text_similarity(
        settlement.get("description") or settlement_utr,
        bank_transaction.get("description"),
    )

    setl_curr = str(settlement.get("currency", "INR") or "INR").upper()
    bank_curr = str(bank_transaction.get("currency", "INR") or "INR").upper()
    currency_match = int(setl_curr == bank_curr)

    return {
        "settlement_id": settlement[
            "settlement_id"
        ],
        "bank_transaction_id": bank_transaction[
            "bank_transaction_id"
        ],
        "settlement_amount": settlement_amount,
        "bank_amount": bank_amount,
        "amount_difference": round(
            amount_difference,
            2,
        ),
        "amount_difference_pct": round(
            amount_difference_pct,
            6,
        ),
        "date_difference_days": date_difference,
        "utr_match": utr_match,
        "utr_missing": utr_missing,
        "narration_similarity": round(
            narration_similarity,
            6,
        ),
        "currency_match": currency_match,
        "label": label,
    }


# ============================================================
# POSITIVE EXAMPLES
# ============================================================

def build_positive_examples(
    settlements,
    bank,
    true_pairs,
):
    settlement_lookup = (
        settlements.set_index(
            "settlement_id"
        )
    )

    bank_lookup = (
        bank.set_index(
            "bank_transaction_id"
        )
    )

    examples = []

    for settlement_id, bank_id in sorted(
        true_pairs
    ):

        if settlement_id not in settlement_lookup.index:
            continue

        if bank_id not in bank_lookup.index:
            continue

        settlement = settlement_lookup.loc[
            settlement_id
        ].copy()

        settlement["settlement_id"] = settlement_id

        bank_transaction = bank_lookup.loc[
            bank_id
        ].copy()

        bank_transaction["bank_transaction_id"] = bank_id

        examples.append(
            create_features(
                settlement,
                bank_transaction,
                label=1,
            )
        )

    return examples


# ============================================================
# NEGATIVE EXAMPLES
# ============================================================

def build_negative_examples(
    settlements,
    bank,
    true_pairs,
    positive_examples,
):
    """
    Create difficult negative examples.

    Negative candidates deliberately resemble real matches:
        - same currency
        - similar amount
        - nearby date
        - similar narration
        - some candidates have missing UTR
        - never use a known true relationship
    """

    settlement_lookup = settlements.set_index(
        "settlement_id"
    )

    bank_lookup = bank.set_index(
        "bank_transaction_id"
    )

    true_bank_by_settlement = {}

    for settlement_id, bank_id in true_pairs:
        true_bank_by_settlement.setdefault(
            settlement_id,
            set(),
        ).add(bank_id)

    candidates = []

    for settlement_id in settlements["settlement_id"]:

        settlement = settlement_lookup.loc[
            settlement_id
        ]

        true_bank_ids = true_bank_by_settlement.get(
            settlement_id,
            set(),
        )

        for bank_id in bank["bank_transaction_id"]:

            if bank_id in true_bank_ids:
                continue

            bank_transaction = bank_lookup.loc[
                bank_id
            ]

            # Safe currency match
            setl_curr = str(settlement.get("currency", "INR") or "INR").upper()
            bank_curr = str(bank_transaction.get("currency", "INR") or "INR").upper()
            currency_match = int(setl_curr == bank_curr)

            if not currency_match:
                continue

            setl_amt_raw = settlement.get("amount") if pd.notna(settlement.get("amount")) else settlement.get("credit", 0)
            settlement_amount = float(pd.to_numeric(setl_amt_raw, errors="coerce") or 0.0)

            bank_amt_raw = bank_transaction.get("credit") if pd.notna(bank_transaction.get("credit")) else bank_transaction.get("amount", 0)
            bank_amount = float(pd.to_numeric(bank_amt_raw, errors="coerce") or 0.0)

            amount_difference = abs(
                settlement_amount
                - bank_amount
            )

            amount_difference_pct = (
                amount_difference / settlement_amount
                if settlement_amount
                else 1.0
            )

            setl_date = settlement.get("settlement_date") or settlement.get("date") or settlement.get("created_at") or "2026-01-01"
            bank_date = bank_transaction.get("transaction_date") or bank_transaction.get("date") or "2026-01-01"

            date_difference = date_difference_days(
                setl_date,
                bank_date,
            )

            narration_similarity = text_similarity(
                settlement.get("utr") or settlement.get("description"),
                bank_transaction.get("description"),
            )

            settlement_utr = normalize_text(
                settlement["utr"]
            )

            bank_utr = normalize_text(
                bank_transaction["utr"]
            )

            # ------------------------------------------------
            # UTR ambiguity
            # ------------------------------------------------

            # Keep both:
            #
            # 1. Wrong-but-present UTR
            # 2. Missing UTR
            #
            # This prevents UTR from becoming the only
            # useful signal.

            utr_missing = int(
                not settlement_utr
                or not bank_utr
            )

            utr_match = int(
                bool(settlement_utr)
                and bool(bank_utr)
                and settlement_utr == bank_utr
            )

            # Never create a negative with a genuine UTR match.
            if utr_match:
                continue

            # ------------------------------------------------
            # Candidate filtering
            # ------------------------------------------------

            # Keep reasonably realistic candidates.
            if (
                amount_difference_pct > 0.25
                and date_difference > 10
                and narration_similarity < 0.25
                and not utr_missing
            ):
                continue

            # ------------------------------------------------
            # Hard-negative score
            # ------------------------------------------------

            amount_score = max(
                0.0,
                1.0 - amount_difference_pct,
            )

            date_score = max(
                0.0,
                1.0 - (
                    date_difference / 30.0
                ),
            )

            hard_negative_score = (
                0.45 * amount_score
                + 0.30 * date_score
                + 0.20 * narration_similarity
                + 0.05 * utr_missing
            )

            candidates.append(
                (
                    hard_negative_score,
                    settlement_id,
                    bank_id,
                )
            )

    # Hardest candidates first.
    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    target_count = (
        len(positive_examples)
        * NEGATIVE_RATIO
    )

    examples = []
    seen = set()

    # --------------------------------------------------------
    # First priority:
    # missing-UTR hard negatives
    # --------------------------------------------------------

    missing_utr_candidates = []

    normal_candidates = []

    for candidate in candidates:

        _, settlement_id, bank_id = candidate

        settlement = settlement_lookup.loc[
            settlement_id
        ]

        bank_transaction = bank_lookup.loc[
            bank_id
        ]

        settlement_utr = normalize_text(
            settlement["utr"]
        )

        bank_utr = normalize_text(
            bank_transaction["utr"]
        )

        if not settlement_utr or not bank_utr:
            missing_utr_candidates.append(
                candidate
            )
        else:
            normal_candidates.append(
                candidate
            )

    # Aim for roughly one third of negatives
    # to involve missing UTR evidence.
    missing_utr_target = max(
        1,
        target_count // 3,
    )

    for (
        score,
        settlement_id,
        bank_id,
    ) in missing_utr_candidates:

        if len(examples) >= missing_utr_target:
            break

        pair = (
            settlement_id,
            bank_id,
        )

        if pair in seen:
            continue

        seen.add(pair)

        settlement = settlement_lookup.loc[
            settlement_id
        ].copy()

        settlement["settlement_id"] = (
            settlement_id
        )

        bank_transaction = bank_lookup.loc[
            bank_id
        ].copy()

        bank_transaction[
            "bank_transaction_id"
        ] = bank_id

        examples.append(
            create_features(
                settlement,
                bank_transaction,
                label=0,
            )
        )

    # --------------------------------------------------------
    # Fill remaining negatives with hardest candidates.
    # --------------------------------------------------------

    for (
        score,
        settlement_id,
        bank_id,
    ) in normal_candidates:

        if len(examples) >= target_count:
            break

        pair = (
            settlement_id,
            bank_id,
        )

        if pair in seen:
            continue

        seen.add(pair)

        settlement = settlement_lookup.loc[
            settlement_id
        ].copy()

        settlement["settlement_id"] = (
            settlement_id
        )

        bank_transaction = bank_lookup.loc[
            bank_id
        ].copy()

        bank_transaction[
            "bank_transaction_id"
        ] = bank_id

        examples.append(
            create_features(
                settlement,
                bank_transaction,
                label=0,
            )
        )

    return examples

# ============================================================
# MAIN
# ============================================================

def main():
    settlements, bank, ground_truth = load_data()

    # Load orders if available and combine
    orders_path = GENERATED_DIR / "internal_orders.csv"
    if orders_path.exists():
        try:
            orders = pd.read_csv(orders_path)
            if not orders.empty:
                if "settlement_id" not in orders.columns and "order_id" in orders.columns:
                    orders["settlement_id"] = orders["order_id"]
                settlements = pd.concat([settlements, orders], ignore_index=True).drop_duplicates(subset=["settlement_id"], keep="first")
        except Exception:
            pass

    true_pairs = build_ground_truth_pairs(
        ground_truth
    )

    positive_examples = build_positive_examples(
        settlements,
        bank,
        true_pairs,
    )

    negative_examples = build_negative_examples(
        settlements,
        bank,
        true_pairs,
        positive_examples,
    )

    examples = positive_examples + negative_examples

    # Dynamic fallback when ground_truth has no matching pairs for current user data
    if not examples and not settlements.empty and not bank.empty:
        for _, s in settlements.iterrows():
            s_id = str(s.get("settlement_id", ""))
            s_amt = float(pd.to_numeric(s.get("amount"), errors="coerce") or 0.0)
            s_date = s.get("date") or s.get("settlement_date") or s.get("created_at") or "2026-01-01"
            s_utr = normalize_text(s.get("utr"))
            s_desc = str(s.get("description") or "")

            for _, b in bank.iterrows():
                b_id = str(b.get("bank_transaction_id", ""))
                b_amt = float(pd.to_numeric(b.get("amount"), errors="coerce") or pd.to_numeric(b.get("credit"), errors="coerce") or 0.0)
                b_date = b.get("date") or b.get("transaction_date") or "2026-01-01"
                b_utr = normalize_text(b.get("utr"))
                b_desc = str(b.get("description") or "")

                amt_diff = abs(s_amt - b_amt)
                amt_diff_pct = (amt_diff / s_amt) if s_amt else 1.0
                d_diff = date_difference_days(s_date, b_date)
                utr_m = int(bool(s_utr) and bool(b_utr) and s_utr == b_utr)
                utr_miss = int(not s_utr or not b_utr)
                sim = text_similarity(s_desc, b_desc)

                label = 0
                if utr_m or (amt_diff == 0 and d_diff <= 3) or (sim > 0.5 and amt_diff_pct < 0.05):
                    label = 1

                if utr_m or amt_diff_pct <= 0.35 or d_diff <= 14 or sim > 0.2:
                    examples.append({
                        "settlement_id": s_id,
                        "bank_transaction_id": b_id,
                        "settlement_amount": s_amt,
                        "bank_amount": b_amt,
                        "amount_difference": round(amt_diff, 2),
                        "amount_difference_pct": round(amt_diff_pct, 6),
                        "date_difference_days": d_diff,
                        "utr_match": utr_m,
                        "utr_missing": utr_miss,
                        "narration_similarity": round(sim, 6),
                        "currency_match": 1,
                        "label": label,
                    })

    if not examples:
        dataset = pd.DataFrame(columns=[
            "settlement_id", "bank_transaction_id", "settlement_amount", "bank_amount",
            "amount_difference", "amount_difference_pct", "date_difference_days",
            "utr_match", "utr_missing", "narration_similarity", "currency_match", "label"
        ])
    else:
        dataset = pd.DataFrame(examples)

    if not dataset.empty:
        dataset = dataset.sample(
            frac=1,
            random_state=SEED,
        ).reset_index(
            drop=True
        )

    ML_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        ML_DIR / "matching_training_data.csv"
    )

    dataset.to_csv(
        output_path,
        index=False,
    )

    print("=" * 60)
    print("LEDGER - ML TRAINING DATA")
    print("=" * 60)

    print(
        f"Positive examples: "
        f"{len(positive_examples)}"
    )

    print(
        f"Negative examples: "
        f"{len(negative_examples)}"
    )

    print(
        f"Total examples: "
        f"{len(dataset)}"
    )

    print()

    print(
        "Class distribution:"
    )

    print(
        dataset["label"]
        .value_counts()
        .sort_index()
    )

    print()

    print(
        "Features:"
    )

    feature_columns = [
        column
        for column in dataset.columns
        if column not in [
            "settlement_id",
            "bank_transaction_id",
            "label",
        ]
    ]

    for feature in feature_columns:
        print(f"  - {feature}")

    print()

    print(
        f"Saved: {output_path}"
    )


if __name__ == "__main__":
    main()