"""
normalizer.py — Ingestion Engine Stage 4 & 5 (Transaction Semantics Normalization) for Ledger AI v2.

Transforms a raw mapped row into a clean CanonicalTransaction record:
  - Preserves raw credit_amount and debit_amount evidence while computing net_amount = credit - debit.
  - General-purpose numeric parser (strips currency symbols, handles (500.00) parenthetical negative & Dr/Cr suffixes).
  - Currency inference from header suffix patterns or configurable fallback.
  - Status normalized via TransactionStatus registry (T0.2).
  - Direction inferred from credit/debit or amount sign.
  - Regex backfill for embedded identifiers (orders, UTRs) in free text.
  - Missing field = None, never inferred.
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import MatchingConfig
from schema import CanonicalTransaction, TransactionStatus, Direction
from ingestion.column_mapper import ColumnMapping

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "normalization_rules.json"


def _load_normalization_rules() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "default_currency": "INR",
        "identifier_patterns": {}
    }


def parse_numeric(val: Any) -> Optional[float]:
    """
    General-purpose locale-agnostic numeric parser.
    Handles currency symbols, thousand separators, parenthetical negatives (100.00),
    and trailing Dr/Cr sign suffixes.
    """
    if val is None:
        return None

    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None

    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()

    s_lower = s.lower()
    if s_lower.endswith(" dr") or s_lower.endswith("dr"):
        is_negative = True
        s = re.sub(r"(?i)\s*dr$", "", s).strip()
    elif s_lower.endswith(" cr") or s_lower.endswith("cr"):
        s = re.sub(r"(?i)\s*cr$", "", s).strip()

    # Clean characters keeping digits, decimal point, and minus sign
    clean = re.sub(r"[^\d.-]", "", s)
    if not clean or clean in ("-", "."):
        return None

    try:
        num = float(clean)
        if is_negative and num > 0:
            num = -num
        return round(num, 2)
    except ValueError:
        return None


def _infer_currency_from_headers(headers: List[str], default_curr: str) -> str:
    iso_codes = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "CAD", "AUD"]
    for h in headers:
        upper_h = h.upper()
        for code in iso_codes:
            if code in upper_h:
                return code
    return default_curr


def _compute_content_hash(fields_dict: Dict[str, Any]) -> str:
    """
    Computes a SHA-256 hash of key transaction attributes for deduplication.
    """
    keys = sorted(["transaction_date", "net_amount", "utr", "order_id", "description", "customer_name"])
    raw_str = "|".join(str(fields_dict.get(k) or "") for k in keys)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def normalize_row(
    raw_row: Dict[str, Any],
    mappings: List[ColumnMapping],
    provenance: Optional[Dict[str, Any]] = None,
    cfg: Optional[MatchingConfig] = None
) -> CanonicalTransaction:
    """
    Normalizes a single raw row dictionary using active column mappings into a CanonicalTransaction.
    """
    rules = _load_normalization_rules()
    default_curr = rules.get("default_currency", "INR")
    id_patterns = rules.get("identifier_patterns", {})

    mapped_vals: Dict[str, Any] = {}
    source_headers: List[str] = []

    for m in mappings:
        source_col = m.source_column
        source_headers.append(source_col)
        raw_val = raw_row.get(source_col)
        if raw_val is not None and not str(raw_val).startswith("nan"):
            mapped_vals[m.field] = raw_val

    # 1. Financial Amounts & Credit/Debit Split
    cr_amt = parse_numeric(mapped_vals.get("credit_amount"))
    dr_amt = parse_numeric(mapped_vals.get("debit_amount"))
    gross_amt = parse_numeric(mapped_vals.get("gross_amount"))
    fee_amt = parse_numeric(mapped_vals.get("fee_amount"))
    tax_amt = parse_numeric(mapped_vals.get("tax_amount"))
    raw_net = parse_numeric(mapped_vals.get("net_amount"))

    net_amt = raw_net
    if net_amt is None:
        if cr_amt is not None or dr_amt is not None:
            c = cr_amt or 0.0
            d = dr_amt or 0.0
            net_amt = round(c - d, 2)
        elif gross_amt is not None:
            fee = fee_amt or 0.0
            tax = tax_amt or 0.0
            net_amt = round(gross_amt - fee - tax, 2)

    # 2. Direction Inference
    dir_val: Optional[str] = None
    if cr_amt is not None and cr_amt > 0 and (dr_amt is None or dr_amt == 0):
        dir_val = "CREDIT"
    elif dr_amt is not None and dr_amt > 0 and (cr_amt is None or cr_amt == 0):
        dir_val = "DEBIT"
    elif net_amt is not None:
        dir_val = "CREDIT" if net_amt >= 0 else "DEBIT"

    # 3. Status Normalization
    raw_status = mapped_vals.get("status")
    norm_status = TransactionStatus.normalize(raw_status) if raw_status else None

    # 4. Reference Identifiers & Free-Text Regex Backfill
    utr_val = str(mapped_vals.get("utr")).strip() if mapped_vals.get("utr") else None
    order_val = str(mapped_vals.get("order_id")).strip() if mapped_vals.get("order_id") else None
    setl_val = str(mapped_vals.get("settlement_id")).strip() if mapped_vals.get("settlement_id") else None
    desc_val = str(mapped_vals.get("description")).strip() if mapped_vals.get("description") else None

    if desc_val:
        # Regex backfill if explicit identifiers are missing
        if not order_val and "order_id" in id_patterns:
            for pat in id_patterns["order_id"]:
                m = re.search(pat, desc_val, re.IGNORECASE)
                if m:
                    order_val = m.group(1)
                    break

        if not utr_val and "utr" in id_patterns:
            for pat in id_patterns["utr"]:
                m = re.search(pat, desc_val, re.IGNORECASE)
                if m:
                    utr_val = m.group(1)
                    break

        if not setl_val and "settlement_id" in id_patterns:
            for pat in id_patterns["settlement_id"]:
                m = re.search(pat, desc_val, re.IGNORECASE)
                if m:
                    setl_val = m.group(1)
                    break

    # 5. Currency Inference
    currency_val = str(mapped_vals.get("currency")).strip() if mapped_vals.get("currency") else None
    if not currency_val:
        currency_val = _infer_currency_from_headers(source_headers, default_curr)

    # 6. Provenance & Primary Transaction ID
    prov = provenance or {}
    src_file = prov.get("source_file") or raw_row.get("source_file")
    src_sheet = prov.get("source_sheet") or raw_row.get("source_sheet")
    src_row_num = prov.get("source_row_number") or raw_row.get("source_row_number")

    # Primary Tx ID logic: preference order -> settlement_id > utr > order_id > synthetic provenance key
    tx_id = setl_val or utr_val or order_val
    if not tx_id:
        file_slug = str(src_file).replace(" ", "_").lower() if src_file else "raw"
        tx_id = f"tx_{file_slug}_{src_row_num or 1}"

    # Build fields dict for hash computation
    hash_fields = {
        "transaction_date": mapped_vals.get("transaction_date"),
        "net_amount": net_amt,
        "utr": utr_val,
        "order_id": order_val,
        "description": desc_val,
        "customer_name": mapped_vals.get("customer_name")
    }
    content_hash = _compute_content_hash(hash_fields)

    return CanonicalTransaction(
        transaction_id=tx_id,
        source_type=prov.get("source_type"),
        channel=prov.get("channel"),
        transaction_date=str(mapped_vals.get("transaction_date")).strip() if mapped_vals.get("transaction_date") else None,
        value_date=str(mapped_vals.get("value_date")).strip() if mapped_vals.get("value_date") else None,
        gross_amount=gross_amt,
        debit_amount=dr_amt,
        credit_amount=cr_amt,
        fee_amount=fee_amt,
        tax_amount=tax_amt,
        net_amount=net_amt,
        currency=currency_val,
        direction=dir_val,
        utr=utr_val,
        order_id=order_val,
        settlement_id=setl_val,
        auth_code=str(mapped_vals.get("auth_code")).strip() if mapped_vals.get("auth_code") else None,
        description=desc_val,
        customer_name=str(mapped_vals.get("customer_name")).strip() if mapped_vals.get("customer_name") else None,
        status=norm_status,
        source_file=src_file,
        source_row_number=src_row_num,
        source_sheet=src_sheet,
        content_hash=content_hash
    )
