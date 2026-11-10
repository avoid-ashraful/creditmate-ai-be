"""Topic name constants."""
CRAWL_FETCHED="creditmate.crawl.fetched.v1"
EXTRACTION_REQUESTED="creditmate.extraction.requested.v1"
EXTRACTION_COMPLETED="creditmate.extraction.completed.v1"
PRODUCT_CHANGED="creditmate.product.changed.v1"
DLQ="creditmate.streaming.dlq.v1"
ALL_TOPICS=(CRAWL_FETCHED,EXTRACTION_REQUESTED,EXTRACTION_COMPLETED,PRODUCT_CHANGED,DLQ)
