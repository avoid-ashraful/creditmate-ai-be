"""Apply the reviewed customer-facing text replacements to the card fixture.

Run ``uv run python scripts/apply_text_cleanup.py`` from the repository root.
Nested ``field`` paths use dot-separated dictionary keys and list indices.
Already-applied entries are skipped; unexpected text aborts without writing.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "credit_cards/fixtures/verified_cards_2026-10-18.json"
CLEANUP = ROOT / "credit_cards/fixtures/text_cleanup_2026-10-19.json"


def field_parent(card, field):
    """Resolve the container and key for a nested text field.

    Parameters
    ----------
    card : dict
        Fixture card object.
    field : str
        Dot-separated field path, including list indices where necessary.

    Returns
    -------
    tuple
        Mutable parent container and its dictionary key or list index.
    """
    parent = card
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    return parent, key


def apply_cleanup(cards, replacements):
    """Validate and apply a cleanup manifest in memory.

    Parameters
    ----------
    cards : list of dict
        Loaded card fixture, modified only after all entries validate.
    replacements : list of dict
        Reviewed bank/card/field/before/after replacement objects.

    Returns
    -------
    int
        Number of values changed; zero when already applied.

    Raises
    ------
    ValueError
        If a card is missing, duplicated, unverified, or its text has drifted,
        or if multiple replacements target the same field.
    """
    indexed = {(card["bank"], card["name"]): card for card in cards}
    if len(indexed) != len(cards):
        raise ValueError("Duplicate bank/card identity in fixture")
    pending = []
    seen = set()
    for entry in replacements:
        identity = (entry["bank"], entry["card"])
        target = (*identity, entry["field"])
        if target in seen:
            raise ValueError(f"Duplicate cleanup target: {target}")
        seen.add(target)
        card = indexed.get(identity)
        if card is None or card.get("verification_status") != "verified":
            raise ValueError(f"Missing or unverified cleanup card: {identity}")
        parent, key = field_parent(card, entry["field"])
        if parent[key] == entry["after"]:
            continue
        if parent[key] != entry["before"]:
            raise ValueError(f"Text differs from reviewed before/after: {target}")
        pending.append((parent, key, entry["after"]))
    for parent, key, after in pending:
        parent[key] = after
    return len(pending)


def main():
    """Apply the manifest to the default or explicitly supplied fixture paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--cleanup", type=Path, default=CLEANUP)
    args = parser.parse_args()
    cards = json.loads(args.fixture.read_text(encoding="utf-8"))
    replacements = json.loads(args.cleanup.read_text(encoding="utf-8"))
    changed = apply_cleanup(cards, replacements)
    if changed:
        args.fixture.write_text(
            json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Applied {changed} text replacements ({len(replacements)} reviewed entries)")


if __name__ == "__main__":
    main()
