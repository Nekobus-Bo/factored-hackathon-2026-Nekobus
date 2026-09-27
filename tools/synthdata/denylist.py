"""Demo identities that must never appear in synthetic training data.

The eval scenarios and the seed fixtures use these identities; if the decision
model trains on them, the scenarios stop measuring generalization.

Sources (keep in sync; ``test_denylist_covers_seed_fixtures`` checks the seed):
- apps/banking-core/src/banking_core/seed/fixtures.py (documents and names)
- eval/scenarios/ (formatted CPF variants and accented names)
"""

DEMO_IDENTITY_DENYLIST: tuple[str, ...] = (
    # Seed fixture documents: demo, blocked card, no OTP channel (es, pt, en)
    "1020304050",
    "12345678900",
    "P12345678",
    "1020304051",
    "12345678901",
    "P12345679",
    "1020304052",
    "98765432199",
    "P12345670",
    # Formatted variants used in eval scenarios
    "123.456.789-00",
    "123.456.789-01",
    "987.654.321-99",
    # Demo customer names from the seed fixtures and scenarios
    "Carlos Gomez",
    "Carlos Gómez",
    "Mariana Silva",
    "Alice Johnson",
)


def find_denylisted(text: str) -> list[str]:
    """Return the denylisted identities contained in ``text`` (case-insensitive)."""
    folded = text.casefold()
    return [item for item in DEMO_IDENTITY_DENYLIST if item.casefold() in folded]
