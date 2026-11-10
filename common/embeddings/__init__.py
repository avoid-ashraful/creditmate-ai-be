"""Embedding provider abstraction (mirrors common/llm)."""

from common.embeddings.base import BaseEmbeddingProvider, normalise
from common.embeddings.services import get_embedding_provider

__all__ = ["BaseEmbeddingProvider", "normalise", "get_embedding_provider"]
