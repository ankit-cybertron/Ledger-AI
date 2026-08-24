from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIR = ROOT / "data" / "results"

RECONCILIATION_PATH = (
    RESULTS_DIR / "reconciliation_results.csv"
)

EXCEPTION_PATH = (
    RESULTS_DIR / "exception_ledger.csv"
)

OUTPUT_PATH = (
    RESULTS_DIR / "reconciliation_report.md"
)


def load_data():

    if not RECONCILIATION_PATH.exists():
        raise FileNotFoundError(
            f"Missing: {RECONCILIATION_PATH}\n"
            "Run the reconciler first."
        )

    if not EXCEPTION_PATH.exists():
        raise FileNotFoundError(
            f"Missing: {EXCEPTION_PATH}\n"
            "Run the exception ledger first."
        )

    reconciliation = pd.read_csv(
        RECONCILIATION_PATH
    )

    exceptions = pd.read_csv(
        EXCEPTION_PATH
    )

    return reconciliation, exceptions


def get_settlement_outcomes(
    reconciliation,
):

    grouped = (
        reconciliation
        .groupby("settlement_id")["status"]
        .agg(set)
    )

    outcomes = {}

    for settlement_id, statuses in grouped.items():

        if "matched" in statuses:
            outcomes[settlement_id] = "matched"

        elif "manual_review" in statuses:
            outcomes[settlement_id] = "manual_review"

        else:
            outcomes[settlement_id] = "unmatched"

    return pd.Series(
        outcomes,
        name="settlement_status",
    )


