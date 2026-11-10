"""Retrieval service: embedding ingestion + filtered vector/FTS search.

Filter contract (applied in SQL, on the Chunk queryset):
    filters = {
        "product_type": "credit_card" | "deposit" | "loan" | "account" | "content",
        "bank": <bank id int> or <bank name substring str>,
        "is_islamic": True | False,
    }
"""

import hashlib
import logging

from django.db import transaction

logger = logging.getLogger(__name__)

RRF_K = 60  # reciprocal-rank-fusion constant (standard value)


def content_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalise_filters(filters):
    """Validate/coerce a filters dict; unknown keys are dropped."""
    filters = dict(filters or {})
    out = {}
    if filters.get("product_type"):
        out["product_type"] = str(filters["product_type"])
    bank = filters.get("bank")
    if bank is not None and bank != "":
        out["bank"] = bank
    if filters.get("is_islamic") is not None:
        value = filters["is_islamic"]
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        out["is_islamic"] = bool(value)
    return out


def apply_filters(queryset, filters):
    """Apply normalised filters to a Chunk queryset (SQL-level)."""
    filters = normalise_filters(filters)
    if "product_type" in filters:
        queryset = queryset.filter(product_type=filters["product_type"])
    if "bank" in filters:
        bank = filters["bank"]
        if isinstance(bank, int) or (isinstance(bank, str) and bank.isdigit()):
            queryset = queryset.filter(bank_id=int(bank))
        else:
            queryset = queryset.filter(bank_name__icontains=str(bank))
    if "is_islamic" in filters:
        queryset = queryset.filter(is_islamic=filters["is_islamic"])
    return queryset


def citation_for_chunk(chunk, score=None):
    return {
        "product_id": chunk.product_id,
        "product_type": chunk.product_type,
        "field": chunk.field,
        "url_path": chunk.url_path,
        "snippet": chunk.text[:280],
        "bank_name": chunk.bank_name,
        "score": score,
    }


def upsert_document(document_data, provider, run=None):
    """Chunk + embed one rendered document if its content changed.

    Returns (SourceDocument, changed: bool, chunks_written: int).
    Idempotent: an unchanged content hash is a no-op.
    """
    from retrieval.chunking import chunk_sections
    from retrieval.documents import canonical_text
    from retrieval.models import SourceDocument

    text = canonical_text(document_data["sections"])
    digest = content_hash(text)
    doc, _created = SourceDocument.objects.get_or_create(
        product_type=document_data["product_type"],
        product_id=document_data["product_id"],
        source_kind=document_data.get("source_kind", "catalogue"),
        defaults={
            "title": document_data.get("title", ""),
            "bank_id": document_data.get("bank_id"),
            "bank_name": document_data.get("bank_name", ""),
            "is_islamic": document_data.get("is_islamic", False),
            "url_path": document_data.get("url_path", ""),
            "content_hash": digest,
            "text": text,
        },
    )
    if not _created and doc.content_hash == digest:
        return doc, False, 0

    chunks = chunk_sections(document_data["sections"])
    vectors = provider.embed([c["text"] for c in chunks]) if chunks else []
    with transaction.atomic():
        doc.title = document_data.get("title", "")
        doc.bank_id = document_data.get("bank_id")
        doc.bank_name = document_data.get("bank_name", "")
        doc.is_islamic = document_data.get("is_islamic", False)
        doc.url_path = document_data.get("url_path", "")
        doc.content_hash = digest
        doc.text = text
        doc.version = (doc.version or 0) + 1
        doc.save()
        doc.chunks.filter(embedding_model=provider.embedding_model).delete()
        from retrieval.models import Chunk

        created = Chunk.objects.bulk_create(
            [
                Chunk(
                    document=doc,
                    ordinal=c["ordinal"],
                    field=c["field"],
                    text=c["text"],
                    token_count=c["token_count"],
                    embedding=vector,
                    embedding_model=provider.embedding_model,
                    product_type=doc.product_type,
                    product_id=doc.product_id,
                    bank_id=doc.bank_id,
                    bank_name=doc.bank_name,
                    is_islamic=doc.is_islamic,
                    url_path=doc.url_path,
                )
                for c, vector in zip(chunks, vectors)
            ]
        )
        if created:
            # Populate the FTS column for hybrid search.
            from django.contrib.postgres.search import SearchVector

            Chunk.objects.filter(pk__in=[c.pk for c in created]).update(
                search_vector=SearchVector("text", config="english")
            )
    if run is not None:
        run.documents_changed += 1
        run.chunks_written += len(chunks)
        run.tokens += sum(c["token_count"] for c in chunks)
    return doc, True, len(chunks)


