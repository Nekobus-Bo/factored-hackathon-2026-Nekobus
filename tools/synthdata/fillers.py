"""Deterministic fake slot fillers using reserved/test ranges.

Conforms to schema.yaml:
- email: RFC 2606 reserved domains (@example.com, @example.org, @example.net)
- phone: Reserved fictional ranges (NANPA 555-01xx, +34 600 000 xxx,
  +55 11 91234 xxxx; NO +00 prefix)
- card_number: Industry standard test PAN ranges (4242..., 4000..., 5555...)
- card_last4: 4-digit card suffix
- document_type & document_number: Realistic natural surface forms and matching
  bare local numbers without artificial prefixes.
- full_name: Fictitious locale-specific given and family names
- birth_date: Plausible date strings in ISO or regional formats
- amount: Numeric strings optionally formatted with thousands separators
- currency: ISO 4217 code or symbol (USD, EUR, BRL, COP, $, €, R$, £)
- merchant: Common merchant/vendor names
- transaction_date: Plausible dates or temporal expressions (yesterday, hoy, etc.)
- otp_code: 6-digit numeric passcodes
"""

import random

# RFC 2606 reserved domains
EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]

# Names per locale
NAMES_ES = [
    "Carlos Mendoza",
    "Lucía Fernández",
    "Mateo Ramírez",
    "Sofía Morales",
    "Alejandro Herrera",
    "Valentina Castro",
    "Diego Torres",
    "Camila Rojas",
    "Andrés Salazar",
    "Mariana Vargas",
    "Gabriel Navarro",
    "Isabella Cordero",
    "Javier Paredes",
    "Daniela Méndez",
    "Santiago Ortiz",
]

NAMES_PT = [
    "Lucas Silva",
    "Beatriz Santos",
    "Thiago Oliveira",
    "Mariana Costa",
    "Rodrigo Almeida",
    "Camila Ferreira",
    "Gabriel Souza",
    "Larissa Pereira",
    "Felipe Carvalho",
    "Juliana Ribeiro",
    "Rafael Martins",
    "Bruna Barbosa",
    "Gustavo Lima",
    "Amanda Gomes",
    "Matheus Rocha",
]

NAMES_EN = [
    "Jane Doe",
    "John Smith",
    "Alice Johnson",
    "Robert Taylor",
    "Emily Davis",
    "David Wilson",
    "Michael Brown",
    "Sarah Miller",
    "James Anderson",
    "Emma White",
    "William Martinez",
    "Olivia Jackson",
    "Thomas Clark",
    "Sophia Hall",
    "Daniel Lewis",
]

# Consistent Document Profiles (normalized enum, surface form, matching bare number)
DOCUMENT_PROFILES_ES = [
    {"normalized": "NATIONAL_ID", "surface": "cédula", "number": "1020304050"},
    {"normalized": "NATIONAL_ID", "surface": "DNI", "number": "98765432X"},
    {
        "normalized": "NATIONAL_ID",
        "surface": "cédula de ciudadanía",
        "number": "52481920",
    },
    {"normalized": "NATIONAL_ID", "surface": "CC", "number": "71234567"},
    {
        "normalized": "NATIONAL_ID",
        "surface": "documento de identidad",
        "number": "80123456",
    },
    {"normalized": "PASSPORT", "surface": "pasaporte", "number": "P9876543"},
    {"normalized": "PASSPORT", "surface": "pasaporte", "number": "A1234567"},
    {
        "normalized": "FOREIGN_ID",
        "surface": "cédula de extranjería",
        "number": "89234561",
    },
    {
        "normalized": "FOREIGN_ID",
        "surface": "carnet de extranjería",
        "number": "55443322",
    },
    {"normalized": "FOREIGN_ID", "surface": "NIE", "number": "X1234567B"},
    {"normalized": "TAX_ID", "surface": "NIT", "number": "900123456-1"},
    {"normalized": "TAX_ID", "surface": "RUT", "number": "12345678-9"},
    {"normalized": "TAX_ID", "surface": "NIF", "number": "800192837-5"},
]

