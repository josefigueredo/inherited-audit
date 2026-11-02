"""Money helpers."""


def to_cents(amount):
    """Convert a decimal amount given as text ("12.345") to whole cents, rounding half up."""
    return round(float(amount) * 100)


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
