"""RAGAS integration — import-guarded, optional dependency group only.

Install with ``uv sync --group evals``. When ragas (or a judge model) is
unavailable this module reports ``available: False`` and the runner's
deterministic results stand alone; nightly RAGAS gates are only applied
when real scores exist (see runner.apply_gates).
"""

from __future__ import annotations

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def ragas_available() -> bool:
    try:
        import ragas  # noqa: F401

        return True
    except ImportError:
        return False


def run_ragas(cases: list[dict], responses: list[dict]) -> dict:
    """Compute RAGAS metrics for (case, response) pairs, if possible.

    Expected response extras for full scoring: ``contexts`` (list[str]).
    Without a configured judge/embedding model RAGAS cannot score; that
    condition is reported, not hidden.
    """
    if not ragas_available():
        return {"available": False, "reason": "ragas not installed (uv sync --group evals)"}
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        rows = {
            "question": [c["question"] for c in cases],
            "answer": [r.get("answer", "") for r in responses],
            "contexts": [r.get("contexts") or [""] for r in responses],
            "ground_truth": [
                ", ".join(str(v) for v in (c.get("expected_facts") or {}).values())
                for c in cases
            ],
        }
        result = evaluate(
            Dataset.from_dict(rows),
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )
        scores = {m: float(result[m]) for m in METRICS if m in result}
        return {"available": True, "scores": scores}
    except Exception as exc:
        return {
            "available": False,
            "reason": f"ragas evaluation failed: {exc.__class__.__name__}: {exc}",
        }
