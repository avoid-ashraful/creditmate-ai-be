#!/usr/bin/env python3
"""Merge verified reward data into the verified-card fixture.

The reward files live outside this repository (one JSON file per bank). Each
entry is matched to a fixture row by card name within the same bank, so bank
naming differences between the two datasets are handled. Existing fixture
values are never changed, except that an empty ``reward_points_policy`` is
filled with the verbatim earn/cashback texts. The merge is idempotent.

Example
-------
python scripts/merge_reward_data.py \
    --rewards-dir /home/ubuntu/credit-agent-control/r2/rewards \
    --fixture credit_cards/fixtures/verified_cards_2026-10-18.json
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_REWARDS_DIR = "/home/ubuntu/credit-agent-control/r2/rewards"
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "credit_cards"
    / "fixtures"
    / "verified_cards_2026-10-18.json"
)

#: Reward-file bank names that differ from the fixture/seed spelling.
BANK_ALIASES = {"the city bank plc": "city bank plc"}


def _normalize_bank(name):
    """Return a lowercase, whitespace-normalised bank name."""
    return " ".join(str(name or "").lower().split())


def resolve_fixture_bank(fixture_rows, reward_bank, reward_cards):
    """Find the fixture bank that owns a reward file.

    Parameters
    ----------
    fixture_rows : list of dict
        Rows loaded from the verified-card fixture.
    reward_bank : str
        Bank name written in the reward file.
    reward_cards : list of dict
        Reward entries from that file, used as a fallback fingerprint.

    Returns
    -------
    str or None
        Matching fixture bank name, or ``None`` when the match is ambiguous.
    """
    banks = {row["bank"] for row in fixture_rows}
    if reward_bank in banks:
        return reward_bank

    alias = BANK_ALIASES.get(_normalize_bank(reward_bank))
    if alias:
        for bank in banks:
            if _normalize_bank(bank) == alias:
                return bank

    # Fallback: the bank whose fixture cards overlap the reward cards most.
    reward_names = {card.get("card_name") for card in reward_cards}
    names_by_bank = {}
    for row in fixture_rows:
        names_by_bank.setdefault(row["bank"], set()).add(row["name"])
    scores = {bank: len(reward_names & names) for bank, names in names_by_bank.items()}
    best = max(scores.values(), default=0)
    winners = [bank for bank, score in scores.items() if score == best and best > 0]
    return winners[0] if len(winners) == 1 else None


def apply_reward_data(row, entry):
    """Copy one reward entry onto a fixture row without touching other values.

    Parameters
    ----------
    row : dict
        Fixture row to update in place.
    entry : dict
        Reward entry for the same card.

    Returns
    -------
    None
    """
    row["reward_program_name"] = entry.get("reward_program_name") or ""
    row["reward_earn_rules"] = entry.get("earn_rules") or []
    row["cashback_rules"] = entry.get("cashback_rules") or []
    point_value = entry.get("point_value_bdt")
    # Keep the literal decimal as a string: a JSON float would be read back as
    # a binary expansion and fail DecimalField's decimal-place validation.
    row["reward_point_value_bdt"] = str(point_value) if point_value is not None else None
    row["points_expiry_text"] = entry.get("points_expiry_text") or ""
    row["reward_source_url"] = entry.get("source_url") or ""

    if not str(row.get("reward_points_policy") or "").strip():
        texts = [
            str(rule.get("text") or "").strip()
            for rule in row["reward_earn_rules"] + row["cashback_rules"]
        ]
        row["reward_points_policy"] = " ".join(text for text in texts if text)


def merge_rewards(fixture_rows, rewards_dir):
    """Merge every reward file in ``rewards_dir`` into ``fixture_rows``.

    Parameters
    ----------
    fixture_rows : list of dict
        Rows loaded from the verified-card fixture (updated in place).
    rewards_dir : str or pathlib.Path
        Directory containing ``<bank_slug>.json`` reward files.

    Returns
    -------
    dict
        Merge statistics, including any unmatched cards or files.
    """
    stats = {
        "files": 0,
        "entries": 0,
        "matched": 0,
        "unmatched_cards": [],
        "unmatched_files": [],
    }
    rows_by_key = {}
    for row in fixture_rows:
        key = (row["bank"], row["name"])
        if key in rows_by_key:
            raise ValueError(f"Duplicate fixture card: {key[0]} / {key[1]}")
        rows_by_key[key] = row

    for path in sorted(Path(rewards_dir).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
            stats["unmatched_files"].append(f"{path.name} (not a reward file)")
            continue
        stats["files"] += 1
        reward_cards = payload["cards"]
        stats["entries"] += len(reward_cards)
        bank = resolve_fixture_bank(fixture_rows, payload.get("bank"), reward_cards)
        if bank is None:
            stats["unmatched_files"].append(f"{path.name} (bank {payload.get('bank')!r})")
            continue
        for entry in reward_cards:
            name = entry.get("card_name")
            row = rows_by_key.get((bank, name))
            if row is None:
                stats["unmatched_cards"].append(f"{bank} / {name}")
                continue
            apply_reward_data(row, entry)
            stats["matched"] += 1
    return stats


def count_rewards(fixture_rows):
    """Count cards carrying each kind of reward data.

    Parameters
    ----------
    fixture_rows : list of dict
        Fixture rows after the merge.

    Returns
    -------
    dict
        Counts for earn rules, cashback rules, stated point value and expiry.
    """
    return {
        "earn_rules": sum(1 for row in fixture_rows if row.get("reward_earn_rules")),
        "cashback": sum(1 for row in fixture_rows if row.get("cashback_rules")),
        "point_value": sum(
            1 for row in fixture_rows if row.get("reward_point_value_bdt") is not None
        ),
        "expiry": sum(1 for row in fixture_rows if row.get("points_expiry_text")),
        "policy_text": sum(
            1
            for row in fixture_rows
            if str(row.get("reward_points_policy") or "").strip()
        ),
    }


def main(argv=None):
    """Run the merge and write the fixture in place.

    Parameters
    ----------
    argv : list of str, optional
        Command line arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code: 0 on a complete merge, 1 when anything was unmatched.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rewards-dir",
        default=DEFAULT_REWARDS_DIR,
        help="Directory of <bank_slug>.json reward files",
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="Verified-card fixture to merge into (written in place)",
    )
    args = parser.parse_args(argv)

    fixture_path = Path(args.fixture)
    fixture_rows = json.loads(fixture_path.read_text(encoding="utf-8"))
    stats = merge_rewards(fixture_rows, args.rewards_dir)
    counts = count_rewards(fixture_rows)

    fixture_path.write_text(
        json.dumps(fixture_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Reward files read: {stats['files']}")
    print(f"Reward entries: {stats['entries']}")
    print(f"Matched cards: {stats['matched']}")
    print(f"Unmatched cards: {len(stats['unmatched_cards'])}")
    for item in stats["unmatched_cards"]:
        print(f"  unmatched card: {item}")
    print(f"Unmatched files: {len(stats['unmatched_files'])}")
    for item in stats["unmatched_files"]:
        print(f"  unmatched file: {item}")
    print(f"Cards with earn rules: {counts['earn_rules']}")
    print(f"Cards with cashback rules: {counts['cashback']}")
    print(f"Cards with stated point value: {counts['point_value']}")
    print(f"Cards with points expiry: {counts['expiry']}")
    print(f"Cards with reward_points_policy text: {counts['policy_text']}")
    return 1 if stats["unmatched_cards"] or stats["unmatched_files"] else 0


if __name__ == "__main__":
    sys.exit(main())
