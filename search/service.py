"""Search service: index lifecycle, synchronisation and query execution."""

import logging

from django.conf import settings

from search.client import SearchUnavailable, get_client, is_enabled
from search.documents import (
    BANK_INDEX_BODY,
    CREDIT_CARD_INDEX_BODY,
    SYNONYMS,
    bank_to_document,
    credit_card_to_document,
)
from search.queries import index_name as configured_index_name

logger = logging.getLogger(__name__)


def _bank_queryset():
    """Return the bank queryset used for bulk indexing.

    Returns
    -------
    QuerySet
        Banks annotated with their active credit card count.
    """
    from django.db import models

    from banks.models import Bank
    from credit_cards.constants import PUBLIC_BANK_CARD_Q

    return Bank.objects.annotate(
        active_credit_card_count=models.Count("credit_cards", filter=PUBLIC_BANK_CARD_Q)
    ).order_by("pk")


def _card_queryset():
    """Return the credit card queryset used for bulk indexing.

    Returns
    -------
    QuerySet
        Public cards with the related bank pre-selected.
    """
    from credit_cards.models import CreditCard

    return CreditCard.objects.select_related("bank").public().order_by("pk")


#: Logical kind -> index definition.  Index names are resolved at runtime so
#: ``SEARCH_INDEX_PREFIX`` and per-environment names stay supported.
_INDEX_SPECS = {
    "banks": {
        "body": BANK_INDEX_BODY,
        "serializer": bank_to_document,
        "queryset": _bank_queryset,
        "source_index": "banks",
    },
    "credit_cards": {
        "body": CREDIT_CARD_INDEX_BODY,
        "serializer": credit_card_to_document,
        "queryset": _card_queryset,
        "source_index": "credit_cards",
    },
}


