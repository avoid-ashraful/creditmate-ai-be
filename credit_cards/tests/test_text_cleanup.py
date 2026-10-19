"""Guard reviewed fixture wording, numeric facts and extraction instructions."""

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from banks.services.prompt_templates import BANK_TEMPLATES, BankSpecificPrompts
from scripts.apply_text_cleanup import apply_cleanup, field_parent

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "credit_cards/fixtures/verified_cards_2026-10-18.json"
CLEANUP = ROOT / "credit_cards/fixtures/text_cleanup_2026-10-19.json"
CARDS = json.loads(FIXTURE.read_text(encoding="utf-8"))
ENTRIES = json.loads(CLEANUP.read_text(encoding="utf-8"))
ORIGINAL_SHA256 = "6a4b5db8a9aa58ec052bfaa63d0c0900dc3ef0c911fd44e84f568b5e07cb9226"
NON_DISPLAY_FIELDS = {
    "source_url",
    "reward_source_url",
    "apply_url",
    "verified_at",
    "verification_status",
    "card_network",
}

# Only these exact neutral customer cautions may mention published sources.
CUSTOMER_CAUTIONS = (
    "Check with the bank: published sources differ.",
    "Check with the bank: published sources differ on how the fee is calculated.",
)
PROVENANCE_PATTERNS = (
    r"\b(?:SoC|PDF|brochure|schedule of charges|footnotes?|notes?)\b",
    r"\b(?:product[- ]page|web[- ]page|website|FAQ)\b",
    r"\b(?:columns?|rows?|tables?|cells?)\b",
    r"\b(?:sources?|verifier|analyst|GT|ground[- ]truth|confidence)\b",
    r"\b(?:images?|posters?|OCR|inferred|inference|unresolved|cut[- ]off)\b",
    r"\b(?:copied from|page also|silent on|read from|digit read|merged across)\b",
    r"\b(?:inconsistent|inconsistency|per SoC|VAT-inclusive per)\b",
    r"\b(?:listed under|no [^.;]* visits (?:listed|stated)|as shown)\b",
    r"\b(?:features? (?:document|sheet)|document|page)\b",
    r"\((?:see|ref\.?|as per|according to|p\.?\s*\d)\b",
    r"\[\d+(?:[-, ]+\d+)*\]",
    r"\*(?=[.;]|$)",
)
PROVENANCE = re.compile("|".join(PROVENANCE_PATTERNS), re.IGNORECASE)
NUMBER = r"\d+(?:,\d+)*(?:\.\d+)?"
# Keep literal numeric formatting, currency, percentage, ordinals, multipliers,
# and adjacent units. Count bare numbers too: ages, ranges and phone numbers
# must survive even when no currency/unit is attached.
NUMERIC_FACT = re.compile(
    rf"(?:(?:US\$|USD|BDT|TK\.?|৳|\$)\s*)?{NUMBER}"
    r"(?:st\b|nd\b|rd\b|th\b|[xX]\b|\s*%|\s*\$)?"
    r"(?:\+)?"
    r"(?:\s+(?:BDT|USD|points?|visits?|guests?|companions?|children|lounges?|"
    r"lakh|lacs?|transactions?|purchases?|persons?|months?|years?|days?|"
    r"times?|cards?)\b)?",
    re.IGNORECASE,
)
REFERENCE_NUMBERS = re.compile(r"\bnotes? (\d+(?:-\d+)?)|\bp\.(\d+)", re.I)


def numeric_facts(text):
    """Return the multiset of literal numeric facts with their adjacent units.

    Parameters
    ----------
    text : str
        Original or cleaned customer-facing text.

    Returns
    -------
    collections.Counter
        Numeric tokens, normalized only for whitespace and letter case.
    """
    return Counter(
        " ".join(match.split()).lower() for match in NUMERIC_FACT.findall(text)
    )


def text_values(value, path=""):
    """Yield nested user-facing strings and their paths.

    Parameters
    ----------
    value : object
        Fixture field, including nested lists or dictionaries.
    path : str, optional
        Current field path used in assertion failures.

    Yields
    ------
    tuple
        Field path and string value.
    """
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from text_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from text_values(child, f"{path}.{index}")


