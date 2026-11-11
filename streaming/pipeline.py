"""Helpers for the crawl/nightly-sync path: emit crawl.fetched + extraction.requested via outbox.

Called additively from banks tasks when EVENT_STREAMING_ENABLED is on; a no-op otherwise,
so flag-off behaviour is byte-identical to the current pipeline.
"""

from streaming.topics import CRAWL_FETCHED, EXTRACTION_REQUESTED


def emit_crawl_fetched(source, crawled_content=None, sync_run_id=None):
    from streaming.outbox import emit

    payload = {
        "source_id": source.pk,
        "url": source.url,
        "content_hash": getattr(crawled_content, "content_hash", "") or "",
        "fetched_at": "",
        "sync_run_id": sync_run_id,
    }
    emit(CRAWL_FETCHED, source.pk, payload, event_type="crawl.fetched")
    emit(
        EXTRACTION_REQUESTED,
        source.pk,
        {
            "source_id": source.pk,
            "crawled_content_id": getattr(crawled_content, "pk", None),
            "purpose": getattr(source, "purpose", "credit_card"),
            "model_hint": "",
        },
        event_type="extraction.requested",
    )