def build_report(
    reconciliation,
    exceptions,
):

    settlement_outcomes = (
        get_settlement_outcomes(
            reconciliation
        )
    )

    total = len(
        settlement_outcomes
    )

    matched = int(
        (
            settlement_outcomes
            == "matched"
        ).sum()
    )

    review = int(
        (
            settlement_outcomes
            == "manual_review"
        ).sum()
    )

    unmatched = int(
        (
            settlement_outcomes
            == "unmatched"
        ).sum()
    )

    match_rate = (
        matched / total
        if total
        else 0
    )

    relationship_count = len(
        reconciliation
    )

    exact = int(
        (
            reconciliation["stage"]
            == "exact"
        ).sum()
    )

    tolerance = int(
        (
            reconciliation["stage"]
            == "tolerance"
        ).sum()
    )

    llm = int(
        (
            reconciliation["stage"]
            == "llm"
        ).sum()
    )

    reconciler = int(
        (
            reconciliation["stage"]
            == "reconciler"
        ).sum()
    )

    total_exceptions = len(
        exceptions
    )

    if exceptions.empty:

        open_exceptions = 0
        high_priority = 0
        exception_types = {}

    else:

        open_exceptions = int(
            (
                exceptions[
                    "resolution_status"
                ]
                == "open"
            ).sum()
        )

        high_priority = int(
            (
                exceptions[
                    "priority"
                ]
                == "high"
            ).sum()
        )

        exception_types = (
            exceptions[
                "exception_type"
            ]
            .value_counts()
            .to_dict()
        )

    accounted_for = (
        matched
        + review
        + unmatched
    )

    integrity_pass = (
        accounted_for == total
    )

    lines = []

    lines.append(
        "# Ledger Reconciliation Report"
    )

    lines.append("")

    lines.append(
        "> Settlement reconciliation, "
        "matching-stage results, and "
        "exception audit."
    )

    lines.append("")

    lines.append(
        "## Executive Summary"
    )

    lines.append("")

    lines.append(
        f"| Metric | Value |"
    )

    lines.append(
        f"|---|---:|"
    )

    lines.append(
        f"| Settlements processed | {total} |"
    )

    lines.append(
        f"| Matched | {matched} |"
    )

    lines.append(
        f"| Manual review | {review} |"
    )

    lines.append(
        f"| Unmatched | {unmatched} |"
    )

    lines.append(
        f"| Match rate | {match_rate:.2%} |"
    )

    lines.append("")

    lines.append(
        "## Settlement Outcomes"
    )

    lines.append("")

    lines.append(
        "| Outcome | Count |"
    )

    lines.append(
        "|---|---:|"
    )

    lines.append(
        f"| Matched | {matched} |"
    )

    lines.append(
        f"| Manual review | {review} |"
    )

    lines.append(
        f"| Unmatched | {unmatched} |"
    )

    lines.append("")

    lines.append(
        "## Reconciliation Stages"
    )

    lines.append("")

    lines.append(
        "Relationship records can exceed the "
        "number of settlements because a single "
        "settlement may map to multiple bank "
        "transactions, such as a split settlement."
    )

    lines.append("")

    lines.append(
        "| Stage | Relationship records |"
    )

    lines.append(
        "|---|---:|"
    )

    lines.append(
        f"| Exact | {exact} |"
    )

    lines.append(
        f"| Tolerance / split | {tolerance} |"
    )

    lines.append(
        f"| LLM-assisted | {llm} |"
    )

    lines.append(
        f"| Reconciler | {reconciler} |"
    )

    lines.append(
        f"| **Total** | **{relationship_count}** |"
    )

    lines.append("")

    lines.append(
        "## Exception Summary"
    )

    lines.append("")

    lines.append(
        f"- Total exceptions: **{total_exceptions}**"
    )

    lines.append(
        f"- Open exceptions: **{open_exceptions}**"
    )

    lines.append(
        f"- High-priority exceptions: "
        f"**{high_priority}**"
    )

    lines.append("")

    if exception_types:

        lines.append(
            "| Exception type | Count |"
        )

        lines.append(
            "|---|---:|"
        )

        for name, count in (
            exception_types.items()
        ):

            lines.append(
                f"| {name} | {count} |"
            )

        lines.append("")

    lines.append(
        "## Open Exceptions"
    )

    lines.append("")

    if exceptions.empty:

        lines.append(
            "No open exceptions."
        )

    else:

        lines.append(
            "| ID | Settlement | Bank transaction | "
            "Type | Priority | Confidence | Status |"
        )

        lines.append(
            "|---|---|---|---|---|---:|---|"
        )

        for _, row in exceptions.iterrows():

            bank_transaction_id = row[
                "bank_transaction_id"
            ]

            if pd.isna(bank_transaction_id):
                bank_transaction_id = "N/A"
            else:
                bank_transaction_id = str(
                    bank_transaction_id
                )

            lines.append(
                f"| {row['exception_id']} "
                f"| {row['settlement_id']} "
                f"| {bank_transaction_id} "
                f"| {row['exception_type']} "
                f"| {row['priority']} "
                f"| {row['confidence']:.4f} "
                f"| {row['resolution_status']} |"
            )
    lines.append("")

    lines.append(
        "## Exception Details"
    )

    lines.append("")

    if exceptions.empty:

        lines.append(
            "No exception details available."
        )

    else:

        for _, row in (
            exceptions.iterrows()
        ):

            lines.append(
                f"### {row['exception_id']}"
            )

            lines.append("")

            lines.append(
                f"- **Settlement:** "
                f"`{row['settlement_id']}`"
            )

            bank_transaction_id = row[
                "bank_transaction_id"
            ]

            if pd.isna(bank_transaction_id):
                bank_transaction_id = "N/A"
            else:
                bank_transaction_id = str(
                    bank_transaction_id
                )

            lines.append(
                f"- **Bank transaction:** "
                f"`{bank_transaction_id}`"
            )
                

            lines.append(
                f"- **Stage:** "
                f"`{row['stage']}`"
            )

            lines.append(
                f"- **Decision:** "
                f"`{row['decision']}`"
            )

            lines.append(
                f"- **Confidence:** "
                f"`{row['confidence']:.4f}`"
            )

            lines.append(
                f"- **Exception type:** "
                f"`{row['exception_type']}`"
            )

            lines.append(
                f"- **Priority:** "
                f"`{row['priority']}`"
            )

            lines.append(
                f"- **Status:** "
                f"`{row['resolution_status']}`"
            )

            lines.append("")

            lines.append(
                f"**Reason:** {row['reason']}"
            )

            lines.append("")

    lines.append(
        "## Integrity Check"
    )

    lines.append("")

    lines.append(
        f"- Matched: **{matched}**"
    )

    lines.append(
        f"- Manual review: **{review}**"
    )

    lines.append(
        f"- Unmatched: **{unmatched}**"
    )

    lines.append(
        f"- Accounted settlements: "
        f"**{accounted_for}/{total}**"
    )

    if integrity_pass:

        lines.append(
            "- Result: **PASS**"
        )

    else:

        lines.append(
            "- Result: **FAIL**"
        )

    lines.append("")

    lines.append(
        "## Pipeline"
    )

    lines.append("")

    lines.append(
        "```text"
    )

    lines.append(
        "Data"
    )

    lines.append(
        "  -> Exact Matching"
    )

    lines.append(
        "  -> Tolerance / Split Matching"
    )

    lines.append(
        "  -> ML Confidence"
    )

    lines.append(
        "  -> LLM Ambiguous Matching"
    )

    lines.append(
        "  -> Reconciler"
    )

    lines.append(
        "  -> Exception Ledger"
    )

    lines.append(
        "```"
    )

    lines.append("")

    lines.append(
        "---"
    )

    lines.append(
        "Generated by Ledger."
    )

    return "\n".join(lines)


def main():

    reconciliation, exceptions = (
        load_data()
    )

    report = build_report(
        reconciliation,
        exceptions,
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        report,
        encoding="utf-8",
    )

    print(report)

    print()
    print(
        f"Saved: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()