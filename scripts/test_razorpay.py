import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import razorpay
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = ROOT / "data" / "raw"


def save_json(filename, data):
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DATA_DIR / filename

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    return path


def fetch_recon(key_id, key_secret):
    now = datetime.now(timezone.utc)

    url = "https://api.razorpay.com/v1/settlements/recon/combined"

    params = {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "count": 100,
        "skip": 0,
    }

    response = requests.get(
        url,
        params=params,
        auth=(key_id, key_secret),
        timeout=30,
    )

    return response.status_code, response.json()


def print_collection(label, data):
    items = data.get("items", []) if isinstance(data, dict) else []

    print(f"{label}: {len(items)}")

    for item in items[:5]:
        print(
            f"  - {item.get('id', item.get('entity_id', 'unknown'))}"
        )


def main():
    load_dotenv(ROOT / ".env")

    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise RuntimeError(
            "Missing RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET in .env"
        )

    client = razorpay.Client(
        auth=(key_id, key_secret)
    )

    print("=" * 70)
    print("LEDGER - RAZORPAY DATA DISCOVERY")
    print("=" * 70)

    # ---------------------------------------------------------
    # 1. FETCH ALL ORDERS
    # ---------------------------------------------------------

    print("\n[1] Fetching orders...")

    orders = client.order.all(
        {
            "count": 100,
            "skip": 0,
        }
    )

    orders_path = save_json(
        "razorpay_orders.json",
        orders,
    )

    print_collection(
        "Orders found",
        orders,
    )

    print(f"Saved: {orders_path}")

    # ---------------------------------------------------------
    # 2. FETCH ALL PAYMENTS
    # ---------------------------------------------------------

    print("\n[2] Fetching payments...")

    payments = client.payment.all(
        {
            "count": 100,
            "skip": 0,
        }
    )

    payments_path = save_json(
        "razorpay_payments.json",
        payments,
    )

    print_collection(
        "Payments found",
        payments,
    )

    print(f"Saved: {payments_path}")

    # ---------------------------------------------------------
    # 3. FETCH ALL REFUNDS
    # ---------------------------------------------------------

    print("\n[3] Fetching refunds...")

    refunds = client.refund.all(
        {
            "count": 100,
            "skip": 0,
        }
    )

    refunds_path = save_json(
        "razorpay_refunds.json",
        refunds,
    )

    print_collection(
        "Refunds found",
        refunds,
    )

    print(f"Saved: {refunds_path}")

    # ---------------------------------------------------------
    # 4. FETCH ALL SETTLEMENTS
    # ---------------------------------------------------------

    print("\n[4] Fetching settlements...")

    settlements = client.settlement.all(
        {
            "count": 100,
            "skip": 0,
        }
    )

    settlements_path = save_json(
        "razorpay_settlements.json",
        settlements,
    )

    print_collection(
        "Settlements found",
        settlements,
    )

    print(f"Saved: {settlements_path}")

    # ---------------------------------------------------------
    # 5. FETCH SETTLEMENT RECON
    # ---------------------------------------------------------

    print("\n[5] Fetching today's settlement reconciliation...")

    status_code, recon = fetch_recon(
        key_id,
        key_secret,
    )

    recon_path = save_json(
        "razorpay_settlement_recon.json",
        recon,
    )

    print(f"HTTP status: {status_code}")

    print_collection(
        "Recon records found",
        recon,
    )

    print(f"Saved: {recon_path}")

    if status_code >= 400:
        print(
            "Recon request returned an API error; "
            "the raw response was saved."
        )

    print("\n" + "=" * 70)
    print("DATA DISCOVERY COMPLETE")
    print("=" * 70)

    print("\nRaw Razorpay responses are in data/raw/.")


if __name__ == "__main__":
    main()