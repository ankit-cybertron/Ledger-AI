from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
RESULTS_DIR = ROOT / "data" / "results"


SETTLEMENTS_PATH = (
    GENERATED_DIR / "razorpay_settlements.csv"
)

GROUND_TRUTH_PATH = (
    GROUND_TRUTH_DIR / "relationships.csv"
)

RECONCILIATION_PATH = (
    RESULTS_DIR / "reconciliation_results.csv"
)

EXCEPTION_PATH = (
    RESULTS_DIR / "exception_ledger.csv"
)


def load_results():
    settlements = pd.read_csv(
        SETTLEMENTS_PATH
    )

    ground_truth = pd.read_csv(
        GROUND_TRUTH_PATH
    )

    reconciliation = pd.read_csv(
        RECONCILIATION_PATH
    )

    exceptions = pd.read_csv(
        EXCEPTION_PATH
    )

    return (
        settlements,
        ground_truth,
        reconciliation,
        exceptions,
    )


def test_settlement_count(
    settlements,
    reconciliation,
):
    expected = len(
        settlements
    )

    actual = reconciliation[
        "settlement_id"
    ].nunique()

    assert actual == expected, (
        f"Expected {expected} settlements, "
        f"got {actual}"
    )


def test_settlement_outcomes(
    reconciliation,
):
    settlement_status = (
        reconciliation
        .groupby("settlement_id")["status"]
        .agg(
            lambda values: (
                "matched"
                if "matched" in set(values)
                else (
                    "manual_review"
                    if "manual_review"
                    in set(values)
                    else "unmatched"
                )
            )
        )
    )

    matched = (
        settlement_status == "matched"
    ).sum()

    manual_review = (
        settlement_status
        == "manual_review"
    ).sum()

    unmatched = (
        settlement_status
        == "unmatched"
    ).sum()

    total = (
        matched
        + manual_review
        + unmatched
    )

    assert total == len(
        settlement_status
    )

    assert (
        matched + manual_review + unmatched
        == 226
    ), (
        "Settlement outcomes do not "
        "account for all 226 settlements"
    )


def test_orphan_settlements_are_exceptions(
    ground_truth,
    exceptions,
):
    orphan_settlements = set(
        ground_truth.loc[
            ground_truth["relationship_type"]
            == "orphan_settlement",
            "settlement_id",
        ]
    )

    exception_settlements = set(
        exceptions[
            "settlement_id"
        ]
    )

    assert orphan_settlements <= (
        exception_settlements
    ), (
        "Every orphan settlement must "
        "appear in the exception ledger"
    )


def test_exceptions_are_open(
    exceptions,
):
    assert (
        exceptions[
            "resolution_status"
        ]
        == "open"
    ).all(), (
        "New exceptions must start "
        "with open status"
    )


def test_exceptions_are_not_matched(
    exceptions,
):
    assert not (
        exceptions[
            "decision"
        ]
        == "match"
    ).any(), (
        "An exception must never be "
        "marked as a match"
    )


def test_split_settlement_relationship_exists(
    ground_truth,
    reconciliation,
):
    split = ground_truth[
        ground_truth[
            "relationship_type"
        ]
        == "split_settlement"
    ]

    if split.empty:
        return

    for _, row in split.iterrows():

        settlement_id = (
            row["settlement_id"]
        )

        bank_id = (
            row["bank_transaction_id"]
        )

        matches = reconciliation[
            (
                reconciliation[
                    "settlement_id"
                ]
                == settlement_id
            )
            &
            (
                reconciliation[
                    "bank_transaction_id"
                ]
                == bank_id
            )
        ]

        assert not matches.empty, (
            f"Split relationship missing: "
            f"{settlement_id} -> {bank_id}"
        )


def test_llm_match_preserved(
    reconciliation,
):
    llm_matches = reconciliation[
        (
            reconciliation["stage"]
            == "llm"
        )
        &
        (
            reconciliation["decision"]
            == "match"
        )
    ]

    if llm_matches.empty:
        return

    assert (
        llm_matches["status"]
        == "matched"
    ).all(), (
        "LLM match must remain "
        "matched in the reconciler"
    )


def test_no_empty_settlement_ids(
    reconciliation,
):
    assert (
        reconciliation[
            "settlement_id"
        ]
        .notna()
        .all()
    )

    assert (
        reconciliation[
            "settlement_id"
        ]
        .astype(str)
        .str.strip()
        .ne("")
        .all()
    )


def test_required_exception_columns(
    exceptions,
):
    required = {
        "exception_id",
        "created_at",
        "settlement_id",
        "bank_transaction_id",
        "stage",
        "decision",
        "confidence",
        "exception_type",
        "priority",
        "reason",
        "resolution_status",
    }

    missing = (
        required
        - set(exceptions.columns)
    )

    assert not missing, (
        f"Missing exception columns: "
        f"{sorted(missing)}"
    )


def main():

    print("=" * 60)
    print("LEDGER - PIPELINE TESTS")
    print("=" * 60)

    (
        settlements,
        ground_truth,
        reconciliation,
        exceptions,
    ) = load_results()

    tests = [
        (
            "settlement count",
            lambda: test_settlement_count(
                settlements,
                reconciliation,
            ),
        ),
        (
            "settlement outcomes",
            lambda: test_settlement_outcomes(
                reconciliation,
            ),
        ),
        (
            "orphan settlements",
            lambda: test_orphan_settlements_are_exceptions(
                ground_truth,
                exceptions,
            ),
        ),
        (
            "exception status",
            lambda: test_exceptions_are_open(
                exceptions,
            ),
        ),
        (
            "exception safety",
            lambda: test_exceptions_are_not_matched(
                exceptions,
            ),
        ),
        (
            "split settlement",
            lambda: test_split_settlement_relationship_exists(
                ground_truth,
                reconciliation,
            ),
        ),
        (
            "LLM match",
            lambda: test_llm_match_preserved(
                reconciliation,
            ),
        ),
        (
            "settlement IDs",
            lambda: test_no_empty_settlement_ids(
                reconciliation,
            ),
        ),
        (
            "exception schema",
            lambda: test_required_exception_columns(
                exceptions,
            ),
        ),
    ]

    passed = 0

    for name, test in tests:

        try:
            test()

            print(
                f"PASS  {name}"
            )

            passed += 1

        except AssertionError as error:

            print(
                f"FAIL  {name}"
            )
            print(
                f"      {error}"
            )

    print()
    print(
        f"Tests passed: "
        f"{passed}/{len(tests)}"
    )

    print("=" * 60)

    if passed != len(tests):
        raise SystemExit(1)

    # Preservation: Do not wipe active statement store on test tearDown
    # from frontend import statement_store
    # statement_store.clear_all_statements()

    print(
        "ALL PIPELINE TESTS PASSED"
    )


def tearDownModule():
    pass


if __name__ == "__main__":
    main()