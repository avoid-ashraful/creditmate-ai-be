"""Backfill (or refresh) embeddings for all public catalogue products.

Usage:
    python manage.py backfill_embeddings [--provider fake|gemini|openai|local]
                                         [--product-type credit_card]
                                         [--limit 20] [--force]

Idempotent: documents whose rendered content hash is unchanged are
skipped unless --force is given (force still re-uses the same upsert
path; pass --reembed-all semantics by clearing chunks is unnecessary —
--force simply bypasses the hash check by deleting stored documents
first for the selected scope).
"""

from django.core.management.base import BaseCommand

from common.embeddings.services import get_embedding_provider
from retrieval.documents import iter_public_documents
from retrieval.models import EmbeddingRun, SourceDocument
from retrieval.services import upsert_document


class Command(BaseCommand):
    help = "Chunk and embed public catalogue products into pgvector."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default=None)
        parser.add_argument("--product-type", default=None)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        provider = get_embedding_provider(options["provider"])
        if options["force"]:
            qs = SourceDocument.objects.all()
            if options["product_type"]:
                qs = qs.filter(product_type=options["product_type"])
            deleted, _ = qs.delete()
            self.stdout.write(f"--force: removed {deleted} stored documents")

        run = EmbeddingRun.objects.create(
            trigger=EmbeddingRun.Trigger.MANUAL,
            provider=provider.provider_name,
            embedding_model=provider.embedding_model,
        )
        seen = changed = 0
        for document_data in iter_public_documents(
            product_type=options["product_type"], limit=options["limit"]
        ):
            seen += 1
            _doc, did_change, _chunks = upsert_document(document_data, provider, run=run)
            changed += 1 if did_change else 0
        run.documents_seen = seen
        run.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"Embedding run {run.pk}: {seen} documents seen, "
                f"{run.documents_changed} changed, {run.chunks_written} chunks "
                f"written with {provider.embedding_model}."
            )
        )