DOCUMENT_PROFILES_PT = [
    {"normalized": "NATIONAL_ID", "surface": "CPF", "number": "123.456.789-00"},
    {"normalized": "NATIONAL_ID", "surface": "CPF", "number": "987.654.321-11"},
    {"normalized": "NATIONAL_ID", "surface": "CPF", "number": "456.789.012-34"},
    {"normalized": "NATIONAL_ID", "surface": "RG", "number": "12.345.678-9"},
    {"normalized": "NATIONAL_ID", "surface": "RG", "number": "23.456.789-0"},
    {"normalized": "PASSPORT", "surface": "passaporte", "number": "PA123456"},
    {"normalized": "PASSPORT", "surface": "passaporte", "number": "FB987654"},
    {"normalized": "FOREIGN_ID", "surface": "RNE", "number": "V123456-7"},
    {"normalized": "FOREIGN_ID", "surface": "CRNM", "number": "W987654-3"},
    {
        "normalized": "FOREIGN_ID",
        "surface": "registro nacional de estrangeiro",
        "number": "G554433-2",
    },
    {"normalized": "TAX_ID", "surface": "CNPJ", "number": "00.000.000/0001-91"},
    {"normalized": "TAX_ID", "surface": "CNPJ", "number": "11.222.333/0001-44"},
]

DOCUMENT_PROFILES_EN = [
    {"normalized": "NATIONAL_ID", "surface": "national ID", "number": "87654321"},
    {"normalized": "NATIONAL_ID", "surface": "ID card", "number": "987654321"},
    {"normalized": "NATIONAL_ID", "surface": "driver's license", "number": "D1234567"},
    {"normalized": "NATIONAL_ID", "surface": "state ID", "number": "45678912"},
    {"normalized": "PASSPORT", "surface": "passport", "number": "P1234567"},
    {"normalized": "PASSPORT", "surface": "passport", "number": "A9876543"},
    {"normalized": "FOREIGN_ID", "surface": "foreign ID", "number": "F87654321"},
    {
        "normalized": "FOREIGN_ID",
        "surface": "alien registration card",
        "number": "A123456789",
    },
    {"normalized": "TAX_ID", "surface": "tax ID", "number": "12-3456789"},
    {"normalized": "TAX_ID", "surface": "SSN", "number": "000-12-3456"},
    {"normalized": "TAX_ID", "surface": "SSN", "number": "000-23-4567"},
]

DOCUMENT_PROFILES = {
    "es": DOCUMENT_PROFILES_ES,
    "pt": DOCUMENT_PROFILES_PT,
    "en": DOCUMENT_PROFILES_EN,
}

# Test PAN card numbers
CARD_NUMBERS = [
    "4242 4242 4242 4242",
    "4000 1234 5678 9010",
    "5555 5555 5555 4444",
    "4111 1111 1111 1111",
    "5105 1051 0510 5100",
    "4242-4242-4242-4242",
    "4000-1234-5678-9010",
    "5555-5555-5555-4444",
]

# Last 4 digits
CARD_LAST4_LIST = [
    "4321",
    "8899",
    "1234",
    "9010",
    "5555",
    "7788",
    "3456",
    "6789",
    "2468",
    "1357",
    "9900",
    "4411",
    "2026",
    "3141",
    "5820",
]

# Birth dates
BIRTH_DATES = [
    "1985-04-12",
    "1992-11-24",
    "1978-07-08",
    "1983-09-30",
    "1995-01-19",
    "1980-12-05",
    "14/05/1987",
    "22/08/1991",
    "03/11/1984",
    "19/06/1993",
    "1989-10-15",
    "1994-03-27",
    "08/12/1982",
]

# Amounts (with and without thousands separators)
AMOUNTS = [
    "15.99",
    "25.50",
    "45.00",
    "75.25",
    "89.90",
    "120.00",
    "150.50",
    "250.00",
    "340.00",
    "500.00",
    "750.00",
    "999.00",
    "1,200.00",
    "1.500,00",
    "85.00",
    "62.30",
]