def handle_product_changed(event, provider=None):
    """Entry point for a product.changed event (Kafka stream calls this).

    Accepts the streaming envelope ``{"payload": {...}}`` or a flat dict
    with keys: product_type, product_id, change_type
    (created|updated|verified|deleted). Deliberately has no dependency on
    the streaming app — it is a plain function over a dict.
    """
    from common.embeddings.services import get_embedding_provider
    from retrieval.documents import build_document_for
    from retrieval.models import EmbeddingRun, SourceDocument

    payload = {}
    if isinstance(event, dict):
        payload = (
            event.get("payload") if isinstance(event.get("payload"), dict) else event
        )
    product_type = payload.get("product_type")
    product_id = payload.get("product_id")
    change_type = payload.get("change_type", "updated")
    if not product_type or product_id is None:
        return {"status": "ignored", "reason": "missing product_type/product_id"}

    if change_type == "deleted":
        deleted, _ = SourceDocument.objects.filter(
            product_type=product_type, product_id=product_id
        ).delete()
        return {"status": "deleted", "documents_deleted": deleted}

    document_data = build_document_for(product_type, int(product_id))
    if document_data is None:
        # Not public/verified (or unknown type): nothing may be embedded.
        deleted, _ = SourceDocument.objects.filter(
            product_type=product_type, product_id=product_id
        ).delete()
        return {"status": "skipped_not_public", "documents_deleted": deleted}

    provider = provider or get_embedding_provider()
    run = EmbeddingRun.objects.create(
        trigger=EmbeddingRun.Trigger.PRODUCT_CHANGED,
        provider=provider.provider_name,
        embedding_model=provider.embedding_model,
        documents_seen=1,
    )
    _doc, changed, chunks = upsert_document(document_data, provider, run=run)
    run.save()
    return {
        "status": "embedded" if changed else "unchanged",
        "chunks_written": chunks,
        "run_id": run.pk,
    }


def _vector_results(query_vector, filters, limit, embedding_model=None):
    from pgvector.django import CosineDistance

    from retrieval.models import Chunk

    queryset = apply_filters(Chunk.objects.all(), filters)
    if embedding_model:
        queryset = queryset.filter(embedding_model=embedding_model)
    return list(
        queryset.annotate(distance=CosineDistance("embedding", query_vector)).order_by(
            "distance"
        )[:limit]
    )


def _fts_results(query, filters, limit):
    from django.contrib.postgres.search import SearchQuery, SearchRank

    from retrieval.models import Chunk

    queryset = apply_filters(Chunk.objects.all(), filters)
    search_query = SearchQuery(query, config="english")
    return list(
        queryset.annotate(rank=SearchRank("search_vector", search_query))
        .filter(search_vector=search_query)
        .order_by("-rank")[:limit]
    )


def merge_rrf(ranked_lists, k, rrf_k=RRF_K):
    """Reciprocal-rank fusion over lists of chunks (pure, testable)."""
    scores = {}
    chunks = {}
    for results in ranked_lists:
        for rank, chunk in enumerate(results):
            scores[chunk.pk] = scores.get(chunk.pk, 0.0) + 1.0 / (rrf_k + rank + 1)
            chunks[chunk.pk] = chunk
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:k]
    return [(chunks[pk], score) for pk, score in ordered]


def search(query, filters=None, k=10, hybrid=False, provider=None):
    """Semantic search over embedded catalogue chunks.

    Returns a list of citation dicts (see citation_for_chunk) ordered by
    relevance. Cosine-only by default; hybrid=True fuses vector and
    Postgres full-text rankings with reciprocal-rank fusion.
    """
    from common.embeddings.services import get_embedding_provider

    if not query or not str(query).strip():
        return []
    k = max(1, min(int(k or 10), 50))
    filters = normalise_filters(filters)
    provider = provider or get_embedding_provider()
    query_vector = provider.embed_one(str(query))

    if not hybrid:
        results = _vector_results(
            query_vector, filters, k, embedding_model=provider.embedding_model
        )
        return [
            citation_for_chunk(chunk, score=1.0 - float(chunk.distance))
            for chunk in results
        ]

    fetch = k * 3
    vector_hits = _vector_results(
        query_vector, filters, fetch, embedding_model=provider.embedding_model
    )
    try:
        fts_hits = _fts_results(str(query), filters, fetch)
    except Exception:  # FTS unavailable (e.g. non-Postgres dev DB): degrade.
        logger.exception("FTS leg of hybrid search failed; using vector only")
        fts_hits = []
    merged = merge_rrf([vector_hits, fts_hits], k)
    return [citation_for_chunk(chunk, score=score) for chunk, score in merged]
