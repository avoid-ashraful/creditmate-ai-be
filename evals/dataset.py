"""Golden dataset loading and product-slug helpers.

Product ids in the dataset are slugs derived from ``"<bank> <name>"`` so a
case stays stable across database rebuilds (numeric PKs do not). Both the
fixture file and a live Django catalogue can be resolved through the same
slug function.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
FIXTURE = (
    ROOT.parent / "credit_cards" / "fixtures" / "verified_cards_2026-10-18.json"
)

CASE_FIELDS = {
    "id",
    "question",
    "category",
    "expected_product_ids",
    "expected_facts",
    "required_citations",
    "forbidden_phrases",
    "relevant_chunk_ids",
}
CATEGORIES = (
    "factual",
    "comparison",
    "eligibility",
    "calculators",
    "grounding",
    "honesty-adversarial",
    "fallback",
)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def card_slug(bank: str, name: str) -> str:
    return slugify(f"{bank} {name}")


def load_cases(suite: str = "golden_v1") -> list[dict]:
    path = DATASETS / f"{suite}.jsonl"
    cases = []
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = CASE_FIELDS - case.keys()
        if missing:
            raise ValueError(f"{path}:{line_no} missing fields {sorted(missing)}")
        if case["category"] not in CATEGORIES:
            raise ValueError(f"{path}:{line_no} unknown category {case['category']}")
        cases.append(case)
    return cases


def load_fixture_cards() -> list[dict]:
    """Cards from the verified fixture, each annotated with its slug."""
    raw = json.loads(FIXTURE.read_text())
    cards = []
    for card in raw:
        item = dict(card)
        item["slug"] = card_slug(card["bank"], card["name"])
        cards.append(item)
    return cards


def load_django_cards() -> list[dict] | None:
    """Cards from a configured Django DB, or None if unavailable/empty."""
    try:
        import django

        if not django.conf.settings.configured:
            import os

            os.environ.setdefault(
                "DJANGO_SETTINGS_MODULE", "credit_mate_ai.settings"
            )
            django.setup()
        from credit_cards.models import CreditCard

        rows = list(
            CreditCard.objects.select_related("bank").values(
                "bank__name",
                "name",
                "annual_fee",
                "interest_rate_apr",
                "min_monthly_income",
            )
        )
        if not rows:
            return None
        cards = []
        for r in rows:
            cards.append(
                {
                    "bank": r["bank__name"],
                    "name": r["name"],
                    "annual_fee": (
                        float(r["annual_fee"]) if r["annual_fee"] is not None else None
                    ),
                    "interest_rate_apr": (
                        float(r["interest_rate_apr"])
                        if r["interest_rate_apr"] is not None
                        else None
                    ),
                    "min_monthly_income": (
                        float(r["min_monthly_income"])
                        if r["min_monthly_income"] is not None
                        else None
                    ),
                    "slug": card_slug(r["bank__name"], r["name"]),
                }
            )
        return cards
    except Exception:
        return None


def load_catalogue() -> tuple[list[dict], str]:
    """Prefer the live Django catalogue; fall back to the verified fixture."""
    cards = load_django_cards()
    if cards:
        return cards, "django"
    return load_fixture_cards(), "fixture"
