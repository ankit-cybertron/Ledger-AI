from pathlib import Path
from difflib import SequenceMatcher

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"


# ============================================================
# CONFIGURATION
# ============================================================

DATE_TOLERANCE_DAYS = 3
AMOUNT_TOLERANCE = 1.00
MIN_NARRATION_SIMILARITY = 0.50


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

    exact_matches = pd.read_csv(
        RESULTS_DIR / "exact_matches.csv"
    )

    return settlements, bank, exact_matches


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


def narration_similarity(left, right):
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
# SPLIT SETTLEMENT MATCHING
# ============================================================

def split_settlement_match(
    settlements,
    bank,
    exact_matches,
):
    """
    Match one settlement against multiple bank credits.

    Conditions:
        - settlement was not matched exactly
        - same UTR
        - at least two bank transactions
        - each bank date is within the date tolerance
        - combined bank credits equal settlement amount
    """

    exact_settlements = set(
        exact_matches["settlement_id"]
    )

    exact_bank = set(
        exact_matches["bank_transaction_id"]
    )

    unresolved = settlements[
        ~settlements["settlement_id"].isin(
            exact_settlements
        )
    ]

    available_bank = bank[
        ~bank["bank_transaction_id"].isin(
            exact_bank
        )
    ]

    matches = []

    for _, settlement in unresolved.iterrows():

        utr = str(
            settlement["utr"]
        ).strip()

        # Split matching requires a UTR.
        if not utr or utr == "nan":
            continue

        candidates = available_bank[
            available_bank["utr"]
            .fillna("")
            .astype(str)
            .str.strip()
            == utr
        ].copy()

        if len(candidates) < 2:
            continue

        # Keep only bank transactions close enough in date.
        valid = []

        for _, transaction in candidates.iterrows():

            date_difference = date_difference_days(
                settlement["settlement_date"],
                transaction["transaction_date"],
            )

            if date_difference <= DATE_TOLERANCE_DAYS:
                valid.append(transaction)

        if len(valid) < 2:
            continue

        valid = pd.DataFrame(valid)

        total_credit = round(
            valid["credit"].astype(float).sum(),
            2,
        )

        amount_difference = round(
            abs(
                float(settlement["amount"])
                - total_credit
            ),
            2,
        )

        # Combined amount must match.
        if amount_difference > AMOUNT_TOLERANCE:
            continue

        bank_ids = sorted(
            valid["bank_transaction_id"]
            .astype(str)
            .tolist()
        )

        matches.append(
            {
                "settlement_id": settlement[
                    "settlement_id"
                ],
                "bank_transaction_id": "|".join(
                    bank_ids
                ),
                "match_type": "split_settlement",
                "amount_difference": amount_difference,
                "date_difference_days": max(
                    date_difference_days(
                    settlement["settlement_date"],
                    transaction_date,
                )
                    for transaction_date in valid[
                        "transaction_date"
                    ]
                ),
                "narration_similarity": 1.0,
                "is_match": True,
            }
        )

    return pd.DataFrame(matches)


# ============================================================
# ONE-TO-ONE TOLERANCE MATCHING
# ============================================================

