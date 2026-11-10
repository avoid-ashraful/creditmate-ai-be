"""Code-level guard for the draft-only invariant for streaming consumers."""
import inspect
FORBIDDEN_TOKENS=("VerificationStatus.VERIFIED","is_verified=True","verification_status =")
class VerifiedWriteError(RuntimeError): pass
def assert_draft_only(consumer_cls):
    src=inspect.getsource(consumer_cls)
    for tok in FORBIDDEN_TOKENS:
        if tok in src: raise VerifiedWriteError(f"{consumer_cls.__name__} references forbidden token {tok}")
    return True
def scan_consumer_sources():
    from streaming.consumers.extraction import ExtractionConsumer
    from streaming.consumers.ingestion import IngestionConsumer
    return {"extraction": assert_draft_only(ExtractionConsumer), "ingestion": assert_draft_only(IngestionConsumer)}
