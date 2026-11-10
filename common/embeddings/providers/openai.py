"""OpenAI embedding provider (openai SDK, already a BE dependency)."""

import logging

from django.conf import settings

from common.embeddings.base import BaseEmbeddingProvider, normalise

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Defaults to text-embedding-3-small; dimension is requested explicitly."""

    def __init__(self, dimension=384, model=None):
        model = model or getattr(
            settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        super().__init__("openai", model, dimension)
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key)
        return self._client

    def embed(self, texts):
        client = self._get_client()
        vectors = []
        for start in range(0, len(texts), 100):
            batch = list(texts[start : start + 100])
            result = client.embeddings.create(
                model=self.model, input=batch, dimensions=self.dimension
            )
            for item in result.data:
                vectors.append(normalise(item.embedding, self.dimension))
        return vectors
