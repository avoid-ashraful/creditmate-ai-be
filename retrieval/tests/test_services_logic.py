"""Unit tests for filter normalisation, RRF merging and eval metrics.

These exercise pure logic only (reduced-testing pass): the SQL/ANN paths
run in the final consolidated test pass against a pgvector database.
"""

from types import SimpleNamespace

from retrieval.evaluation import evaluate, recall_at_k, reciprocal_rank
from retrieval.services import merge_rrf, normalise_filters


def test_normalise_filters_drops_unknown_and_coerces():
    out = normalise_filters(
        {"product_type": "credit_card", "is_islamic": "true", "bogus": 1, "bank": ""}
    )
    assert out == {"product_type": "credit_card", "is_islamic": True}


def test_normalise_filters_bank_kept():
    assert normalise_filters({"bank": 12}) == {"bank": 12}
    assert normalise_filters({"bank": "BRAC Bank"}) == {"bank": "BRAC Bank"}
    assert normalise_filters(None) == {}


def test_merge_rrf_prefers_items_ranked_high_in_both_lists():
    a = SimpleNamespace(pk=1)
    b = SimpleNamespace(pk=2)
    c = SimpleNamespace(pk=3)
    merged = merge_rrf([[a, b], [b, c]], k=3)
    assert merged[0][0] is b  # ranked in both lists
    assert {chunk.pk for chunk, _ in merged} == {1, 2, 3}


def test_recall_and_mrr():
    retrieved = [("credit_card", 1), ("credit_card", 2), ("credit_card", 3)]
    relevant = [("credit_card", 3)]
    assert recall_at_k(retrieved, relevant, 2) == 0.0
    assert recall_at_k(retrieved, relevant, 5) == 1.0
    assert reciprocal_rank(retrieved, relevant) == 1 / 3


def test_evaluate_with_stub_search():
    golden = [
        {
            "query": "q1",
            "relevant": [{"product_type": "credit_card", "product_id": 7}],
        },
        {"query": "q2", "expected_keywords": ["annual fee"]},
    ]

    def stub(query, filters, k):
        if query == "q1":
            return [{"product_type": "credit_card", "product_id": 7, "snippet": "x"}]
        return [
            {"product_type": "credit_card", "product_id": 1, "snippet": "Annual fee: 0"}
        ]

    summary = evaluate(stub, golden=golden)
    assert summary["mean_recall@5"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["mean_keyword_recall"] == 1.0