# Merchants
MERCHANTS = [
    "Amazon",
    "Uber",
    "Netflix",
    "Zara",
    "Walmart",
    "Mercado Libre",
    "Spotify",
    "Starbucks",
    "Deliveroo",
    "Target",
    "Rappi",
    "iFood",
    "Steam",
    "Airbnb",
    "Shell",
    "Carrefour",
    "Apple Store",
]

# Currencies per language
CURRENCIES_ES = ["USD", "EUR", "COP", "$", "€"]
CURRENCIES_PT = ["BRL", "USD", "EUR", "R$", "$"]
CURRENCIES_EN = ["USD", "EUR", "GBP", "$", "€", "£"]

# Transaction dates per language
DATES_ES = [
    "ayer",
    "hoy",
    "2026-09-20",
    "2026-09-22",
    "2026-09-25",
    "18/09/2026",
    "15/09/2026",
]
DATES_PT = [
    "ontem",
    "hoje",
    "2026-09-20",
    "2026-09-22",
    "2026-09-25",
    "18/09/2026",
    "15/09/2026",
]
DATES_EN = [
    "yesterday",
    "today",
    "2026-09-20",
    "2026-09-22",
    "2026-09-25",
    "18/09/2026",
    "15/09/2026",
]

# OTP codes (6 digits)
OTP_CODES = [
    "482910",
    "192837",
    "654321",
    "738192",
    "829104",
    "551203",
    "394812",
    "918273",
    "604921",
    "273849",
    "847291",
    "319482",
]


def generate_phone(lang: str, rng: random.Random) -> str:
    """Generate a realistic but reserved fictional phone number.

    Never starts with +00.
    """
    if lang == "es":
        # Spain test range +34 600 000 xxx
        suffix = rng.randint(100, 999)
        return f"+34-600-000-{suffix}"
    elif lang == "pt":
        # Brazil test fictional series +55 11 91234 xxxx
        suffix = rng.randint(1000, 9999)
        return f"+55-11-91234-{suffix}"
    else:
        # US fictional reserved range NANPA 555-01xx (+1-555-01xx)
        suffix = rng.randint(10, 99)
        return f"+1-555-01{suffix}"


def generate_email(full_name: str, rng: random.Random) -> str:
    """Generate email with RFC 2606 reserved domain."""
    clean_name = (
        full_name.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("õ", "o")
    )
    parts = clean_name.split()
    first = parts[0] if parts else "user"
    last = parts[1] if len(parts) > 1 else "test"
    domain = rng.choice(EMAIL_DOMAINS)
    return f"{first}.{last}@{domain}"


def get_fillers(lang: str, rng: random.Random) -> dict[str, str]:
    """Return a dictionary of realistic fake slot values for the given locale.

    Guarantees document_type and document_number are drawn as a consistent pair.
    """
    if lang == "es":
        name = rng.choice(NAMES_ES)
        currency = rng.choice(CURRENCIES_ES)
        tx_date = rng.choice(DATES_ES)
    elif lang == "pt":
        name = rng.choice(NAMES_PT)
        currency = rng.choice(CURRENCIES_PT)
        tx_date = rng.choice(DATES_PT)
    else:
        name = rng.choice(NAMES_EN)
        currency = rng.choice(CURRENCIES_EN)
        tx_date = rng.choice(DATES_EN)

    email = generate_email(name, rng)
    phone = generate_phone(lang, rng)

    # Consistent document profile (type + number match format perfectly)
    doc_profile = rng.choice(DOCUMENT_PROFILES[lang])

    return {
        "document_type": doc_profile["surface"],
        "document_type_normalized": doc_profile["normalized"],
        "document_number": doc_profile["number"],
        "full_name": name,
        "birth_date": rng.choice(BIRTH_DATES),
        "email": email,
        "phone": phone,
        "card_last4": rng.choice(CARD_LAST4_LIST),
        "card_number": rng.choice(CARD_NUMBERS),
        "amount": rng.choice(AMOUNTS),
        "currency": currency,
        "merchant": rng.choice(MERCHANTS),
        "transaction_date": tx_date,
        "otp_code": rng.choice(OTP_CODES),
    }
