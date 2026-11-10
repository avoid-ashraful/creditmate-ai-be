"""Models for pgvector-backed semantic retrieval.

Only *published, verified* catalogue data is ever turned into a
SourceDocument (see retrieval.documents). Chunks denormalise the filter
fields (product_type, bank, is_islamic, field provenance) so retrieval
filters are applied in SQL on the chunk query itself — never by
post-filtering an unfiltered ANN result.
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from pgvector.django import HnswIndex, VectorField

from common.models import Audit

# Fixed at migration time. Runtime providers must produce exactly this
# many dimensions (hosted providers are asked for it explicitly; the
# local MiniLM model and the fake provider are natively 384).
EMBEDDING_DIMENSIONS = 384


class ProductType(models.TextChoices):
    CREDIT_CARD = "credit_card", "Credit card"
    DEPOSIT = "deposit", "Deposit"
    LOAN = "loan", "Loan"
    ACCOUNT = "account", "Bank account"
    CONTENT = "content", "Editorial / methodology content"


class SourceDocument(Audit):
    """One canonical text document rendered from a verified product."""

    product_type = models.CharField(
        max_length=20, choices=ProductType.choices, db_index=True
    )
    product_id = models.PositiveIntegerField(
        help_text="PK of the product in its own app (no cross-app FK)."
    )
    source_kind = models.CharField(
        max_length=30,
        default="catalogue",
        help_text="e.g. catalogue, methodology, bank_page.",
    )
    title = models.CharField(max_length=500, blank=True, default="")
    bank_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    bank_name = models.CharField(max_length=255, blank=True, default="")
    is_islamic = models.BooleanField(default=False, db_index=True)
    url_path = models.CharField(max_length=500, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, db_index=True)
    text = models.TextField(help_text="Canonical rendered text that was chunked.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product_type", "product_id", "source_kind"],
                name="retrieval_doc_unique_product_source",
            )
        ]
        indexes = [
            models.Index(
                fields=["product_type", "product_id"],
                name="retrieval_doc_product_idx",
            )
        ]

    def __str__(self):
        return f"{self.product_type}:{self.product_id} ({self.source_kind})"


class Chunk(Audit):
    """One embedded chunk of a SourceDocument, with field provenance."""

    document = models.ForeignKey(
        SourceDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    ordinal = models.PositiveIntegerField()
    field = models.CharField(
        max_length=60,
        help_text="Provenance: the document section this chunk came from "
        "(e.g. fees, rewards, eligibility) — used for citations.",
    )
    text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    embedding_model = models.CharField(max_length=120, db_index=True)
    search_vector = SearchVectorField(null=True, blank=True)

    # Denormalised filter/citation fields (copied from the document).
    product_type = models.CharField(
        max_length=20, choices=ProductType.choices, db_index=True
    )
    product_id = models.PositiveIntegerField(db_index=True)
    bank_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    bank_name = models.CharField(max_length=255, blank=True, default="")
    is_islamic = models.BooleanField(default=False, db_index=True)
    url_path = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "ordinal", "embedding_model"],
                name="retrieval_chunk_unique_ordinal_model",
            )
        ]
        indexes = [
            HnswIndex(
                name="retrieval_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(fields=["search_vector"], name="retrieval_chunk_fts_gin"),
            models.Index(
                fields=["product_type", "is_islamic"],
                name="retr_chunk_type_islamic_idx",
            ),
        ]

    def __str__(self):
        return f"chunk {self.document_id}#{self.ordinal} ({self.field})"


class EmbeddingRun(Audit):
    """Book-keeping for one embedding/backfill run."""

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual / management command"
        PRODUCT_CHANGED = "product_changed", "product.changed event"
        KAFKA = "kafka", "Kafka consumer"

    trigger = models.CharField(
        max_length=20, choices=Trigger.choices, default=Trigger.MANUAL
    )
    provider = models.CharField(max_length=30, blank=True, default="")
    embedding_model = models.CharField(max_length=120, blank=True, default="")
    documents_seen = models.PositiveIntegerField(default=0)
    documents_changed = models.PositiveIntegerField(default=0)
    chunks_written = models.PositiveIntegerField(default=0)
    tokens = models.PositiveIntegerField(
        default=0, help_text="Approximate tokens embedded (chunker estimate)."
    )
    status = models.CharField(max_length=20, default="completed")
    note = models.CharField(max_length=500, blank=True, default="")

    def __str__(self):
        return f"EmbeddingRun {self.pk} ({self.trigger}, {self.status})"
