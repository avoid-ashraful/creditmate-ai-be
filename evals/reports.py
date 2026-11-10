"""JSON + simple HTML report rendering for an eval run."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path


def summarise(results: list[dict], meta: dict) -> dict:
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    categories = {}
    for cat, rows in sorted(by_cat.items()):
        passed = sum(1 for r in rows if r["passed"])
        categories[cat] = {
            "total": len(rows),
            "passed": passed,
            "score": round(passed / len(rows), 4) if rows else 0.0,
        }
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    grader_totals = Counter()
    grader_passed = Counter()
    for r in results:
        for name, g in r["graders"].items():
            grader_totals[name] += 1
            grader_passed[name] += 1 if g["passed"] else 0
    return {
        "meta": meta,
        "totals": {
            "cases": total,
            "passed": passed,
            "score": round(passed / total, 4) if total else 0.0,
        },
        "categories": categories,
        "graders": {
            n: {
                "total": grader_totals[n],
                "passed": grader_passed[n],
                "score": round(grader_passed[n] / grader_totals[n], 4),
            }
            for n in sorted(grader_totals)
        },
        "results": results,
    }


def write_reports(summary: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(summary, indent=2))
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(r["case_id"]),
            html.escape(r["category"]),
            "PASS" if r["passed"] else "FAIL",
            html.escape(
                "; ".join(
                    f"{n}: {g['detail']}"
                    for n, g in r["graders"].items()
                    if not g["passed"]
                )
            ),
        )
        for r in summary["results"]
    )
    cat_rows = "".join(
        f"<tr><td>{html.escape(c)}</td><td>{v['passed']}/{v['total']}</td>"
        f"<td>{v['score']:.3f}</td></tr>"
        for c, v in summary["categories"].items()
    )
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>CreditMate eval report — {html.escape(str(summary['meta'].get('suite')))}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}}</style></head><body>
<h1>CreditMate LLM eval report</h1>
<p>Suite: {html.escape(str(summary['meta'].get('suite')))} ·
Mode: {html.escape(str(summary['meta'].get('mode')))} ·
Score: {summary['totals']['passed']}/{summary['totals']['cases']} ({summary['totals']['score']:.3f}) ·
Gates passed: {summary['meta'].get('gates_passed')}</p>
<h2>By category</h2><table><tr><th>Category</th><th>Passed</th><th>Score</th></tr>{cat_rows}</table>
<h2>Cases</h2><table><tr><th>Case</th><th>Category</th><th>Result</th><th>Failures</th></tr>{rows}</table>
</body></html>"""
    html_path = out_dir / "report.html"
    html_path.write_text(doc)
    return json_path, html_path
