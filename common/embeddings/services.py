"""Provider factory for embeddings."""

from django.conf import settings


def get_embedding_provider(name=None, dimension=None):
    """Return an embedding provider instance.

    Provider name resolution: explicit argument, then
    ``settings.EMBEDDING_PROVIDER`` (default ``"gemini"``).
    Dimension: explicit argument, then ``settings.EMBEDDING_DIMENSIONS``
    (default 384 — matches MiniLM/fake and is requested explicitly from
    hosted providers, which support output-dimensionality).
    """
    name = (name or getattr(settings, "EMBEDDING_PROVIDER", "gemini") or "gemini").lower()
    if dimension is None:
        dimension = int(getattr(settings, "EMBEDDING_DIMENSIONS", 384))

    if name == "fake":
        from common.embeddings.providers.fake import FakeEmbeddingProvider

        return FakeEmbeddingProvider(dimension=dimension)
    if name == "gemini":
        from common.embeddings.providers.gemini import GeminiEmbeddingProvider

        return GeminiEmbeddingProvider(dimension=dimension)
    if name == "openai":
        from common.embeddings.providers.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(dimension=dimension)
    if name == "local":
        from common.embeddings.providers.local import LocalEmbeddingProvider

        return LocalEmbeddingProvider(dimension=dimension)
    raise ValueError(f"Unknown embedding provider: {name!r}")