class SearchService:
    """Thin service object in front of the Elasticsearch engine."""

    def __init__(self, client=None):
        """Create a service.

        Parameters
        ----------
        client : object | None
            Optional engine client (injected in tests).  When omitted the
            shared client from :mod:`search.client` is used lazily.
        """
        self._client = client

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    @property
    def client(self):
        """Return the engine client.

        Returns
        -------
        elasticsearch.Elasticsearch
            Shared client instance.

        Raises
        ------
        SearchUnavailable
            If the service is disabled or the client cannot be created.
        """
        if self._client is not None:
            return self._client
        return get_client()

    @property
    def available(self):
        """Return True when the service can be used.

        Returns
        -------
        bool
        """
        if not is_enabled():
            return False
        try:
            self.client
        except SearchUnavailable:
            return False
        return True

    def index_names(self):
        """Return the configured index names.

        Returns
        -------
        list of str
        """
        return [self.resolve_name(kind) for kind in _INDEX_SPECS]

    @staticmethod
    def resolve_name(kind):
        """Resolve a logical kind (``banks``/``credit_cards``) to an index name.

        Parameters
        ----------
        kind : str
            Logical index kind.

        Returns
        -------
        str
            Configured index name.
        """
        return configured_index_name(kind)

    def _spec(self, kind):
        """Return the index specification for a logical kind.

        Parameters
        ----------
        kind : str
            ``banks`` or ``credit_cards``.

        Returns
        -------
        dict
            Spec with ``body``, ``serializer`` and ``queryset``.
        """
        return _INDEX_SPECS[kind]

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------
    def index_exists(self, index_name):
        """Return True when an index exists.

        Parameters
        ----------
        index_name : str
            Resolved index name.

        Returns
        -------
        bool
        """
        return bool(self.client.indices.exists(index=index_name))

    def create_index(self, kind):
        """Create an index when missing.

        Parameters
        ----------
        kind : str
            ``banks`` or ``credit_cards``.

        Returns
        -------
        bool
            True when the index was created, False when it already existed.
        """
        index_name = self.resolve_name(kind)
        if self.index_exists(index_name):
            return False
        self.client.indices.create(index=index_name, body=self._spec(kind)["body"])
        logger.info("Created search index %s", index_name)
        return True

    def ensure_indexes(self):
        """Create both indexes when they are missing.

        Returns
        -------
        dict
            Mapping of index name to ``created`` flag.
        """
        result = {}
        for kind in _INDEX_SPECS:
            result[self.resolve_name(kind)] = self.create_index(kind)
        return result

    def apply_synonyms(self):
        """Re-apply the configured synonyms on closed indexes.

        Synonyms live in index settings, so Elasticsearch requires the index
        to be closed before settings can be updated.

        Returns
        -------
        dict
            Mapping of index name to the ``acknowledged`` flag.
        """
        result = {}
        for kind, spec in _INDEX_SPECS.items():
            index_name = self.resolve_name(kind)
            analysis = spec["body"]["settings"]["analysis"]
            if not self.index_exists(index_name):
                self.create_index(kind)
            self.client.indices.close(index=index_name)
            try:
                response = self.client.indices.put_settings(
                    index=index_name, body={"analysis": analysis}
                )
            finally:
                self.client.indices.open(index=index_name)
            result[index_name] = bool(response.get("acknowledged"))
        return result

    def drop_indexes(self):
        """Delete both indexes (used by the rebuild command).

        Returns
        -------
        dict
            Mapping of index name to the ``acknowledged`` flag.
        """
        result = {}
        for kind in _INDEX_SPECS:
            index_name = self.resolve_name(kind)
            if not self.index_exists(index_name):
                result[index_name] = False
                continue
            response = self.client.indices.delete(index=index_name)
            result[index_name] = bool(response.get("acknowledged"))
        return result

    # ------------------------------------------------------------------
    # Document writes
    # ------------------------------------------------------------------
    def index_document(self, kind, obj, refresh=False):
        """Index a single model instance.

        Parameters
        ----------
        kind : str
            ``banks`` or ``credit_cards``.
        obj : Model
            Instance to index. A non-public card is removed from the index
            instead.
        refresh : bool
            Refresh the index so the document is immediately searchable.

        Returns
        -------
        dict
            Engine response for the index (or delete) request.
        """
        if kind == "credit_cards" and not obj.is_public:
            return self.delete_document(kind, obj.pk, refresh=refresh)
        document = self._spec(kind)["serializer"](obj)
        return self.client.index(
            index=self.resolve_name(kind), id=obj.pk, document=document, refresh=refresh
        )

    def delete_document(self, kind, object_id, refresh=False):
        """Delete a single document.

        Parameters
        ----------
        kind : str
            ``banks`` or ``credit_cards``.
        object_id : int
            Document id to delete.
        refresh : bool
            Refresh the index after deletion.

        Returns
        -------
        dict
            Engine response for the delete request.
        """
        from elasticsearch import NotFoundError

        try:
            return self.client.delete(
                index=self.resolve_name(kind), id=object_id, refresh=refresh
            )
        except NotFoundError:
            # Deleting a document that does not exist is a no-op.
            return {"result": "not_found", "_id": object_id}

    def bulk_index(self, index_name, documents, refresh=True):
        """Bulk index (or delete) documents.

        Parameters
        ----------
        index_name : str
            Resolved target index name.
        documents : iterable of (id, document) | iterable of dict
            Either ``(pk, document)`` tuples or raw Elasticsearch actions.
        refresh : bool
            Refresh the index at the end of the bulk call.

        Returns
        -------
        dict
            Summary with ``indexed`` count and ``errors`` list.
        """
        from elasticsearch import helpers

        actions = []
        for item in documents:
            if isinstance(item, dict):
                action = dict(item)
                action.setdefault("_index", index_name)
                actions.append(action)
                continue
            object_id, document = item
            actions.append(
                {
                    "_op_type": "index",
                    "_index": index_name,
                    "_id": object_id,
                    "_source": document,
                }
            )
        if not actions:
            return {"indexed": 0, "errors": []}
        success, errors = helpers.bulk(
            self.client, actions, chunk_size=200, raise_on_error=False
        )
        if refresh and self.index_exists(index_name):
            self.client.indices.refresh(index=index_name)
        return {"indexed": success, "errors": errors}

    def delete_documents(self, index_name, object_ids, refresh=True):
        """Bulk delete documents.

        Parameters
        ----------
        index_name : str
            Resolved target index name.
        object_ids : iterable of int
            Document ids to delete.
        refresh : bool
            Refresh the index at the end of the bulk call.

        Returns
        -------
        dict
            Summary with ``deleted`` count and ``errors`` list.
        """
        from elasticsearch import helpers

        ids = [int(object_id) for object_id in object_ids]
        if not ids:
            return {"deleted": 0, "errors": []}
        actions = [
            {"_op_type": "delete", "_index": index_name, "_id": object_id}
            for object_id in ids
        ]
        success, errors = helpers.bulk(
            self.client, actions, chunk_size=200, raise_on_error=False
        )
        if refresh and self.index_exists(index_name):
            self.client.indices.refresh(index=index_name)
        return {"deleted": success, "errors": errors}

    def refresh(self, index_name=None):
        """Refresh one or both indexes.

        Parameters
        ----------
        index_name : str | None
            Index name, or ``None`` to refresh every managed index.

        Returns
        -------
        None
        """
        targets = [index_name] if index_name else self.index_names()
        for name in targets:
            if self.index_exists(name):
                self.client.indices.refresh(index=name)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def count(self, index_name=None):
        """Return document counts.

        Parameters
        ----------
        index_name : str | None
            Index name, or ``None`` to count both.

        Returns
        -------
        dict | int
            Mapping of index name to count, or a single count.
        """
        if index_name:
            return int(self.client.count(index=index_name).get("count", 0))
        return {
            name: int(self.client.count(index=name).get("count", 0))
            for name in self.index_names()
        }

    def search(self, kind, query=None, filters=None, page=1, page_size=20, ordering=None):
        """Run a search against one index.

        Parameters
        ----------
        kind : str
            ``banks`` or ``cards``.
        query : str | None
            Full text query.
        filters : dict | None
            Validated filters.
        page : int
            1 based page number.
        page_size : int
            Page size.
        ordering : str | None
            Django style ordering value.

        Returns
        -------
        dict
            Normalised result with ``total``, ``took``, ``hits`` and
            ``aggregations`` keys.
        """
        from search.queries import build_body

        index_name = configured_index_name("banks" if kind == "banks" else "credit_cards")
        body = build_body(
            kind,
            query=query,
            filters=filters,
            page=page,
            page_size=page_size,
            ordering=ordering,
        )
        response = self.client.search(index=index_name, body=body)
        return self._normalise(response)

    def suggest(self, kind, query, size=8):
        """Run a type ahead query.

        Parameters
        ----------
        kind : str
            ``banks`` or ``cards``.
        query : str
            Partial user input.
        size : int
            Maximum number of suggestions.

        Returns
        -------
        list of dict
            Suggestion dictionaries with ``id``, ``text`` and optional
            ``bank_name``/``bank_id`` keys.
        """
        from search.queries import build_suggest_body

        index_name = configured_index_name("banks" if kind == "banks" else "credit_cards")
        body = build_suggest_body(kind, query, size=size)
        if body is None:
            return []
        response = self.client.search(index=index_name, body=body)
        suggestions = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            suggestion = {"id": source.get("id"), "text": source.get("name")}
            if "bank_name" in source:
                suggestion["bank_name"] = source.get("bank_name")
                suggestion["bank_id"] = source.get("bank_id")
            suggestions.append(suggestion)
        return suggestions

    def _normalise(self, response):
        """Normalise an engine response into a stable payload.

        Parameters
        ----------
        response : dict
            Raw engine response.

        Returns
        -------
        dict
            Normalised payload.
        """
        hits = response.get("hits", {})
        total = hits.get("total", {})
        documents = []
        for hit in hits.get("hits", []):
            source = dict(hit.get("_source", {}))
            source["_score"] = hit.get("_score")
            documents.append(source)
        if isinstance(total, dict):
            total_value = total.get("value", len(documents))
        else:
            total_value = total
        return {
            "total": total_value,
            "took": response.get("took", 0),
            "hits": documents,
            "aggregations": response.get("aggregations", {}),
        }

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------
    def rebuild(self, batch_size=500, drop=True):
        """Rebuild both indexes from the database.

        Parameters
        ----------
        batch_size : int
            Number of documents per bulk call.
        drop : bool
            Delete and recreate the index definitions first.

        Returns
        -------
        dict
            Per index summary with ``documents`` count and ``errors``.
        """
        from elasticsearch import helpers

        summary = {}
        for kind, spec in _INDEX_SPECS.items():
            index_name = self.resolve_name(kind)
            if drop and self.index_exists(index_name):
                self.client.indices.delete(index=index_name)
            self.create_index(kind)
            queryset = spec["queryset"]()
            serializer = spec["serializer"]

            def actions(name=index_name, serializer=serializer, queryset=queryset):
                for obj in queryset.iterator(chunk_size=batch_size):
                    yield {
                        "_op_type": "index",
                        "_index": name,
                        "_id": obj.pk,
                        "_source": serializer(obj),
                    }

            success, failures = helpers.bulk(
                self.client, actions(), chunk_size=batch_size, raise_on_error=False
            )
            self.client.indices.refresh(index=index_name)
            summary[index_name] = {"documents": success, "errors": list(failures or [])}
        return summary

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def status(self):
        """Return engine and index status for diagnostics.

        Returns
        -------
        dict
            Status payload including engine version, index health, document
            counts and pending queue depth.
        """
        from search import client as client_module
        from search.queue import pending_count

        payload = {
            "enabled": is_enabled(),
            "url": getattr(settings, "SEARCH_URL", None),
            "synonyms": list(SYNONYMS),
            "indexes": {},
            "pending_queue_rows": pending_count(),
        }
        try:
            payload["engine"] = client_module.engine_info()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not raise
            payload["engine_error"] = str(exc)
        for kind in _INDEX_SPECS:
            name = self.resolve_name(kind)
            info = {"kind": kind, "exists": self.index_exists(name)}
            if info["exists"]:
                info["count"] = int(self.client.count(index=name).get("count", 0))
                try:
                    info["health"] = self.client.cluster.health(index=name).get("status")
                except Exception:  # noqa: BLE001 - optional diagnostics
                    info["health"] = None
            payload["indexes"][name] = info
        return payload
