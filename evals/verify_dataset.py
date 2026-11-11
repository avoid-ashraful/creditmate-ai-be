"""Verify the golden dataset against the real catalogue.

Runnable as ``python -m evals.verify_dataset [--suite golden_v1]``.
Exit code 0 = no drift, 1 = drift / unknown product / bad EMI figure.

Checks every verifiable expected fact:
- ``annual_fee_bdt``            -> card.annual_fee
- ``interest_rate_apr_percent`` -> card.interest_rate_apr
- ``min_monthly_income_bdt``    -> card.min_monthly_income (None = unpublished)
- slug-qualified variants (``annual_fee_bdt:<slug>``) for comparisons
- ``expected_emi_bdt`` recomputed from principal / tenure / the card's APR

Catalogue source: live Django DB when configured and non-empty, otherwise
the verified fixture shipped in the repo (and the source used is printed).
"""

from __future__ import annotations

import argparse
import sys

from .dataset import load_cases, load_catalogue

FIELD_MAP = {
    "annual_fee_bdt": "annual_fee",
    "interest_rate_apr_percent": "interest_rate_apr",
    "min_monthly_income_bdt": "min_monthly_income",
}


def _close(a, b, tol=0.51) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def _emi(principal, apr_percent, months) -> float:
    r = float(apr_percent) / 1200.0
    if r == 0:
        return float(principal) / months
    return float(principal) * r * (1 + r) ** months / ((1 + r) ** months - 1)


# C901: sequential independent dataset checks — a linear checklist.
def verify(suite: str = "golden_v1") -> list[str]:  # noqa: C901
    cases = load_cases(suite)
    cards, source = load_catalogue()
    by_slug = {c["slug"]: c for c in cards}
    print(f"Catalogue source: {source} ({len(cards)} cards); cases: {len(cases)}")
    problems: list[str] = []
    for case in cases:
        facts = case.get("expected_facts") or {}
        slugs = case.get("expected_product_ids") or []
        for slug in slugs:
            if slug not in by_slug:
                problems.append(f"{case['id']}: unknown product slug {slug}")
        # EMI recomputation uses the first expected product's APR fact.
        if "expected_emi_bdt" in facts and slugs and slugs[0] in by_slug:
            apr = facts.get("interest_rate_apr_percent")
            if apr is not None:
                want = _emi(facts["principal_bdt"], apr, facts["tenure_months"])
                if not _close(want, facts["expected_emi_bdt"], tol=1.0):
                    problems.append(
                        f"{case['id']}: expected_emi_bdt {facts['expected_emi_bdt']} "
                        f"!= recomputed {want:.2f}"
                    )
        for key, expected in facts.items():
            if key in ("principal_bdt", "tenure_months", "expected_emi_bdt", "bank"):
                continue
            base, _, qual = key.partition(":")
            if base not in FIELD_MAP:
                problems.append(f"{case['id']}: unverifiable fact key {key}")
                continue
            targets = [qual] if qual else slugs
            if len(targets) != 1:
                problems.append(
                    f"{case['id']}: fact {key} needs slug qualification "
                    f"(case has {len(targets)} products)"
                )
                continue
            card = by_slug.get(targets[0])
            if card is None:
                continue  # already reported as unknown slug
            actual = card[FIELD_MAP[base]]
            if not _close(actual, expected):
                problems.append(
                    f"{case['id']}: {key} dataset={expected!r} catalogue={actual!r} "
                    f"({targets[0]})"
                )
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="evals.verify_dataset")
    parser.add_argument("--suite", default="golden_v1")
    args = parser.parse_args(argv)
    problems = verify(args.suite)
    if problems:
        print(f"DRIFT: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: every verifiable expected fact matches the catalogue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
