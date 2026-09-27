"""Deterministic synthetic generator for banking data.

Generates:
- 300 customers (100 es, 100 pt, 100 en) including the 9 scenario fixtures
- 1-2 accounts per customer (COP for es, BRL for pt, USD for en)
- 1-3 cards per account
- ~15,000 transactions over the last 120 days
- Outputs raw JSONL files into data/raw/synthetic/
"""

import json
import random
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

from faker import Faker

from banking_core.models.enums import BlockReason, DocumentType
from banking_core.seed.fixtures import create_scenario_fixtures

MCC_CODES = [
    ("5411", "Grocery Stores, Supermarkets"),
    ("5812", "Eating Places, Restaurants"),
    ("5814", "Fast Food Restaurants"),
    ("5541", "Service Stations, Gas"),
    ("5311", "Department Stores"),
    ("4121", "Taxicabs and Limousines, Ride Share"),
    ("5912", "Drug Stores and Pharmacies"),
    ("5732", "Electronic Sales"),
    ("5651", "Family Clothing Stores"),
    ("5999", "Miscellaneous and Specialty Retail"),
]

MERCHANTS_BY_LOCALE = {
    "es": [
        "Éxito Supermercado",
        "Carulla FreshMarket",
        "D1 Tiendas",
        "Juan Valdez Café",
        "Crepes & Waffles",
        "Farmatodo",
        "Estación Terpel",
        "Uber Colombia",
        "Rappi Servicios",
        "Homecenter",
        "Falabella",
        "Cine Colombia",
    ],
    "pt": [
        "Pão de Açúcar",
        "Carrefour Express",
        "Padaria São Bento",
        "Outback Steakhouse",
        "Droga Raia",
        "Posto Ipiranga",
        "Uber Brasil",
        "iFood Delivery",
        "Magazine Luiza",
        "Lojas Americanas",
        "Smart Fit",
        "Cinemark",
    ],
    "en": [
        "Whole Foods Market",
        "Trader Joe's",
        "Starbucks Coffee",
        "Chipotle Mexican Grill",
        "Walgreens Pharmacy",
        "Chevron Gas Station",
        "Uber Rides",
        "DoorDash Delivery",
        "Target Store",
        "Best Buy Electronics",
        "Home Depot",
        "AMC Theatres",
    ],
}


def _clean_slug(name: str) -> str:
    """Convert name to an email-safe ASCII slug."""
    clean = re.sub(r"[^a-zA-Z0-9]", ".", name.strip().lower())
    clean = re.sub(r"\.+", ".", clean).strip(".")
    return clean or "user"


