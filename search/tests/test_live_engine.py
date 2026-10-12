"""Live engine tests: real Elasticsearch + real PostgreSQL.

These tests only run when ``SEARCH_LIVE=1`` is exported::

    SEARCH_LIVE=1 uv run pytest search/tests/test_live_engine.py -v

They use their own index prefix (``oc6_``) so they never touch another
worker's or a shared index, and they drop those indexes afterwards.
"""

import os

import pytest

from django.core.management import call_command
from django.test import override_settings

LIVE = os.getenv("SEARCH_LIVE") == "1"

pytestmark = [
    pytest.mark.skipif(
        not LIVE,
        reason="set SEARCH_LIVE=1 to run against a real Elasticsearch node",
    ),
]

PREFIX = "oc6_"


@pytest.fixture(autouse=True)
def live_socket(socket_enabled):
    """Allow sockets (pytest.ini runs with ``--disable-socket``)."""
    return socket_enabled


@pytest.fixture(autouse=True)
def isolated_indexes(settings):
    """Run every live test against its own prefixed, freshly built indexes."""
    settings.SEARCH_INDEX_PREFIX = PREFIX
    settings.SEARCH_SYNC_MODE = "queue"
    from search.service import SearchService

    service = SearchService()
    if not service.available or not service.client.ping():
        pytest.skip("search engine is not reachable on SEARCH_URL")
    service.drop_indexes()
    created = service.ensure_indexes()
    assert all(created.values()), f"indexes already existed: {created}"
    yield service
    service.drop_indexes()


def _make_bank(name, card_count=0):
    from banks.models import Bank

    return Bank.objects.create(name=name, website="https://example.com")


def _make_card(bank, **kwargs):
    from decimal import Decimal

    from credit_cards.models import CreditCard

    defaults = {
        "name": "Default Card",
        "annual_fee": None,
        "interest_rate_apr": None,
        "reward_points_policy": "",
        "additional_features": [],
        "is_active": True,
    }
    defaults.update(kwargs)
    if isinstance(defaults["annual_fee"], (int, float)):
        defaults["annual_fee"] = Decimal(str(defaults["annual_fee"]))
    if isinstance(defaults["interest_rate_apr"], (int, float)):
        defaults["interest_rate_apr"] = Decimal(str(defaults["interest_rate_apr"]))
    return CreditCard.objects.create(bank=bank, **defaults)


def _hits(result):
    return [hit["id"] for hit in result["hits"]]


class TestEngineReachability:
    def test_engine_is_elasticsearch_8(self, isolated_indexes):
        service = isolated_indexes
        info = service.client.info()
        assert info["version"]["number"].startswith("8.")
        assert service.available is True


class TestIndexDefinitions:
    def test_index_settings_contain_bengali_analyzer(self, isolated_indexes):
        service = isolated_indexes
        settings = service.client.indices.get_settings(index=f"{PREFIX}banks")
        analysis = settings[f"{PREFIX}banks"]["settings"]["index"]["analysis"]
        assert analysis["analyzer"]["creditmate_bengali"]["type"] == "bengali"
        assert (
            "bengali_normalization"
            in analysis["analyzer"]["creditmate_multilang"]["filter"]
        )
        assert (
            "creditmate_bengali_stemmer"
            in analysis["analyzer"]["creditmate_multilang"]["filter"]
        )

    def test_index_settings_contain_required_synonyms(self, isolated_indexes):
        service = isolated_indexes
        settings = service.client.indices.get_settings(index=f"{PREFIX}credit_cards")
        synonyms = settings[f"{PREFIX}credit_cards"]["settings"]["index"]["analysis"][
            "filter"
        ]["creditmate_synonyms"]["synonyms"]
        lowered = [item.lower() for item in synonyms]
        assert "visa, credit card" in lowered
        assert any(
            item.startswith("apr,") and "interest rate" in item for item in lowered
        )

    @pytest.mark.parametrize("kind", ["banks", "credit_cards"])
    def test_mapping_exposes_all_filterable_fields(self, isolated_indexes, kind):
        from search.documents import FILTERABLE_TYPES
        from search.queries import filterable_fields

        service = isolated_indexes
        index = f"{PREFIX}{kind}"
        mapping = service.client.indices.get_mapping(index=index)
        properties = mapping[index]["mappings"]["properties"]
        for path in filterable_fields(kind):
            node = properties
            parts = path.split(".")
            for position, part in enumerate(parts):
                assert part in node, f"{index}: missing {path}"
                node = node[part]
                if position < len(parts) - 1:
                    node = node.get("fields", {})
            assert (
                node.get("type") in FILTERABLE_TYPES
            ), f"{index}:{path} -> {node.get('type')} is not filterable"


