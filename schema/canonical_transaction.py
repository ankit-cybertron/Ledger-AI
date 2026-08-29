"""
canonical_transaction.py

Defines the CanonicalTransaction dataclass for Ledger AI v2.
This canonical schema represents a single transaction record in a standardized format
regardless of what source file, bank, gateway, or sub-ledger it originated from.

Rule: missing field = None, never inferred.
No part of this type definition references a specific merchant, bank, or gateway name.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any


@dataclass
class CanonicalTransaction:
    """
    Canonical representation of a transaction record across all input sources.
    Missing fields must be None, never guessed or inferred during schema instantiation.
    """

    # Primary Identifier (Required)
    transaction_id: str

    # Primary & Role Attributes
    is_primary: bool = False

    # Channel Taxonomy (Extensible strings or Enums)
    channel: Optional[str] = None

    # Temporal Attributes
    transaction_date: Optional[str] = None
    value_date: Optional[str] = None
    transaction_time: Optional[str] = None

    # Financial & Monetary Amounts (Floats rounded to 2 decimal places when set)
    gross_amount: Optional[float] = None
    debit_amount: Optional[float] = None
    credit_amount: Optional[float] = None
    fee_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    net_amount: Optional[float] = None
    refund_amount: Optional[float] = None
    adjustment_amount: Optional[float] = None
    currency: Optional[str] = None
    direction: Optional[str] = None  # e.g., "CREDIT" | "DEBIT"

    # Reference & Identifier Keys
    transaction_reference: Optional[str] = None
    utr: Optional[str] = None
    rrn: Optional[str] = None
    order_id: Optional[str] = None
    settlement_id: Optional[str] = None
    gateway_reference: Optional[str] = None
    auth_code: Optional[str] = None

    # Descriptive & Counterparty Info
    description: Optional[str] = None
    customer_name: Optional[str] = None
    status: Optional[str] = None
    transaction_type: Optional[str] = None
    expected_settlement_date: Optional[str] = None
    account_identifier: Optional[str] = None

    # Provenance & Statement Attributes
    statement_id: Optional[str] = None
    primary_statement_id: Optional[str] = None
    counterpart_statement_id: Optional[str] = None
    source_name: Optional[str] = None
    source_color: Optional[str] = None
    source_file: Optional[str] = None
    source_row_number: Optional[int] = None
    source_sheet: Optional[str] = None


    # Content Hashing & Deduplication
    content_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the CanonicalTransaction instance into a clean Python dictionary.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalTransaction":
        """
        Instantiates a CanonicalTransaction from a dictionary, safely mapping
        matching fields and setting any missing fields to None.
        """
        if not data or "transaction_id" not in data or not data["transaction_id"]:
            raise ValueError("CanonicalTransaction instantiation requires a non-empty 'transaction_id'.")

        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)