def generate_synthetic_dataset(
    output_dir: Path | str,
    seed: int = 42,
    base_time: datetime | None = None,
) -> dict[str, int]:
    """Generate deterministic synthetic banking dataset and save as JSONL files."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    now = base_time or datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)

    fakers = {
        "es": Faker("es_CO"),
        "pt": Faker("pt_BR"),
        "en": Faker("en_US"),
    }
    for f in fakers.values():
        f.seed_instance(seed)

    # 1. Load predefined scenario fixtures
    fixture_bundle = create_scenario_fixtures(base_time=now)
    customers = list(fixture_bundle.customers)
    accounts = list(fixture_bundle.accounts)
    cards = list(fixture_bundle.cards)
    transactions = list(fixture_bundle.transactions)

    # Track used IDs and documents to enforce absolute uniqueness
    used_customer_ids = {c["id"] for c in customers}
    used_doc_keys = {(c["document_type"], c["document_number"]) for c in customers}
    used_account_ids = {a["id"] for a in accounts}
    used_card_ids = {cd["id"] for cd in cards}
    used_card_refs = {cd["card_ref"] for cd in cards}
    used_tx_ids = {tx["id"] for tx in transactions}

    # 2. Generate remaining 97 customers per locale (100 per locale = 300 total)
    locales = [("es", "COP", "+57"), ("pt", "BRL", "+55"), ("en", "USD", "+1")]

    for locale, currency, phone_prefix in locales:
        faker = fakers[locale]
        for i in range(4, 101):
            c_uuid = uuid5(NAMESPACE_DNS, f"synthetic-customer-{locale}-{i}-{seed}")
            used_customer_ids.add(str(c_uuid))

            # Pick document type and unique document number
            doc_type_roll = rng.random()
            if doc_type_roll < 0.85:
                doc_type = DocumentType.NATIONAL_ID
                # 8 to 10 digits
                doc_number = str(rng.randint(10000000, 999999999))
            elif doc_type_roll < 0.90:
                doc_type = DocumentType.PASSPORT
                doc_number = f"P{rng.randint(1000000, 9999999)}"
            elif doc_type_roll < 0.95:
                doc_type = DocumentType.FOREIGN_ID
                doc_number = f"E{rng.randint(1000000, 9999999)}"
            else:
                doc_type = DocumentType.TAX_ID
                doc_number = str(rng.randint(100000000, 999999999))

            while (doc_type.value, doc_number) in used_doc_keys:
                doc_number = (
                    str(int(doc_number) + 1)
                    if doc_number.isdigit()
                    else f"P{rng.randint(1000000, 9999999)}"
                )
            used_doc_keys.add((doc_type.value, doc_number))

            first_name = faker.first_name()
            last_name = faker.last_name()
            full_name = f"{first_name} {last_name}"
            email_slug = f"{_clean_slug(first_name)}.{_clean_slug(last_name)}.{i}"
            email = f"{email_slug}@example.com"

            if locale == "es":
                phone = f"{phone_prefix}3{rng.randint(100000000, 999999999)}"[:13]
            elif locale == "pt":
                phone = f"{phone_prefix}119{rng.randint(10000000, 99999999)}"
            else:
                phone = f"{phone_prefix}555{rng.randint(1000000, 9999999)}"

            birth_year = rng.randint(1960, 2004)
            birth_month = rng.randint(1, 12)
            birth_day = rng.randint(1, 28)
            birth_date_val = date(birth_year, birth_month, birth_day).isoformat()

            created_days_ago = rng.randint(125, 365)
            created_at = (
                now - timedelta(days=created_days_ago, minutes=rng.randint(0, 1440))
            ).isoformat()
            otp_channel = "sms" if rng.random() < 0.75 else "email"

            customers.append(
                {
                    "id": str(c_uuid),
                    "document_type": doc_type.value,
                    "document_number": doc_number,
                    "full_name": full_name,
                    "email": email,
                    "phone": phone,
                    "birth_date": birth_date_val,
                    "preferred_locale": locale,
                    "registered_otp_channel": otp_channel,
                    "created_at": created_at,
                }
            )

            # 3. Accounts for this customer (1 or 2)
            num_accounts = 2 if rng.random() < 0.35 else 1
            customer_accounts = []

            for acc_idx in range(num_accounts):
                acc_type = "CHECKING" if acc_idx == 0 else "SAVINGS"
                acc_uuid = uuid5(NAMESPACE_DNS, f"synthetic-acc-{c_uuid}-{acc_idx}")
                used_account_ids.add(str(acc_uuid))

                if currency == "COP":
                    balance = rng.randint(5000000, 250000000)  # 50,000 to 2,500,000 COP
                elif currency == "BRL":
                    balance = rng.randint(20000, 1500000)  # 200 to 15,000 BRL
                else:
                    balance = rng.randint(50000, 2500000)  # 500 to 25,000 USD

                acc_dict = {
                    "id": str(acc_uuid),
                    "customer_id": str(c_uuid),
                    "type": acc_type,
                    "currency": currency,
                    "available_balance_minor": balance,
                    "ledger_balance_minor": balance,
                    "status": "ACTIVE",
                }
                accounts.append(acc_dict)
                customer_accounts.append(acc_dict)

                # 4. Cards for this account (1 to 3)
                num_cards = rng.choice([1, 1, 2, 3])
                for card_idx in range(num_cards):
                    card_uuid = uuid5(
                        NAMESPACE_DNS, f"synthetic-card-{acc_uuid}-{card_idx}"
                    )
                    used_card_ids.add(str(card_uuid))

                    card_ref = f"card_{locale}_{i}_{acc_idx}_{card_idx}"
                    while card_ref in used_card_refs:
                        card_ref = f"card_{uuid5(NAMESPACE_DNS, card_ref).hex[:12]}"
                    used_card_refs.add(card_ref)

                    prefix_bin = rng.choice(["4532", "5412", "3782"])
                    rand_middle = f"{rng.randint(10000000, 99999999):08d}"
                    pan_last4 = f"{rng.randint(1000, 9999):04d}"
                    pan = f"{prefix_bin}{rand_middle}{pan_last4}"

                    brand = (
                        "VISA"
                        if prefix_bin == "4532"
                        else ("MASTERCARD" if prefix_bin == "5412" else "AMEX")
                    )

                    is_blocked = rng.random() < 0.02
                    status = "BLOCKED" if is_blocked else "ACTIVE"
                    blocked_at = (
                        (now - timedelta(days=rng.randint(1, 30))).isoformat()
                        if is_blocked
                        else None
                    )
                    blocked_reason = (
                        rng.choice(
                            [
                                BlockReason.LOST.value,
                                BlockReason.STOLEN.value,
                                BlockReason.SUSPICIOUS_ACTIVITY.value,
                            ]
                        )
                        if is_blocked
                        else None
                    )

                    card_dict = {
                        "id": str(card_uuid),
                        "account_id": str(acc_uuid),
                        "card_ref": card_ref,
                        "pan": pan,
                        "pan_last4": pan_last4,
                        "brand": brand,
                        "status": status,
                        "blocked_at": blocked_at,
                        "blocked_reason": blocked_reason,
                    }
                    cards.append(card_dict)

    # 5. Generate ~15,000 transactions over the last 120 days across all accounts
    # 300 customers * ~50 transactions = ~15,000 transactions
    # Build lookup of account -> list of cards
    cards_by_account: dict[str, list[dict]] = {}
    for cd in cards:
        cards_by_account.setdefault(cd["account_id"], []).append(cd)

    merchants_pool = MERCHANTS_BY_LOCALE
    tx_count_target = 15000
    # Average per customer to hit exactly ~15k
    tx_per_customer = (tx_count_target - len(transactions)) // len(customers)

    for c in customers:
        # Get customer accounts
        c_accs = [a for a in accounts if a["customer_id"] == c["id"]]
        if not c_accs:
            continue

        c_locale = c["preferred_locale"]
        locale_merchants = merchants_pool.get(c_locale, merchants_pool["es"])

        # Determine number of transactions for this customer
        n_tx = rng.randint(tx_per_customer - 3, tx_per_customer + 3)
        for tx_idx in range(n_tx):
            acc = rng.choice(c_accs)
            acc_id = acc["id"]
            curr = acc["currency"]
            acc_cards = cards_by_account.get(acc_id, [])

            # 90% card-based, 10% direct account transfer
            use_card = len(acc_cards) > 0 and rng.random() < 0.90
            card_id = rng.choice(acc_cards)["id"] if use_card else None

            # Transaction occurrence: past 120 days
            days_ago = rng.randint(0, 119)
            hours_ago = rng.randint(0, 23)
            mins_ago = rng.randint(0, 59)
            occurred_at = (
                now - timedelta(days=days_ago, hours=hours_ago, minutes=mins_ago)
            ).isoformat()

            # Amount in minor units
            if curr == "COP":
                amount = rng.randint(500000, 45000000)  # 5,000 to 450,000 COP
            elif curr == "BRL":
                amount = rng.randint(1000, 120000)  # 10 to 1,200 BRL
            else:
                amount = rng.randint(250, 40000)  # 2.50 to 400.00 USD

            merchant = rng.choice(locale_merchants)
            mcc, _ = rng.choice(MCC_CODES)

            # Dispute eligibility: card transactions in last 90 days (15% prob)
            dispute_eligible = bool(card_id and days_ago <= 90 and rng.random() < 0.15)
            status = "SETTLED" if days_ago > 1 or rng.random() < 0.85 else "PENDING"

            tx_uuid = uuid5(
                NAMESPACE_DNS,
                f"synthetic-tx-{acc_id}-{days_ago}-{hours_ago}-{mins_ago}-{tx_idx}",
            )
            if str(tx_uuid) in used_tx_ids:
                tx_uuid = uuid5(
                    NAMESPACE_DNS, f"{tx_uuid}-unique-{rng.randint(1000, 9999)}"
                )
            used_tx_ids.add(str(tx_uuid))

            transactions.append(
                {
                    "id": str(tx_uuid),
                    "account_id": acc_id,
                    "card_id": card_id,
                    "amount_minor": amount,
                    "currency": curr,
                    "merchant": merchant,
                    "mcc": mcc,
                    "occurred_at": occurred_at,
                    "status": status,
                    "dispute_eligible": dispute_eligible,
                }
            )

    # 6. Write JSONL files
    files_data = [
        ("customers.jsonl", customers),
        ("accounts.jsonl", accounts),
        ("cards.jsonl", cards),
        ("transactions.jsonl", transactions),
    ]

    counts: dict[str, int] = {}
    for filename, record_list in files_data:
        file_path = out_path / filename
        with open(file_path, "w", encoding="utf-8") as f:
            for item in record_list:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        counts[filename] = len(record_list)

    return counts
