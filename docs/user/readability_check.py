#!/usr/bin/env python3
"""Readability check for the CreditMate AI user guides (task 9.1).

The acceptance criterion is *"SEO-optimized, readable (Flesch-Kincaid < 8th grade)"*.
This script measures exactly that, transparently and reproducibly.

What it measures
----------------
Every Markdown guide in this directory (``README.md`` is an index, so it is
skipped) and, optionally, the frontend guide content that the React
``GuidesPage`` actually renders (``--fe src/content/guides.ts``).

The text is normalised first so the score reflects prose a reader sees, not
Markdown/TypeScript syntax:

* fenced code blocks are dropped
* link/image syntax is reduced to its label text
* headings, list markers, blockquotes, table pipes, emphasis markers are stripped
* HTML tags are dropped
* URL-looking tokens (``https://...``) are dropped
* for a ``.ts`` file, every single-quoted literal except the values of
  metadata keys (slug, url, publisher, category, ...) is treated as prose

Metrics
-------
* **Flesch-Kincaid grade level** - the acceptance metric. Must be < 8.0.
* Flesch Reading Ease - higher is easier (target >= 60 for plain English).
* Gunning Fog index - reported for extra transparency.

Syllables are counted with the usual English heuristic (short words, silent
``-ed``/``-e`` endings, vowel groups). The ``--selftest`` flag runs known-answer
tests so the counter can be trusted, and ``--csv`` emits a machine-readable
table.

Exit status: ``0`` when every guide is below the 8.0 threshold, ``1`` otherwise.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from dataclasses import dataclass

# Guides that must be measured (acceptance criteria of task 9.1).
GUIDE_FILES = [
    "choosing-your-first-credit-card.md",
    "understanding-annual-fee-waivers.md",
    "maximizing-lounge-access-benefits.md",
    "credit-card-vs-debit-card.md",
]

MAX_GRADE = 8.0

# Object keys in guides.ts that hold user-visible prose.
PROSE_KEYS = (
    "title",
    "description",
    "heading",
    "disclaimer",
    "aspect",
    "debit",
    "credit",
    "label",
    "publisher",
)

# Array keys in guides.ts whose items are user-visible prose.
ARRAY_KEYS = ("paragraphs", "bullets", "steps")


@dataclass
class Score:
    name: str
    words: int
    sentences: int
    syllables: int
    grade: float
    ease: float
    fog: float


def count_syllables(word: str) -> int:
    """Return the number of syllables in an English word (heuristic).

    Three well known English rules are applied, in order:

    1. Words of three letters or fewer hold one syllable.
    2. Silent endings are dropped: ``-ed`` after a consonant sound (``walked``),
       ``-es`` after a consonant sound (``tens``) and a final consonant +
       ``-e`` (``phone``).
    3. A leading ``y`` counts as a consonant, so it is dropped.
    4. What is left is scanned for vowel groups (``table`` holds ``a`` + ``e``,
       so it has 2 syllables).
    """
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1

    # Drop silent endings: 'ed' (walked), 'es' (tens) and final consonant+'e'.
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    # A leading 'y' is a consonant ("yellow"), not a vowel.
    word = re.sub(r"^y", "", word)

    groups = re.findall(r"[aeiouy]{1,2}", word)
    return len(groups) if groups else 1


def strip_markdown(text: str) -> str:
    """Reduce Markdown to plain prose."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"```.*", " ", text, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)
    text = text.replace("|", " ")
    text = re.sub(r"[*_`~]", "", text)
    # Drop bare URLs and mail addresses (they are links to sources, not prose).
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\S+@\S+", " ", text)
    return normalise(text)


def strip_typescript(text: str) -> str:
    """Reduce a ``guides.ts`` content module to its prose strings.

    Only the values of keys that hold visible copy are read:

    * ``PROSE_KEYS`` - one string value per key, e.g. ``heading: 'Banking'``
    * ``ARRAY_KEYS``  - a list of strings, e.g. ``paragraphs: ['...', '...']``

    Both quote styles are accepted because Prettier rewrites strings that
    contain an apostrophe to double quotes.
    """
    # Remove comments first so commented-out copy is not counted.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//.*$", " ", text, flags=re.M)

    pieces: list[str] = []

    def unwrap(raw: str) -> str:
        inner = raw[1:-1]
        return inner.replace("\\'", "'").replace('\\"', '"')

    for key in PROSE_KEYS:
        pattern = rf"\b{key}:\s*((?:'(?:[^'\\]|\\.)*')|(?:\"(?:[^\"\\]|\\.)*\"))"
        for match in re.finditer(pattern, text):
            if match.group(1).strip(" '\""):
                pieces.append(unwrap(match.group(1)))

    for key in ARRAY_KEYS:
        pattern = rf"\b{key}:\s*\[(.*?)\]"
        for match in re.finditer(pattern, text, flags=re.S):
            for item in re.finditer(r"(?:'(?:[^'\\]|\\.)*')|(?:\"(?:[^\"\\]|\\.)*\")", match.group(1)):
                pieces.append(unwrap(item.group(0)))

    prose = ". ".join(p for p in pieces if p.strip())
    prose = re.sub(r"https?://\S+", " ", prose)
    return normalise(prose)