class TestBengaliSearch:
    def test_bengali_document_is_found_with_bengali_query(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("ঢাকা ব্যাংক")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(
                bank,
                name="ক্রেডিট কার্ড",
                reward_points_policy="বাংলাদেশে সেরা রিওয়ার্ড",
            )
        service.index_document("banks", bank, refresh=True)
        service.index_document("credit_cards", card, refresh=True)

        result = service.search("cards", query="ক্রেডিট কার্ড")
        assert card.pk in _hits(result), "Bengali query found no document"

        result_bank = service.search("banks", query="ঢাকা")
        assert bank.pk in _hits(result_bank), "Bengali bank query found no document"

    def test_bengali_analyzer_normalizes_variants(self, isolated_indexes):
        """The engine's own analyzer output is asserted, not our JSON."""
        service = isolated_indexes
        response = service.client.indices.analyze(
            index=f"{PREFIX}credit_cards",
            body={"analyzer": "creditmate_bengali", "text": "ঢাকা ব্যাংকের কার্ড"},
        )
        tokens = [token["token"] for token in response["tokens"]]
        assert tokens
        assert any("কার্ড" in token for token in tokens)

    def test_multilang_analyzer_handles_bengali_and_english(self, isolated_indexes):
        service = isolated_indexes
        response = service.client.indices.analyze(
            index=f"{PREFIX}credit_cards",
            body={"analyzer": "creditmate_multilang", "text": "cashback ক্রেডিট কার্ড"},
        )
        tokens = [token["token"] for token in response["tokens"]]
        assert "cashback" in tokens
        assert "ক্রেডিট" in tokens


class TestSynonyms:
    def test_visa_matches_credit_card_document(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("Synonym Bank")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(bank, name="Platinum Credit Card", annual_fee=500)
        service.index_document("credit_cards", card, refresh=True)

        # The document says "credit card", the user types "visa".
        result = service.search("cards", query="visa")
        assert card.pk in _hits(result), "query 'visa' did not find the credit card"

    def test_credit_card_query_finds_visa_document(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("Synonym Bank 4")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(bank, name="SkyBlue Visa", annual_fee=300)
        service.index_document("credit_cards", card, refresh=True)

        # The document says "visa", the user types "credit card".
        result = service.search("cards", query="credit card")
        assert card.pk in _hits(result), "query 'credit card' did not find the visa card"

    def test_apr_matches_interest_rate_document(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("Synonym Bank 2")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(
                bank,
                name="Plain Card",
                reward_points_policy="interest rate 18% on revolving balance",
            )
        service.index_document("credit_cards", card, refresh=True)

        result = service.search("cards", query="apr")
        assert card.pk in _hits(result), "query 'apr' did not match 'interest rate'"

    def test_reverse_synonym_apr_matches_document_mentioning_apr(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("Synonym Bank 3")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(bank, name="Rate Card", reward_points_policy="apr 22.5%")
        service.index_document("credit_cards", card, refresh=True)
        result = service.search("cards", query="interest rate")
        assert card.pk in _hits(result)

    def test_synonym_tokens_are_produced_by_the_engine(self, isolated_indexes):
        service = isolated_indexes
        response = service.client.indices.analyze(
            index=f"{PREFIX}credit_cards",
            body={"analyzer": "creditmate_multilang", "text": "visa apr"},
        )
        tokens = {token["token"] for token in response["tokens"]}
        assert {"credit", "card"} <= tokens, tokens
        assert {"interest", "rate"} <= tokens, tokens

    def test_multi_word_synonym_sources_can_be_indexed(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ) -> None:
        """Regression guard for an Elasticsearch 8.19 indexing bug.

        ``search_as_you_type`` combined with the ``synonym_graph`` filter
        rejects a document as soon as its text contains a multi word synonym
        source, with::

            400 illegal_argument_exception: first position increment must be
            > 0 (got 0) for field 'name._3gram'

        The prefix suggest fields therefore run on a synonym free analyzer;
        this asserts both documents index cleanly.
        """
        service = isolated_indexes
        bank = _make_bank("Multiword Bank")
        with django_capture_on_commit_callbacks(execute=True):
            transfer = _make_card(bank, name="Balance Transfer Credit Card")
            rate = _make_card(bank, name="Low Interest Rate Card")
        service.index_document("credit_cards", transfer, refresh=True)
        service.index_document("credit_cards", rate, refresh=True)
        assert service.count(f"{PREFIX}credit_cards") == 2
        assert transfer.pk in _hits(service.search("cards", query="visa"))
        assert rate.pk in _hits(service.search("cards", query="apr"))


class TestFiltersAndFacets:
    @pytest.fixture()
    def three_cards(self, isolated_indexes, django_capture_on_commit_callbacks, db):
        """Three cards: paid, genuinely free and unknown fee."""
        service = isolated_indexes
        bank = _make_bank("Filter Bank")
        with django_capture_on_commit_callbacks(execute=True):
            paid = _make_card(
                bank, name="Paid Card", annual_fee=1500, interest_rate_apr=24
            )
            free = _make_card(bank, name="Free Card", annual_fee=0, interest_rate_apr=20)
            unknown = _make_card(bank, name="Unknown Fee Card", annual_fee=None)
        for card in (paid, free, unknown):
            service.index_document("credit_cards", card, refresh=True)
        return {"paid": paid, "free": free, "unknown": unknown}

    def test_no_annual_fee_filter_excludes_unknown(self, three_cards, isolated_indexes):
        service = isolated_indexes
        result = service.search("cards", filters={"no_annual_fee": True})
        assert _hits(result) == [three_cards["free"].pk]

    def test_has_annual_fee_false_excludes_unknown(self, three_cards, isolated_indexes):
        service = isolated_indexes
        result = service.search("cards", filters={"has_annual_fee": False})
        assert _hits(result) == [three_cards["free"].pk]

    def test_annual_fee_unknown_filter_returns_only_unknown(
        self, three_cards, isolated_indexes
    ):
        service = isolated_indexes
        result = service.search("cards", filters={"annual_fee_unknown": True})
        assert _hits(result) == [three_cards["unknown"].pk]

    def test_range_filter_and_aggregations(self, three_cards, isolated_indexes):
        service = isolated_indexes
        result = service.search("cards", filters={"annual_fee_min": 1000})
        assert _hits(result) == [three_cards["paid"].pk]

        # Facets are always computed on the unfiltered query so they can be
        # used as navigation counts by the UI.
        global_result = service.search("cards", query=None)
        aggs = global_result["aggregations"]
        known = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs["annual_fee_known"]["buckets"]
        }
        assert known == {True: 2, False: 1}
        has_fee = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs["has_annual_fee"]["buckets"]
        }
        # Unknown fee is not indexed, so it never appears in this facet.
        assert has_fee == {True: 1, False: 1}
        free_bucket = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs["annual_fee_ranges"]["buckets"]
        }
        assert free_bucket["free"] == 1

    def test_bank_and_feature_filters(self, three_cards, isolated_indexes, db):
        service = isolated_indexes
        bank = three_cards["paid"].bank
        result = service.search("cards", filters={"bank_id": bank.pk})
        assert sorted(_hits(result)) == sorted(card.pk for card in three_cards.values())
        result = service.search("cards", filters={"is_active": True})
        assert len(_hits(result)) == 3
        result = service.search("cards", filters={"is_active": False})
        assert _hits(result) == []

    def test_aggregate_on_bank_name_facet(self, three_cards, isolated_indexes):
        service = isolated_indexes
        result = service.search("cards", query=None)
        buckets = {
            bucket["key"]: bucket["doc_count"]
            for bucket in result["aggregations"]["bank_name"]["buckets"]
        }
        assert buckets == {"Filter Bank": 3}


class TestSignalQueueIndexFlow:
    def test_save_then_drain_then_delete(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        """Full ``signal -> transaction commit -> queue -> index`` path."""
        from search.models import SearchIndexUpdate
        from search.queue import drain

        service = isolated_indexes

        # 1. Create: the signal must queue, not touch the engine.
        with django_capture_on_commit_callbacks(execute=True):
            bank = _make_bank("Queue Bank")
            card = _make_card(bank, name="Queued Card", annual_fee=900)
        assert SearchIndexUpdate.objects.count() == 2
        assert SearchIndexUpdate.objects.filter(
            object_id=card.pk, action="index"
        ).exists()

        # 2. Drain: rows go to the real engine and are marked done.
        summary = drain()
        assert summary["processed"] == 2
        assert summary["indexed"] == 2
        assert summary["failed"] == 0
        assert summary["remaining"] == 0
        assert SearchIndexUpdate.objects.filter(status="pending").count() == 0
        assert service.count(f"{PREFIX}credit_cards") == 1
        assert service.search("cards", query="Queued Card")["total"] >= 1

        # 3. Update: a new row is queued and the document is refreshed.
        with django_capture_on_commit_callbacks(execute=True):
            card.name = "Queued Card V2"
            card.save()
        summary = drain()
        assert summary["indexed"] == 1
        refreshed = service.client.mget(index=f"{PREFIX}credit_cards", ids=[card.pk])
        assert refreshed["docs"][0]["found"] is True
        assert refreshed["docs"][0]["_source"]["name"] == "Queued Card V2"

        # 4. Delete: document must disappear from the engine.
        card_pk = card.pk
        with django_capture_on_commit_callbacks(execute=True):
            card.delete()
        assert SearchIndexUpdate.objects.filter(action="delete").count() == 1
        summary = drain()
        assert summary["deleted"] == 1
        assert service.count(f"{PREFIX}credit_cards") == 0
        gone = service.client.mget(index=f"{PREFIX}credit_cards", ids=[card_pk])
        assert gone["docs"][0]["found"] is False

    def test_drain_creates_missing_indexes_with_full_analysis(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        """A fresh environment must not fall back to dynamic mappings.

        When the index is missing the engine would auto-create it from the
        first bulk action, which silently drops the analyzers, synonyms and
        filterable fields (and leaves the cluster yellow on a single node).
        """
        from search.queue import drain

        service = isolated_indexes
        service.drop_indexes()
        assert service.index_exists(f"{PREFIX}credit_cards") is False

        with django_capture_on_commit_callbacks(execute=True):
            bank = _make_bank("Fresh Env Bank")
            card = _make_card(bank, name="Platinum Credit Card", annual_fee=0)
        summary = drain()

        assert summary["indexed"] == 2
        assert summary["failed"] == 0
        assert service.index_exists(f"{PREFIX}credit_cards") is True

        analysis = service.client.indices.get_settings(index=f"{PREFIX}credit_cards")[
            f"{PREFIX}credit_cards"
        ]["settings"]["index"]["analysis"]
        assert analysis["analyzer"]["creditmate_bengali"]["type"] == "bengali"
        assert "creditmate_synonyms" in analysis["filter"]
        assert (
            "bengali_normalization"
            in analysis["analyzer"]["creditmate_multilang"]["filter"]
        )
        assert (
            service.client.cluster.health(index=f"{PREFIX}credit_cards")["status"]
            == "green"
        )
        # Synonyms and the real mapping are live on the rebuilt index.
        assert service.search("cards", query="visa")["total"] == 1

    def test_engine_outage_keeps_rows_pending(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        """A broken engine must never lose queued work."""
        from search.models import SearchIndexUpdate
        from search.queue import drain, pending_count
        from search.tests.fakes import RecordingService

        with django_capture_on_commit_callbacks(execute=True):
            bank = _make_bank("Outage Bank")
        assert pending_count() == 1

        summary = drain(service=RecordingService(fail=True))
        assert summary["failed"] == 1
        assert summary["errors"]
        row = SearchIndexUpdate.objects.get()
        assert row.status == SearchIndexUpdate.STATUS_PENDING
        assert row.attempts == 1
        assert "engine is down" in row.last_error
        # Backoff window: the row must not be picked up yet.
        assert drain()["processed"] == 0
        # Recovery: once the backoff expires a healthy engine drains the row.
        from django.utils import timezone

        row.available_at = timezone.now()
        row.save(update_fields=["available_at"])
        recovered = drain()
        assert recovered["processed"] == 1
        assert isolated_indexes.count(f"{PREFIX}banks") == 1


class TestRebuildCommand:
    def test_rebuild_indexes_everything_from_the_database(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        service = isolated_indexes
        bank = _make_bank("Rebuild Bank")
        with django_capture_on_commit_callbacks(execute=True):
            _make_card(bank, name="Rebuild Card 1", annual_fee=100)
            _make_card(bank, name="Rebuild Card 2", annual_fee=None)

        # Index one document, then rebuild from scratch.
        service.index_document("banks", bank, refresh=True)
        assert service.count(f"{PREFIX}credit_cards") == 0

        call_command("search_index", "--rebuild")

        assert service.count(f"{PREFIX}banks") == 1
        assert service.count(f"{PREFIX}credit_cards") == 2
        result = service.search("cards", query="Rebuild Card")
        assert result["total"] == 2

    def test_create_command_reports_filterable_fields(self, isolated_indexes, db, capsys):
        call_command("search_index", "--create")
        out = capsys.readouterr().out
        assert "filterable fields (cards)" in out
        assert "annual_fee_known" in out

    def test_status_command_reports_engine_and_queue(self, isolated_indexes, db, capsys):
        call_command("search_index", "--status")
        out = capsys.readouterr().out
        assert "engine: Elasticsearch 8." in out
        assert "queue depth" in out


class TestLiveApi:
    def test_search_endpoint_hits_real_engine(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        from rest_framework.test import APIClient

        service = isolated_indexes
        bank = _make_bank("API Bank")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(bank, name="API Credit Card", annual_fee=0)
        service.index_document("credit_cards", card, refresh=True)

        client = APIClient()
        response = client.get("/api/search/", {"q": "visa", "type": "cards"})
        assert response.status_code == 200, response.content
        payload = response.json()
        assert payload["results"]["cards"]["total"] >= 1

        status = client.get("/api/search/status/")
        assert status.status_code == 200
        assert status.json()["engine"]["number"].startswith("8.")

    def test_suggest_endpoint_hits_real_engine(
        self, isolated_indexes, django_capture_on_commit_callbacks, db
    ):
        from rest_framework.test import APIClient

        service = isolated_indexes
        bank = _make_bank("Suggest Bank")
        with django_capture_on_commit_callbacks(execute=True):
            card = _make_card(bank, name="SkyBlue Premier")
        service.index_document("credit_cards", card, refresh=True)

        response = APIClient().get("/api/search/suggest/", {"q": "skyb", "type": "cards"})
        assert response.status_code == 200
        suggestions = response.json()["suggestions"]
        assert suggestions
        assert suggestions[0]["text"] == "SkyBlue Premier"


def test_override_settings_helper_is_usable():
    """Sanity check that the override_settings import stays available."""
    with override_settings(SEARCH_SYNC_MODE="off"):
        from django.conf import settings

        assert settings.SEARCH_SYNC_MODE == "off"
