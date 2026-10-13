"""Load small deterministic data for the local API smoke run."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "credit_mate_ai.settings")

import django  # noqa: E402

django.setup()

from banks.models import Bank  # noqa: E402
from credit_cards.models import CreditCard  # noqa: E402


def main():
    banks = [Bank.objects.create(name=f"Smoke Bank {n}", website=f"https://bank{n}.example.test") for n in range(1, 4)]
    for i in range(12):
        CreditCard.objects.create(
            bank=banks[i % 3], name=f"Smoke Card {i + 1:02d}",
            annual_fee=[0, 250, 1200, None][i % 4],
            interest_rate_apr=[18, 24, None, 31][i % 4],
            lounge_access_international=["4 visits per year", "", "Not available"][i % 3],
            lounge_access_domestic=["", "2 visits per year", "Not available"][i % 3],
            additional_features=["smoke", f"tier-{i % 3}"],
        )
    print("Seeded 3 banks and 12 cards")


if __name__ == "__main__":
    main()
