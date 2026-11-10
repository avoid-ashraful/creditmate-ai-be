"""CLI: ``python -m evals run --suite golden_v1 --mode fake|live``."""

from __future__ import annotations

import argparse
import json
import sys

from .runner import run
from .verify_dataset import verify


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run an eval suite")
    run_p.add_argument("--suite", default="golden_v1")
    run_p.add_argument("--mode", choices=["fake", "live"], default="fake")
    run_p.add_argument("--nightly", action="store_true",
                       help="apply nightly RAGAS/category gates when scores exist")
    run_p.add_argument("--output-dir", default=None)
    verify_p = sub.add_parser("verify", help="verify the dataset against the catalogue")
    verify_p.add_argument("--suite", default="golden_v1")
    args = parser.parse_args(argv)

    if args.command == "verify":
        problems = verify(args.suite if hasattr(args, "suite") else "golden_v1")
        for p in problems:
            print(f"  - {p}")
        return 1 if problems else 0

    try:
        summary = run(
            suite=args.suite,
            mode=args.mode,
            out_dir=args.output_dir,
            nightly=args.nightly,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    totals = summary["totals"]
    print(
        f"{args.suite} ({args.mode}): {totals['passed']}/{totals['cases']} "
        f"passed, score {totals['score']}"
    )
    print(f"Reports: {summary['meta']['report_json']} / {summary['meta']['report_html']}")
    if not summary["meta"]["gates_passed"]:
        for failure in summary["meta"]["gate_failures"]:
            print(f"GATE FAILED: {failure}")
        return 1
    print("Gates: PASS")
    print(json.dumps(summary["categories"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
