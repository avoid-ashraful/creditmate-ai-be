"""Deterministic fake embedding provider for tests and offline runs.

Hashes word tokens into a fixed-dimension bag-of-words vector. Texts that
share words land close together, which is enough for retrieval unit tests
to exercise ranking/filter plumbing without a network, a key, or a model
download. It is NOT a semantic model and must never be used for measured
retrieval quality.
"""

import hashlib
import re

from common.embeddings.base import BaseEmbeddingProvider, normalise

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class FakeEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension=384):
        super().__init__("fake", "fake-hash-v1", dimension)

    def embed(self, texts):
        vectors = []
        for text in texts:
            vec = [0.0] * self.dimension
            for token in _TOKEN_RE.findall((text or "").lower()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[idx] += sign
            vectors.append(normalise(vec, self.dimension))
        return vectors