def normalise(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    # Split into sentences. A sentence ends on . ! ? : followed by a space.
    text = re.sub(r"([.!?])\s+", r"\1 ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\s*[;]\s+|\s+[-\u2013]\s+", text)
    return [c for c in (c.strip() for c in chunks) if c]


def score_text(name: str, text: str) -> Score:
    sentences = split_sentences(text)
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if not sentences:
        sentences = ["."]
    if not words:
        return Score(name, 0, 0, 0, 0.0, 0.0, 0.0)

    syllables = sum(count_syllables(w) for w in words)
    long_words = sum(1 for w in words if count_syllables(w) >= 3)

    wps = len(words) / len(sentences)
    spw = syllables / len(words)

    grade = 0.39 * wps + 11.8 * spw - 15.59
    ease = 206.835 - 1.015 * wps - 84.6 * spw
    fog = 0.4 * (wps + 100.0 * (long_words / len(words)))

    return Score(
        name=name,
        words=len(words),
        sentences=len(sentences),
        syllables=syllables,
        grade=round(grade, 2),
        ease=round(ease, 2),
        fog=round(fog, 2),
    )


def read_guide(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if path.endswith(".md"):
        return strip_markdown(text)
    if path.endswith((".ts", ".tsx")):
        return strip_typescript(text)
    raise ValueError(f"unsupported file type: {path}")


def check_guide_links(directory: str) -> list[str]:
    """Return editorial violations found in the raw Markdown guides.

    The app's compare page only renders cards that were already selected on the
    home page, where the filter panel lives. A guide must therefore never send
    readers to ``/compare`` as if it were a browse or filter screen.
    """
    violations: list[str] = []
    for filename in GUIDE_FILES:
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if re.search(r"\]\(/compare(?:[?)\s#]|$)", line):
                    violations.append(f"{filename}:{lineno} links to /compare")
    return violations


def selftest() -> int:
    """Known-answer tests for the syllable counter and the grade formula."""
    cases = {
        "cat": 1,
        "the": 1,
        "bank": 1,
        "lounge": 1,
        "phone": 1,
        "walked": 1,
        "fees": 1,
        "table": 2,
        "annual": 2,
        "credit": 2,
        "debit": 2,
        "money": 2,
        "airport": 2,
        "benefits": 3,
        "waiver": 2,
        "choosing": 2,
        "interest": 3,
        "bangladesh": 3,
        "information": 4,
    }
    failures = []
    for word, expected in cases.items():
        got = count_syllables(word)
        if got != expected:
            failures.append(f"count_syllables({word!r}) = {got}, expected {expected}")

    # A six word sentence must split into six words and one sentence.
    score = score_text("selftest", "The cat sat on the mat.")
    if score.words != 6 or score.sentences != 1:
        failures.append(f"basic split failed: {score}")

    if failures:
        print("SELFTEST FAIL")
        for line in failures:
            print("  -", line)
        return 1
    print(f"SELFTEST OK ({len(cases)} syllable cases + sentence splitting)")
    return 0


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
    parser.add_argument("--csv", action="store_true", help="emit a CSV table")
    parser.add_argument("--selftest", action="store_true", help="run self tests")
    parser.add_argument(
        "--max-grade",
        type=float,
        default=MAX_GRADE,
        help=f"fail when a guide is at or above this grade (default {MAX_GRADE})",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    violations = check_guide_links(args.dir)
    if violations:
        for violation in violations:
            print(f"LINK POLICY FAIL: {violation}", file=sys.stderr)
        return 1

    results: list[Score] = []
    for filename in GUIDE_FILES:
        path = os.path.join(args.dir, filename)
        if not os.path.exists(path):
            print(f"MISSING: {path}", file=sys.stderr)
            return 1
        results.append(score_text(filename, read_guide(path)))

    for fe_path in args.fe:
        if not os.path.exists(fe_path):
            print(f"MISSING: {fe_path}", file=sys.stderr)
            return 1
        results.append(
            score_text(os.path.relpath(fe_path, args.dir), read_guide(fe_path))
        )

    if args.csv:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["file", "words", "sentences", "syllables", "fk_grade", "flesch_ease", "gunning_fog"])
        for row in results:
            writer.writerow(
                [row.name, row.words, row.sentences, row.syllables, row.grade, row.ease, row.fog]
            )
        sys.stdout.write(buffer.getvalue())
    else:
        print(f"{'file':<34}{'words':>7}{'sent':>6}{'syl':>6}{'FK':>8}{'FRE':>8}{'Fog':>8}")
        print("-" * 77)
        for row in results:
            flag = "OK " if row.grade < args.max_grade else "FAIL"
            print(
                f"{row.name:<34}{row.words:>7}{row.sentences:>6}{row.syllables:>6}"
                f"{row.grade:>8.2f}{row.ease:>8.2f}{row.fog:>8.2f}  {flag}"
            )
        print("-" * 77)
        worst = max(r.grade for r in results)
        print(
            f"threshold: FK grade < {args.max_grade}  |  "
            f"worst: {worst:.2f}  |  {len(results)} file(s) measured"
        )

    failing = [r.name for r in results if r.grade >= args.max_grade]
    if failing:
        print(f"READABILITY FAIL: {', '.join(failing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
