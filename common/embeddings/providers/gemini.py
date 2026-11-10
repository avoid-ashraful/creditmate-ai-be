"""Gemini embedding provider (google-genai SDK, already a BE dependency)."""

import logging

from django.conf import settings

from common.embeddings.base import BaseEmbeddingProvider, normalise

logger = logging.getLogger(__name__)


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension=384, model=None):
        model = model or getattr(
            settings, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
        )
        super().__init__("gemini", model, dimension)
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            from google import genai

            self._client = genai.Client(api_key=api_key)
        return self._client

    def embed(self, texts):
        from google.genai import types

        client = self._get_client()
        vectors = []
        # The API accepts a list of contents per call; keep batches modest.
        for start in range(0, len(texts), 100):
            batch = list(texts[start : start + 100])
            result = client.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(output_dimensionality=self.dimension),
            )
            for embedding in result.embeddings:
                vectors.append(normalise(embedding.values, self.dimension))
        return vectors