@pytest.mark.parametrize(
    "entry",
    ENTRIES,
    ids=lambda entry: f"{entry['bank']}/{entry['card']}/{entry['field']}",
)
def test_cleanup_preserves_every_numeric_fact_except_allowlisted_references(entry):
    """Check amounts, units and duplicate counts against reviewed reference digits."""
    assert set(entry) == {"bank", "card", "field", "before", "after", "dropped_numbers"}
    assert entry["before"] != entry["after"]
    references = Counter(
        number
        for groups in REFERENCE_NUMBERS.findall(entry["before"])
        for group in groups
        if group
        for number in group.split("-")
    )
    dropped = Counter(entry["dropped_numbers"])
    assert not dropped - references, "Only note/page reference digits can be allowlisted"
    assert numeric_facts(entry["before"]) == numeric_facts(entry["after"]) + dropped


@pytest.mark.parametrize(
    "text, expected",
    [
        ("USD 35; BDT 35; 35%; 35 visits", ["usd 35", "bdt 35", "35%", "35 visits"]),
        ("TK. 1,500 and US$ 35", ["tk. 1,500", "us$ 35"]),
        ("3.00%; 2% p.a.; 1.5 points", ["3.00%", "2%", "1.5 points"]),
        ("1st and 2nd cards; after 12th", ["1st", "2nd cards", "12th"]),
        ("6 visits and 6 visits", ["6 visits", "6 visits"]),
        ("1,700+ lounges; 4X rewards", ["1,700+ lounges", "4x"]),
        ("500-999 points; below 12", ["500", "999 points", "12"]),
        ("750 BDT/1,875 points", ["750 bdt", "1,875 points"]),
    ],
)
def test_numeric_guard_distinguishes_currency_units_and_repeated_limits(text, expected):
    assert numeric_facts(text) == Counter(expected)


@pytest.mark.parametrize(
    "card",
    [card for card in CARDS if card["verification_status"] == "verified"],
    ids=lambda card: f"{card['bank']}/{card['name']}",
)
def test_verified_customer_text_has_no_provenance(card):
    for field, value in card.items():
        if field in NON_DISPLAY_FIELDS:
            continue
        for path, text in text_values(value, field):
            for caution in CUSTOMER_CAUTIONS:
                text = text.replace(caution, "")
            assert not PROVENANCE.search(text), (card["name"], path, text)


def test_manifest_replays_exactly_and_changes_no_unlisted_values():
    """Reconstruct the original fixture and verify complete, idempotent replay."""
    original = deepcopy(CARDS)
    indexed = {(card["bank"], card["name"]): card for card in original}
    for entry in ENTRIES:
        parent, key = field_parent(
            indexed[(entry["bank"], entry["card"])], entry["field"]
        )
        assert parent[key] == entry["after"]
        parent[key] = entry["before"]
    digest = hashlib.sha256(
        json.dumps(original, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert digest == ORIGINAL_SHA256, "Unlisted values or fixture structure changed"
    assert apply_cleanup(original, ENTRIES) == len(ENTRIES)
    assert original == CARDS
    assert apply_cleanup(original, ENTRIES) == 0
    assert original == CARDS


def test_drift_aborts_before_applying_any_replacements():
    original = deepcopy(CARDS)
    indexed = {(card["bank"], card["name"]): card for card in original}
    first, last = ENTRIES[0], ENTRIES[-1]
    parent, key = field_parent(indexed[(first["bank"], first["card"])], first["field"])
    parent[key] = first["before"]
    parent, key = field_parent(indexed[(last["bank"], last["card"])], last["field"])
    parent[key] = "Unexpected text: needs editorial review"
    unchanged = deepcopy(original)
    with pytest.raises(ValueError, match="Text differs from reviewed"):
        apply_cleanup(original, ENTRIES)
    assert original == unchanged


@pytest.mark.parametrize("bank", [*BANK_TEMPLATES, "Unknown Bank"])
def test_prompts_require_customer_terms_without_provenance(bank):
    prompt = BankSpecificPrompts().get_prompt_for_bank(bank, "Example document")
    assert "These fields are displayed verbatim to customers" in prompt
    assert "without their note numbers or citations" in prompt
    assert "Preserve every amount, currency, percentage, count, limit" in prompt
    assert "Check with the bank: published sources differ." in prompt
