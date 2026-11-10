"""Eval runner: ``python -m evals run --suite golden_v1 --mode fake|live``.

- fake mode: deterministic stub responses derived from each case's own
  expected facts/citations. Zero LLM calls; proves the harness end-to-end
  and seeds the baseline. It is a *harness smoke*, not an advisor score.
- live mode: calls the advisor service/endpoint via import guard. The
  advisor lands in a parallel branch; until it exists, live mode exits
  with a clear message instead of failing obscurely.

Gates (see baselines.json / runbook):
- Deterministic (PR CI): every case must pass -> score must be 1.0.
- Nightly (only when RAGAS scores exist): faithfulness >= 0.85,
  context_recall >= 0.80, and no category may drop > 3 points versus the
  stored baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

from .dataset import ROOT, load_cases
from .graders import grade_case, grade_retrieval
from .langsmith_adapter import log_experiment, sync_dataset
from .ragas_runner import run_ragas
from .reports import summarise, write_reports

BASELINES = ROOT / "baselines.json"
NIGHTLY_THRESHOLDS = {"faithfulness": 0.85, "context_recall": 0.80}
CATEGORY_DROP_LIMIT = 0.03


# ---------------------------------------------------------------- fake mode
def stub_response(case: dict) -> dict:
    """A response built from the case's expected data (offline, no LLM).

    Honesty/fallback cases have no expected facts: the stub is the correct
    behaviour for them — a refusal/uncertainty answer containing none of
    the forbidden phrases.
    """
    facts = {
        k: v
        for k, v in (case.get("expected_facts") or {}).items()
        if k not in ("principal_bdt", "tenure_months")
    }
    if case["category"] in ("honesty-adversarial", "fallback"):
        answer = (
            "I don't have published data to answer that as stated, and "
            "CreditMate cannot make promises about a bank's decision. "
            "Please use the published card data and eligibility results."
        )
        return {
            "answer": answer,
            "cited_product_ids": [],
            "citations": [],
            "figures": {},
            "contexts": [],
        }
    fact_text = "; ".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in facts.items() if v is not None
    )
    names = ", ".join(case.get("expected_product_ids") or [])
    answer = f"Based on published CreditMate data for {names}: {fact_text}."
    return {
        "answer": answer,
        "cited_product_ids": list(case.get("expected_product_ids") or []),
        "citations": list(case.get("required_citations") or []),
        "figures": facts,
        "contexts": [answer],
    }


# ---------------------------------------------------------------- live mode
def live_response(case: dict) -> dict:
    """Call the advisor via import guard (parallel branch: `advisor`)."""
    try:
        from advisor.services import ask_advisor  # type: ignore
    except ImportError:
        try:
            from advisor.graph import run_advisor  # type: ignore

            return run_advisor(case["question"])
        except ImportError as exc:
            raise RuntimeError(
                "live mode unavailable: the advisor app (parallel branch "
                "feat/advisor) is not in this tree yet. Use --mode fake."
            ) from exc
    result = ask_advisor(case["question"])
    return result if isinstance(result, dict) else {"answer": str(result),
                                                    "cited_product_ids": [],
                                                    "citations": []}


def _retriever():
    try:
        from retrieval.service import search_chunk_ids  # type: ignore

        return search_chunk_ids
    except Exception:
        return None


# -------------------------------------------------------------------- gates
def load_baselines() -> dict:
    if BASELINES.exists():
        return json.loads(BASELINES.read_text())
    return {}


def apply_gates(summary: dict, ragas: dict, nightly: bool) -> tuple[bool, list[str]]:
    failures = []
    if summary["totals"]["score"] < 1.0:
        failures.append(
            f"deterministic gate: score {summary['totals']['score']} < 1.0"
        )
    if nightly and ragas.get("available"):
        scores = ragas.get("scores") or {}
        for metric, threshold in NIGHTLY_THRESHOLDS.items():
            if metric in scores and scores[metric] < threshold:
                failures.append(
                    f"nightly gate: {metric} {scores[metric]:.3f} < {threshold}"
                )
        baseline = load_baselines().get("categories") or {}
        for cat, vals in summary["categories"].items():
            base = (baseline.get(cat) or {}).get("score")
            if base is not None and base - vals["score"] > CATEGORY_DROP_LIMIT:
                failures.append(
                    f"nightly gate: category {cat} dropped "
                    f"{base - vals['score']:.3f} (> {CATEGORY_DROP_LIMIT}) vs baseline"
                )
    return (not failures), failures


def run(suite="golden_v1", mode="fake", out_dir=None, nightly=False) -> dict:
    cases = load_cases(suite)
    respond = stub_response if mode == "fake" else live_response
    responses, results = [], []
    retriever = _retriever()
    for case in cases:
        response = respond(case)
        responses.append(response)
        graded = grade_case(case, response)
        retrieval = grade_retrieval(case, retriever)
        if retrieval is not None:
            graded["retrieval"] = retrieval
        results.append(graded)
    ragas = run_ragas(cases, responses) if nightly or mode == "live" else {
        "available": False,
        "reason": "not requested (deterministic run)",
    }
    meta = {"suite": suite, "mode": mode, "nightly": nightly, "ragas": ragas}
    summary = summarise(results, meta)
    gates_passed, gate_failures = apply_gates(summary, ragas, nightly)
    summary["meta"]["gates_passed"] = gates_passed
    summary["meta"]["gate_failures"] = gate_failures
    summary["langsmith"] = {
        "sync": sync_dataset(cases),
        "experiment": log_experiment(summary),
    }
    out = Path(out_dir) if out_dir else ROOT / "reports" / f"{suite}-{mode}"
    json_path, html_path = write_reports(summary, out)
    summary["meta"]["report_json"] = str(json_path)
    summary["meta"]["report_html"] = str(html_path)
    return summary
