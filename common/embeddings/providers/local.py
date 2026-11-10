"""Local sentence-transformers provider (optional dependency).

``sentence-transformers`` is intentionally NOT a hard dependency: it pulls
in torch and model weights. Install it only on machines that run offline
embedding (CI/dev). Import failures raise a clear RuntimeError.
"""

import logging

from django.conf import settings

from common.embeddings.base import BaseEmbeddingProvider, normalise

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # native dim 384


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension=384, model=None):
        model = model or getattr(settings, "LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_MODEL)
        super().__init__("local", model, dimension)
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed; the local embedding "
                    "provider is optional (pip install sentence-transformers) — "
                    "use the fake provider for tests or gemini/openai otherwise."
                ) from exc
            self._model = SentenceTransformer(self.model)
        return self._model

    def embed(self, texts):
        model = self._get_model()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return [normalise(v, self.dimension) for v in vectors]
