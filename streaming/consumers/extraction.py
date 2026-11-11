"""Extraction consumer: on extraction.requested, mark the CrawledContent extraction result and emit extraction.completed.

Delegates the heavy LLM work to the existing crawler pipeline when the content has not been
extracted yet (BankDataCrawlerService.crawl_bank_data_source); if parsed data already exists it
completes immediately. Either way it NEVER writes verified product data.
"""

import logging

from streaming.consumers.base import BaseConsumer
from streaming.topics import EXTRACTION_COMPLETED, EXTRACTION_REQUESTED

logger = logging.getLogger(__name__)


class ExtractionConsumer(BaseConsumer):
    name = "extraction"
    topics = (EXTRACTION_REQUESTED,)

    def handle(self, envelope):
        p = envelope.get("payload") or {}
        cc_id = p.get("crawled_content_id")
        source_id = p.get("source_id")
        from banks.models import CrawledContent

        cc = CrawledContent.objects.filter(pk=cc_id).first() if cc_id else None
        if cc is not None and not cc.parsed_json and source_id:
            from banks.services import BankDataCrawlerService

            BankDataCrawlerService().crawl_bank_data_source(source_id)
            cc.refresh_from_db()
        confidence = float(getattr(cc, "extraction_confidence", 0) or 0) if cc else 0.0
        from streaming.outbox import emit

        emit(
            EXTRACTION_COMPLETED,
            p.get("source_id") or "",
            {
                "crawled_content_id": cc_id,
                "source_id": source_id,
                "draft_payload_ref": f"crawled_content:{cc_id}" if cc_id else "",
                "confidence": confidence,
                "provider": p.get("model_hint") or "",
                "token_usage": {},
            },
            event_type="extraction.completed",
        )
