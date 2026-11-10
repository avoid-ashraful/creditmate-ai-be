"""Ingestion consumer: extraction.completed -> ReviewQueue DRAFT ONLY.

HARD INVARIANT: this consumer must never create/update a verified product row
(CreditCard/DepositProduct/LoanProduct/AccountProduct). It only creates banks.ReviewQueue
items, which a human must approve through the existing gate. Guarded by
streaming.guard.assert_draft_only and a source-scan test.
"""
import logging
from streaming.consumers.base import BaseConsumer
from streaming.guard import assert_draft_only
from streaming.topics import EXTRACTION_COMPLETED
logger=logging.getLogger(__name__)
class IngestionConsumer(BaseConsumer):
    name="ingestion"; topics=(EXTRACTION_COMPLETED,)
    def handle(self, envelope):
        assert_draft_only(self.__class__)
        p=envelope.get("payload") or {}
        cc_id=p.get("crawled_content_id")
        if not cc_id: return
        from banks.enums import ReviewSource
        from banks.models import CrawledContent, ReviewQueue
        cc=CrawledContent.objects.select_related("data_source__bank").filter(pk=cc_id).first()
        if cc is None: return
        if ReviewQueue.objects.filter(crawled_content=cc).exists(): return
        ReviewQueue.objects.create(crawled_content=cc, source=ReviewSource.CRAWLER_PROPOSAL,
            bank=cc.data_source.bank, message=f"Draft from streaming ingestion (confidence={p.get('confidence')})")
