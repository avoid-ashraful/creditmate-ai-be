"""Base interface for embedding providers.

Mirrors ``common/llm``: business code depends on this abstraction only,
never on a vendor SDK. Every provider returns L2-normalised vectors of
exactly ``dimension`` components, so vectors from different providers are
at least shape-compatible (they are still never mixed in one index
population — ``Chunk.embedding_model`` records which model produced each
vector and re-embedding is a full-population job, see retrieval docs).
"""

import math
from abc import ABC, abstractmethod


def normalise(vector, dimension):
    """Pad/truncate ``vector`` to ``dimension`` and L2-normalise it.

    Returns a list of floats. A zero vector is returned unchanged (it has
    no direction; cosine distance against it is undefined but harmless).
    """
    values = [float(v) for v in list(vector)[:dimension]]
    if len(values) < dimension:
        values.extend([0.0] * (dimension - len(values)))
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


class BaseEmbeddingProvider(ABC):
    """Abstract embedding provider."""

    def __init__(self, provider_name, model, dimension):
        self.provider_name = provider_name
        self.model = model
        self.dimension = int(dimension)

    @property
    def embedding_model(self):
        """Identifier stored on each Chunk, e.g. ``fake:fake-hash-v1``."""
        return f"{self.provider_name}:{self.model}"

    @abstractmethod
    def embed(self, texts):
        """Embed a list of texts -> list of normalised vectors (list[float])."""

    def embed_one(self, text):
        return self.embed([text])[0]
