"""Test doubles for the search service (no engine required)."""


class FakeEngineClient:
    """Minimal in-memory stand-in for the Elasticsearch Python client.

    It only implements the surface used by :class:`search.service.SearchService`
    so unit tests can assert on real request payloads.
    """

    def __init__(self):
        self.indexes = {}
        self.bulk_actions = []
        self.search_calls = []
        self.indices = FakeIndices(self)
        self.fail_next_bulk = False

    # -- documents ---------------------------------------------------
    def index(self, index, id, document, refresh=False):  # noqa: A002
        self.indexes.setdefault(index, {})[id] = document
        return {"result": "created", "_id": id}

    def delete(self, index, id, ignore=None, refresh=False):  # noqa: A002
        self.indexes.setdefault(index, {}).pop(id, None)
        return {"result": "deleted", "_id": id}

    def bulk(self, operations=None, refresh=False):  # noqa: A002
        if self.fail_next_bulk:
            self.fail_next_bulk = False
            raise RuntimeError("engine is down")
        return {"errors": False, "items": []}

    def search(self, index, body):
        self.search_calls.append({"index": index, "body": body})
        return {"took": 1, "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}

    def count(self, index):
        return {"count": len(self.indexes.get(index, {}))}

    def ping(self, request_timeout=None):
        return True

    def info(self):
        return {"version": {"number": "8.19.3", "build_flavor": "default"}}


class FakeIndices:
    """Sub-object implementing the ``client.indices`` namespace."""

    def __init__(self, owner):
        self.owner = owner

    def exists(self, index):
        return index in self.owner.indexes

    def create(self, index, body=None):
        self.owner.indexes.setdefault(index, {})
        self.owner.indexes[index]["__settings__"] = body
        return {"acknowledged": True, "index": index}

    def delete(self, index, ignore=None):
        self.owner.indexes.pop(index, None)
        return {"acknowledged": True}

    def put_settings(self, index, body=None):
        self.owner.indexes.setdefault(index, {})["__settings__"] = body
        return {"acknowledged": True}

    def close(self, index):
        return {"acknowledged": True}

    def open(self, index):
        return {"acknowledged": True}

    def refresh(self, index):
        return {"_shards": {"successful": 1}}


class RecordingService:
    """A ``SearchService``-shaped double that records queued operations.

    Used by queue tests so ``drain()`` can be exercised without an engine.
    """

    def __init__(self, fail=False):
        self.indexed = {}
        self.deleted = {}
        self.refresh_calls = 0
        self.fail = fail
        self.created_indexes = []

    def create_index(self, kind):
        self.created_indexes.append(kind)
        return kind not in self.created_indexes[:-1]

    def bulk_index(self, index_name, documents):
        if self.fail:
            raise RuntimeError("engine is down")
        documents = list(documents)
        self.indexed.setdefault(index_name, {}).update(dict(documents))
        return {"indexed": len(documents), "errors": []}

    def delete_documents(self, index_name, object_ids):
        if self.fail:
            raise RuntimeError("engine is down")
        ids = [int(object_id) for object_id in object_ids]
        bucket = self.deleted.setdefault(index_name, [])
        bucket.extend(ids)
        store = self.indexed.get(index_name, {})
        for object_id in ids:
            store.pop(object_id, None)
        return {"deleted": len(ids), "errors": []}

    def refresh(self, index_name=None):
        self.refresh_calls += 1
