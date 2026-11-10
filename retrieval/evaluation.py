"""Retrieval-quality evaluation harness (golden queries -> Recall@k / MRR).

Golden set format (retrieval/fixtures/golden_queries.json): each case is
    {"query": str, "filters": {...},
     "relevant": [{"product_type": ..., "product_id": ...}],   # optional
     "expected_keywords": [str, ...]}                          # optional

A case is scored on whichever ground truth it carries:
- relevant ids  -> Recall@k and reciprocal rank over retrieved citations;
- expected_keywords -> fraction of keywords found in the top-k snippets.
Cases with neither are skipped (reported as such).
"""

import json
from pathlib import Path

DEFAULT_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden_queries.json"


def load_golden(path=None):
    with open(path or DEFAULT_GOLDEN_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["queries"] if isinstance(data, dict) else data


def recall_at_k(retrieved_keys, relevant_keys, k):
    if not relevant_keys:
        return None
    top = set(retrieved_keys[:k])
    return len(top & set(relevant_keys)) / len(set(relevant_keys))


def reciprocal_rank(retrieved_keys, relevant_keys):
    relevant = set(relevant_keys)
    for idx, key in enumerate(retrieved_keys):
        if key in relevant:
            return 1.0 / (idx + 1)
    return 0.0


def _result_key(citation):
    return (citation.get("product_type"), citation.get("product_id"))


def evaluate(search_fn, golden=None, ks=(5, 10)):
    """Run search_fn(query, filters, k=max(ks)) over the golden set.

    Returns a summary dict with per-k mean recall, mean keyword recall and
    MRR, plus per-case detail. ``search_fn`` is injected so the harness is
    unit-testable with a stub.
    """
    cases = golden if golden is not None else load_golden()
    max_k = max(ks)
    totals = {k: [] for k in ks}
    keyword_recalls = []
    rrs = []
    details = []
    for case in cases:
        citations = search_fn(case["query"], case.get("filters") or {}, max_k)
        keys = [_result_key(c) for c in citations]
        relevant = [
            (r.get("product_type"), r.get("product_id"))
            for r in case.get("relevant") or []
        ]
        entry = {"query": case["query"]}
        if relevant:
            for k in ks:
                value = recall_at_k(keys, relevant, k)
                totals[k].append(value)
                entry[f"recall@{k}"] = value
            rr = reciprocal_rank(keys, relevant)
            rrs.append(rr)
            entry["rr"] = rr
        keywords = case.get("expected_keywords") or []
        if keywords:
            blob = " ".join((c.get("snippet") or "") for c in citations).lower()
            hit = sum(1 for kw in keywords if kw.lower() in blob) / len(keywords)
            keyword_recalls.append(hit)
            entry["keyword_recall"] = hit
        details.append(entry)

    def _mean(values):
        return round(sum(values) / len(values), 4) if values else None

    summary = {
        "cases": len(cases),
        "scored_cases": len(rrs),
        "mrr": _mean(rrs),
        "mean_keyword_recall": _mean(keyword_recalls),
    }
    for k in ks:
        summary[f"mean_recall@{k}"] = _mean(totals[k])
    summary["details"] = details
    return summary


def compare_modes(query_provider=None):
    """Convenience: evaluate cosine vs hybrid against the live index.

    Used by the run_retrieval_eval management command in the consolidated
    test pass (needs a populated pgvector index; not run in unit tests).
    """
    from retrieval.services import search

    results = {}
    for hybrid in (False, True):
        label = "hybrid" if hybrid else "cosine"

        def _fn(query, filters, k, _hybrid=hybrid):
            return search(query, filters=filters, k=k, hybrid=_hybrid)

        results[label] = evaluate(_fn)
    return results
