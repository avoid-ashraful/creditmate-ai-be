#!/usr/bin/env python3
"""Independent readability cross-check for the CreditMate AI user guides.

Why this file exists
--------------------
``readability_check.py`` is the CI gate, but it uses its own English syllable
counter, so on its own it is weak *independent* proof that the guides score
below a Flesch-Kincaid grade of 8.0. This script re-scores the exact same text
with established third-party scorers:

* **textstat 0.7.13** - the standard Python readability library. It computes
  Flesch-Kincaid from its own independent word/sentence/syllable counters
  (``textstat.lexicon_count``, ``textstat.sentence_count``,
  ``textstat.syllable_count``). Formula, from its own docstring::

      (.39 * avg sentence length) + (11.8 * avg syllables per word) - 15.59

* **CMU Pronouncing Dictionary** (optional, used when the ``cmudict`` package is
  importable) - a real dictionary of word pronunciations. Each syllable is
  counted from the ARPAbet phoneme list, which is unrelated to any heuristic.
  The grade is then recomputed with those syllable counts.

Method and what is *not* done
-----------------------------
* The **input is identical** to the CI gate: this module imports the normalisers
  (``strip_markdown``, ``strip_typescript``) from ``readability_check`` rather
  than reimplementing them, so both scorers see byte-for-byte the same prose.
* The SHA-256 and length of that normalised input are printed for every file, so
  the exact input can be reproduced and audited.
* Every file is reported **separately**. There is no average, no weighted score
  and no combined figure that could hide one hard guide.
* Nothing here tunes the scoring rules. Thresholds, formulas and word/sentence
  splitting are the defaults of the libraries named above; the only choice made
  by this script is which text is fed in (see below), and that choice is shared
  with the CI gate so the two numbers are comparable.
* What is stripped before scoring: fenced code, link/image syntax (the link
  **label** is kept, the URL is not), heading/list/blockquote markers, emphasis
  markers, table pipes, HTML tags and bare URLs. A URL is not prose a reader
  sounds out, and the source URLs are identical for every guide, so including
  them would move every score the same way and prove nothing.

Exit status
-----------
``0`` every file is below the threshold under every scorer that ran
``1`` at least one file is at or above the threshold
``2`` an underlying scorer (textstat) is not installed - nothing was measured
``3`` a guide file is missing

Usage
-----
    uv venv .venv-readability --python 3.12
    uv pip install --python .venv-readability/bin/python textstat cmudict
    .venv-readability/bin/python docs/user/readability_textstat.py --fe ../creditmate-ai-fe/src/content/guides.ts
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys

# Re-use the CI gate's normalisers and file list so both scorers share one input.
_HERE = os.path.dirname(os.path.abspath(__file__))
_GATE_PATH = os.path.join(_HERE, "readability_check.py")
_spec = importlib.util.spec_from_file_location("readability_check", _GATE_PATH)
if _spec is None or _spec.loader is None:
    print(f"cannot load {_GATE_PATH}", file=sys.stderr)
    raise SystemExit(3)
gate = importlib.util.module_from_spec(_spec)
sys.modules["readability_check"] = gate
_spec.loader.exec_module(gate)

try:
    import textstat  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    print(
        "textstat is not installed. Install it first, for example:\n"
        "  uv venv .venv-readability --python 3.12\n"
        "  uv pip install --python .venv-readability/bin/python textstat cmudict",
        file=sys.stderr,
    )
    raise SystemExit(2)

try:
    import cmudict  # type: ignore
except ImportError:  # pragma: no cover - optional extra
    cmudict = None


MAX_GRADE = 8.0

# CMU dict is ~134k entries; parse it once instead of per token.
_CMU: dict | None = None


def cmu_dict() -> dict | None:
    """Return the CMU dictionary, parsed once and cached."""
    global _CMU
    if cmudict is None:
        return None
    if _CMU is None:
        _CMU = cmudict.dict()
    return _CMU


def cmu_syllables(word: str) -> int | None:
    """Syllables for ``word`` straight from CMU dict, or None when unknown."""
    table = cmu_dict()
    if table is None:
        return None
    entries = table.get(word.lower())
    if not entries:
        # Hyphenated compounds (e.g. "fee-free") are not dictionary entries;
        # score them as the sum of their parts when every part is known.
        if "-" in word:
            parts = [cmu_syllables(p) for p in word.split("-") if p]
            if parts and all(p is not None for p in parts):
                return sum(int(p) for p in parts if p is not None)
        return None
    phones = entries[0]
    # ARPAbet: every vowel phone carries a stress digit (AA0, AH1, EY2) and no
    # consonant phone does, so counting stress digits counts syllables.
    return sum(1 for phone in phones if phone[-1:].isdigit())


def cmu_score(words: list[str], sentences: int) -> tuple[float | None, float]:
    """Return (Flesch-Kincaid grade from CMU syllables, coverage 0-1).

    The grade is computed over the words CMU actually knows; ``coverage`` says
    how much of the token stream that is, so a partial dictionary cannot quietly
    flatter a score.
    """
    counts = [cmu_syllables(w) for w in words]
    known = [int(c) for c in counts if c is not None]
    coverage = (len(known) / len(words)) if words else 0.0
    if not known or not words or sentences <= 0:
        return None, coverage
    return (
        0.39 * (len(known) / sentences) + 11.8 * (sum(known) / len(known)) - 15.59,
        coverage,
    )


def word_list(text: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z][A-Za-z'\-]*", text)


def score_file(name: str, prose: str) -> dict[str, object]:
    digest = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    words = word_list(prose)
    sentences = int(textstat.sentence_count(prose))

    row: dict[str, object] = {
        "file": name,
        "chars": len(prose),
        "sha256": digest,
        "ts_words": int(textstat.lexicon_count(prose)),
        "ts_sentences": sentences,
        "ts_syllables": int(textstat.syllable_count(prose)),
        "ts_fk": round(float(textstat.flesch_kincaid_grade(prose)), 4),
        "ts_fre": round(float(textstat.flesch_reading_ease(prose)), 4),
        "ts_fog": round(float(textstat.gunning_fog(prose)), 4),
        "cmu_fk": None,
        "cmu_syllables": None,
    }

    grade, coverage = cmu_score(words, sentences)
    row["cmu_cov"] = round(coverage, 4)
    if grade is not None:
        counts = [cmu_syllables(w) for w in words]
        row["cmu_syllables"] = sum(int(c) for c in counts if c is not None)
        row["cmu_fk"] = round(grade, 4)

    # Same formula, same input, but scored by this script's own counter: this is
    # the number the CI gate produces, shown next to the independent scorers so
    # any divergence between counters is visible rather than hidden.
    gate_score = gate.score_text(name, prose)
    row["own_fk"] = round(gate_score.grade, 4)
    return row


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="directory holding the Markdown guides",
    )
    parser.add_argument(
        "--fe",
        action="append",
        default=[],
        metavar="FILE",
        help="frontend guide content file (repeatable), e.g. src/content/guides.ts",
    )
    parser.add_argument("--max-grade", type=float, default=MAX_GRADE)
    args = parser.parse_args(argv)

    inputs: list[tuple[str, str]] = []
    for filename in gate.GUIDE_FILES:
        path = os.path.join(args.dir, filename)
        if not os.path.exists(path):
            print(f"MISSING: {path}", file=sys.stderr)
            return 3
        with open(path, encoding="utf-8") as handle:
            inputs.append((filename, gate.strip_markdown(handle.read())))

    for fe_path in args.fe:
        if not os.path.exists(fe_path):
            print(f"MISSING: {fe_path}", file=sys.stderr)
            return 3
        with open(fe_path, encoding="utf-8") as handle:
            inputs.append((os.path.relpath(fe_path, args.dir), gate.strip_typescript(handle.read())))

    print(
        f"scorer A: textstat {'.'.join(str(p) for p in textstat.__version__)} "
        f"(flesch_kincaid_grade, its own lexicon/sentence/syllable counters)"
    )
    print(
        "scorer B: CMU Pronouncing Dictionary syllables "
        + ("(available)" if cmudict is not None else "(NOT INSTALLED - skipped)")
    )
    print(f"scorer C: readability_check.py own counter (the CI gate)")
    print(f"threshold: Flesch-Kincaid grade < {args.max_grade}, evaluated per file\n")

    header = (
        f"{'file':<36}{'chars':>7}{'words':>7}{'sent':>6}{'syl':>7}"
        f"{'A_fk':>9}{'B_fk':>9}{'B_cov':>8}{'C_fk':>9}{'FRE':>9}{'Fog':>8}"
    )
    print(header)
    print("-" * len(header))

    rows = [score_file(name, prose) for name, prose in inputs]

    failures: list[str] = []
    for row in rows:
        a = float(row["ts_fk"])
        b = row["cmu_fk"]
        cov = float(row["cmu_cov"])
        c = float(row["own_fk"])
        b_text = f"{b:9.4f}" if b is not None else f"{'n/a':>9}"
        flag = "OK"
        for label, value in (("textstat", a), ("cmu", b), ("own", c)):
            if value is not None and float(value) >= args.max_grade:
                flag = f"FAIL[{label}]"
                failures.append(f"{row['file']} via {label} = {value}")
        print(
            f"{str(row['file'])[:35]:<36}{row['chars']:>7}{row['ts_words']:>7}"
            f"{row['ts_sentences']:>6}{row['ts_syllables']:>7}"
            f"{a:>9.4f}{b_text}{cov:>8.3f}{c:>9.4f}"
            f"{float(row['ts_fre']):>9.4f}{float(row['ts_fog']):>8.4f}  {flag}"
        )

    print("\nexact inputs (SHA-256 of the normalised prose fed to every scorer):")
    for row in rows:
        print(f"  {str(row['file'])[:35]:<36} {row['sha256']}  ({row['chars']} chars)")

    if failures:
        print("\nCROSS-CHECK FAIL:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"\nall {len(rows)} file(s) below grade {args.max_grade} under every scorer that ran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