def tolerance_match(
    settlements,
    bank,
    exact_matches,
    split_matches,
):
    """
    Match only settlements that exact matching and
    split-settlement matching could not resolve.
    """

    exact_settlements = set(
        exact_matches["settlement_id"]
    )

    exact_bank = set(
        exact_matches["bank_transaction_id"]
    )

    split_settlements = set()
    split_bank = set()

    if not split_matches.empty:

        split_settlements = set(
            split_matches["settlement_id"]
        )

        for value in split_matches[
            "bank_transaction_id"
        ]:
            split_bank.update(
                str(value).split("|")
            )

    resolved_settlements = (
        exact_settlements
        | split_settlements
    )

    resolved_bank = (
        exact_bank
        | split_bank
    )

    unresolved = settlements[
        ~settlements["settlement_id"].isin(
            resolved_settlements
        )
    ]

    available_bank = bank[
        ~bank["bank_transaction_id"].isin(
            resolved_bank
        )
    ]

    matches = []

    for _, settlement in unresolved.iterrows():

        settlement_amount = float(
            settlement["amount"]
        )

        candidates = []

        for _, transaction in available_bank.iterrows():

            bank_amount = float(
                transaction["credit"]
            )

            amount_difference = abs(
                settlement_amount
                - bank_amount
            )

            if amount_difference > AMOUNT_TOLERANCE:
                continue

            date_difference = date_difference_days(
                settlement["settlement_date"],
                transaction["transaction_date"],
            )

            if date_difference > DATE_TOLERANCE_DAYS:
                continue

            similarity = narration_similarity(
                settlement["utr"],
                transaction["description"],
            )

            candidates.append(
                {
                    "settlement_id": settlement[
                        "settlement_id"
                    ],
                    "bank_transaction_id": transaction[
                        "bank_transaction_id"
                    ],
                    "amount_difference": round(
                        amount_difference,
                        2,
                    ),
                    "date_difference_days": date_difference,
                    "narration_similarity": round(
                        similarity,
                        4,
                    ),
                }
            )

        if not candidates:
            continue

        candidates.sort(
            key=lambda x: (
                x["amount_difference"],
                x["date_difference_days"],
                -x["narration_similarity"],
            )
        )

        best = candidates[0]

        utr = str(
            settlement["utr"]
        ).strip()

        if utr and utr != "nan":

            if (
                best["narration_similarity"]
                < MIN_NARRATION_SIMILARITY
            ):
                continue

        if len(candidates) > 1:

            second = candidates[1]

            same_amount = (
                best["amount_difference"]
                == second["amount_difference"]
            )

            same_date = (
                best["date_difference_days"]
                == second["date_difference_days"]
            )

            if same_amount and same_date:
                continue

        matches.append(
            {
                "settlement_id": best[
                    "settlement_id"
                ],
                "bank_transaction_id": best[
                    "bank_transaction_id"
                ],
                "match_type": "tolerance",
                "amount_difference": best[
                    "amount_difference"
                ],
                "date_difference_days": best[
                    "date_difference_days"
                ],
                "narration_similarity": best[
                    "narration_similarity"
                ],
                "is_match": True,
            }
        )

    return pd.DataFrame(matches)

# ============================================================
# MAIN
# ============================================================

def main():

    settlements, bank, exact_matches = load_data()

    # First resolve split settlements.
    split_matches = split_settlement_match(
        settlements,
        bank,
        exact_matches,
    )

    # Then perform normal one-to-one tolerance matching
    # on everything still unresolved.
    tolerance_matches = tolerance_match(
        settlements,
        bank,
        exact_matches,
        split_matches,
    )

    if split_matches.empty and tolerance_matches.empty:

        all_matches = pd.DataFrame(
            columns=[
                "settlement_id",
                "bank_transaction_id",
                "match_type",
                "amount_difference",
                "date_difference_days",
                "narration_similarity",
                "is_match",
            ]
        )

    else:

        all_matches = pd.concat(
            [
                split_matches,
                tolerance_matches,
            ],
            ignore_index=True,
        )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        RESULTS_DIR / "tolerance_matches.csv"
    )

    all_matches.to_csv(
        output_path,
        index=False,
    )

    print("=" * 60)
    print("LEDGER - TOLERANCE MATCHING")
    print("=" * 60)

    print(
        f"Total settlements: "
        f"{len(settlements)}"
    )

    print(
        f"Exact matches: "
        f"{len(exact_matches)}"
    )

    print(
        f"Unresolved after exact: "
        f"{len(settlements) - len(exact_matches)}"
    )

    print(
        f"Split-settlement matches: "
        f"{len(split_matches)}"
    )

    print(
        f"One-to-one tolerance matches: "
        f"{len(tolerance_matches)}"
    )

    print(
        f"Total tolerance-stage matches: "
        f"{len(all_matches)}"
    )

    print(
        f"Still unresolved: "
        f"{len(settlements) - len(exact_matches) - len(all_matches)}"
    )

    print(
        f"Saved: {output_path}"
    )

if __name__ == "__main__":
    main()