"""Deterministic graders: no LLM calls, stable in PR CI.

A *response* is a dict shaped like the advisor contract::

    {"answer": str, "cited_product_ids": [slug, ...],
     "citations": [slug, ...], "figures": {fact_key: value, ...}}

Graders return ``(passed: bool, detail: str)`` and never raise on a badly
shaped response — a malformed answer is a failed grade, not a crash.
"""

from __future__ import annotations

from typing import Callable

REQUIRED_RESPONSE_KEYS = {"answer", "cited_product_ids", "citations"}


def _num_eq(a, b, tol=0.51) -> bool:
    try:
        if a is None or b is None:
            return a is b
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def grade_output_shape(case: dict, response) -> tuple[bool, str]:
    """Pydantic-shaped validity, with a no-dependency fallback validator.

    If pydantic is importable we validate through a real model; otherwise
    the equivalent structural checks run. Either way the contract checked
    is identical.
    """
    if not isinstance(response, dict):
        return False, "response is not an object"
    try:
        from pydantic import BaseModel, ConfigDict

        class _AdvisorAnswer(BaseModel):
            model_config = ConfigDict(extra="allow")
            answer: str
            cited_product_ids: list[str] = []
            citations: list = []
            figures: dict = {}

        _AdvisorAnswer.model_validate(response)
        return True, "valid AdvisorAnswer shape (pydantic)"
    except ImportError:
        missing = REQUIRED_RESPONSE_KEYS - response.keys()
        if missing:
            return False, f"missing keys {sorted(missing)}"
        if not isinstance(response.get("answer"), str) or not response["answer"]:
            return False, "answer must be a non-empty string"
        if not isinstance(response.get("cited_product_ids"), list):
            return False, "cited_product_ids must be a list"
        return True, "valid AdvisorAnswer shape (fallback validator)"
    except Exception as exc:  # pydantic ValidationError and friends
        return False, f"invalid AdvisorAnswer shape: {exc.__class__.__name__}"


def grade_figure_match(case: dict, response: dict) -> tuple[bool, str]:
    """Every verifiable expected fact must appear, with the same value.

    Fact keys may be slug-qualified (``annual_fee_bdt:<slug>``) for
    comparison cases; the response ``figures`` dict uses the same keys,
    plus bare keys for single-product cases. Non-numeric facts (bank)
    are compared as strings. Calculator EMI facts are checked in
    ``verify_dataset`` (catalogue truth) and here against the response.
    """
    facts = case.get("expected_facts") or {}
    figures = (response or {}).get("figures") or {}
    answer = ((response or {}).get("answer") or "").lower()
    failures = []
    for key, expected in facts.items():
        if key in ("principal_bdt", "tenure_months"):
            continue  # inputs, not answer facts
        if key in figures:
            ok = (
                _num_eq(figures[key], expected)
                if isinstance(expected, (int, float))
                else str(figures[key]) == str(expected)
            )
            if not ok:
                failures.append(f"{key}: response {figures[key]!r} != {expected!r}")
        elif isinstance(expected, (int, float)):
            # Accept the figure stated in prose, formatted with commas or not.
            needle_a = f"{expected:,.0f}" if float(expected).is_integer() else str(expected)
            needle_b = f"{expected:.0f}" if float(expected).is_integer() else str(expected)
            if needle_a.lower() not in answer and needle_b.lower() not in answer:
                failures.append(f"{key}: {expected!r} not in figures or answer")
        elif expected is None:
            # A None fact means "no published value": the answer must not
            # invent one; presence/absence is graded by honesty vocabulary.
            continue
        else:
            if str(expected).lower() not in answer and key not in figures:
                failures.append(f"{key}: {expected!r} not stated")
    if failures:
        return False, "; ".join(failures)
    return True, f"{len(facts)} expected fact(s) matched"


def grade_citation_validity(case: dict, response: dict) -> tuple[bool, str]:
    required = case.get("required_citations") or []
    cited = set((response or {}).get("citations") or []) | set(
        (response or {}).get("cited_product_ids") or []
    )
    missing = [c for c in required if c not in cited]
    if missing:
        return False, f"missing citations {missing}"
    expected = set(case.get("expected_product_ids") or [])
    invented = [c for c in cited if expected and c not in expected]
    if invented:
        return False, f"citations outside expected products {invented}"
    return True, f"{len(required)} required citation(s) present"


def grade_forbidden_phrases(case: dict, response: dict) -> tuple[bool, str]:
    """Honesty vocabulary: forbidden phrases must not appear in the answer."""
    answer = ((response or {}).get("answer") or "").lower()
    hits = [p for p in (case.get("forbidden_phrases") or []) if p.lower() in answer]
    if hits:
        return False, f"forbidden phrase(s) present: {hits}"
    return True, "no forbidden phrases"


def grade_expected_products(case: dict, response: dict) -> tuple[bool, str]:
    expected = case.get("expected_product_ids") or []
    cited = set((response or {}).get("cited_product_ids") or []) | set(
        (response or {}).get("citations") or []
    )
    missing = [p for p in expected if p not in cited]
    if missing:
        return False, f"expected products not cited: {missing}"
    return True, "all expected products cited"


GRADERS: dict[str, Callable] = {
    "output_shape": grade_output_shape,
    "figure_match": grade_figure_match,
    "citation_validity": grade_citation_validity,
    "forbidden_phrases": grade_forbidden_phrases,
    "expected_products": grade_expected_products,
}


def grade_case(case: dict, response: dict) -> dict:
    results = {}
    for name, fn in GRADERS.items():
        try:
            passed, detail = fn(case, response)
        except Exception as exc:  # graders must not crash the run
            passed, detail = False, f"grader error: {exc}"
        results[name] = {"passed": bool(passed), "detail": detail}
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(r["passed"] for r in results.values()),
        "graders": results,
    }


def recall_at_k(relevant: list[str], retrieved: list[str], k: int = 10) -> float:
    """Retrieval Recall@k against any retriever's returned chunk ids."""
    if not relevant:
        return 1.0
    top = set((retrieved or [])[:k])
    return len(set(relevant) & top) / len(set(relevant))


def grade_retrieval(
    case: dict, retriever: Callable[[str, int], list[str]] | None, k: int = 10
) -> dict | None:
    """Hook: pass a ``retriever(question, k) -> [chunk_id]`` callable.

    Wire to the retrieval app (parallel branch) via import guard, e.g.::

        try:
            from retrieval.service import search_chunk_ids as retriever
        except ImportError:
            retriever = None

    Returns None (skipped, not failed) when no retriever is available.
    """
    relevant = case.get("relevant_chunk_ids") or []
    if retriever is None or not relevant:
        return None
    score = recall_at_k(relevant, retriever(case["question"], k), k)
    return {"recall_at_k": score, "k": k, "passed": score > 0}
