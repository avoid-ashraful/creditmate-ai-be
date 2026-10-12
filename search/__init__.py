"""Search package: Elasticsearch index infrastructure for CreditMate AI.

This package owns everything search related:

* :mod:`search.documents` -- index settings (analyzers/synonyms) and mappings
* :mod:`search.client` -- engine client lifecycle and health
* :mod:`search.service` -- create/rebuild/search/index documents
* :mod:`search.queue` -- durable outbox queue (signal -> queue -> index)
* :mod:`search.signals` -- Django model signal wiring
* :mod:`search.tasks` -- Celery worker entry point
* :mod:`search.api` -- read-only search HTTP API

The engine chosen for this project is Elasticsearch because it is the only
option in the evaluated set with a first party Bengali language analyzer
(``{"type": "bengali"}``), synonym graph token filters and aggregatable
keyword/numeric facets.
"""

__all__ = [
    "client",
    "documents",
    "queue",
    "queries",
    "service",
    "signals",
    "tasks",
]
