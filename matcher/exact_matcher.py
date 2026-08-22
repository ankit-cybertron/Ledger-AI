from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
RESULTS_DIR = ROOT / "data" / "results"


def load_data():
    settlements = pd.read_csv(
        GENERATED_DIR / "razorpay_settlements.csv"
    )

    bank = pd.read_csv(
        GENERATED_DIR / "bank_statement.csv"
    )

    return settlements, bank


def exact_match(settlements, bank):
    """
    Match settlement and bank records using:
        1. Exact UTR
        2. Exact settlement amount
    """

    matches = []

    matched_bank_ids = set()

    for _, settlement in settlements.iterrows():

        settlement_utr = str(
            settlement["utr"]
        ).strip()

        settlement_amount = round(
            float(settlement["amount"]),
            2,
        )

        # Cannot perform an exact UTR match
        # when UTR is missing.
        if not settlement_utr or settlement_utr == "nan":
            continue

        candidates = bank[
            (
                bank["utr"]
                .fillna("")
                .astype(str)
                .str.strip()
                == settlement_utr
            )
            &
            (
                bank["credit"].round(2)
                == settlement_amount
            )
        ]

        # Don't reuse the same bank transaction.
        candidates = candidates[
            ~candidates["bank_transaction_id"].isin(
                matched_bank_ids
            )
        ]

        # Accept only an unambiguous match.
        if len(candidates) == 1:

            candidate = candidates.iloc[0]

            matches.append(
                {
                    "settlement_id": settlement[
                        "settlement_id"
                    ],
                    "bank_transaction_id": candidate[
                        "bank_transaction_id"
                    ],
                    "match_type": "exact_utr_amount",
                    "is_match": True,
                }
            )

            matched_bank_ids.add(
                candidate["bank_transaction_id"]
            )

    return pd.DataFrame(matches)


def main():

    settlements, bank = load_data()

    matches = exact_match(
        settlements,
        bank,
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
    