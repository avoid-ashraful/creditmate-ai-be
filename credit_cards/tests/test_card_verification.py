"""Tests for card verification gating, report-issue, admin actions and I/O commands."""

import json

import pytest

from django.contrib.auth.models import User
from django.core.management import call_command

from banks.enums import ReviewSource, ReviewStatus
from banks.factories import BankFactory
from banks.models import ReviewQueue
from credit_cards.admin import CreditCardAdmin
from credit_cards.constants import VerificationStatus
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard, CreditCardFieldHistory

LIST_URL = "/api/v1/credit-cards/"
SEARCH_URL = "/api/v1/credit-cards/advanced-search/"
TYPEAHEAD_URL = "/api/v1/credit-cards/typeahead/"


def _non_public_cards(bank):
    return {
        "draft": CreditCardFactory(
            bank=bank, name="Hidden Draft", verification_status="draft"
        ),
        "needs_review": CreditCardFactory(
            bank=bank, name="Hidden Review", verification_status="needs_review"
        ),
        "inactive": CreditCardFactory(bank=bank, name="Hidden Inactive", is_active=False),
    }


@pytest.mark.django_db()
class TestPublicVisibility:
    """Only active + verified cards appear on public endpoints."""

    def test_list_and_detail_hide_non_public_cards(self, api_client):
        bank = BankFactory()
        visible = CreditCardFactory(bank=bank, name="Shown Card")
        hidden = _non_public_cards(bank)

        response = api_client.get(LIST_URL)
        assert [c["name"] for c in response.data["results"]] == ["Shown Card"]
        assert api_client.get(f"{LIST_URL}{visible.pk}/").status_code == 200
        for card in hidden.values():
            assert api_client.get(f"{LIST_URL}{card.pk}/").status_code == 404

    def test_search_and_typeahead_hide_non_public_cards(self, api_client):
        bank = BankFactory(name="Gate Bank")
        CreditCardFactory(bank=bank, name="Hidden Shown", annual_fee=0)
        _non_public_cards(bank)

        search = api_client.get(SEARCH_URL, {"search": "Hidden"})
        assert [c["name"] for c in search.data["results"]] == ["Hidden Shown"]

        typeahead = api_client.get(TYPEAHEAD_URL, {"q": "Hidden"})
        assert typeahead.data["matches"]["card"] == ["Hidden Shown"]
        assert typeahead.data["facets"]["no_fee"]["count"] == 1

    def test_bank_card_counts_ignore_non_public_cards(self, api_client):
        bank = BankFactory(name="Counted Bank")
        CreditCardFactory(bank=bank, name="Counted")
        _non_public_cards(bank)

        assert bank.credit_card_count == 1
        response = api_client.get(TYPEAHEAD_URL, {"q": "Counted Bank"})
        bank_suggestion = [s for s in response.data["suggestions"] if s["type"] == "bank"]
        assert bank_suggestion[0]["detail"] == "1 cards"

    def test_new_fields_are_serialized_on_list_and_detail(self, api_client):
        card = CreditCardFactory(
            source_url="https://bank.test/card",
            apply_url="https://bank.test/apply",
            card_network="visa",
            is_islamic=True,
            is_dual_currency=False,
            min_monthly_income=50000,
            supplementary_card_fee="Free",
            foreign_transaction_fee="3%",
        )
        for payload in (
            api_client.get(LIST_URL).data["results"][0],
            api_client.get(f"{LIST_URL}{card.pk}/").data,
        ):
            assert payload["source_url"] == "https://bank.test/card"
            assert payload["apply_url"] == "https://bank.test/apply"
            assert payload["verification_status"] == "verified"
            assert payload["card_network"] == "visa"
            assert payload["is_islamic"] is True
            assert payload["is_dual_currency"] is False
            assert payload["min_monthly_income"] == "50000.00"
            assert payload["supplementary_card_fee"] == "Free"
            assert payload["foreign_transaction_fee"] == "3%"

    def test_new_cards_default_to_draft_with_unknown_values(self):
        card = CreditCard.objects.create(bank=BankFactory(), name="Plain")
        assert card.verification_status == VerificationStatus.DRAFT
        assert card.is_dual_currency is None
        assert card.is_islamic is False
        assert not card.is_public

    def test_new_field_changes_are_recorded_in_history(self):
        card = CreditCardFactory(card_network="")
        card.card_network = "visa"
        card.verification_status = "needs_review"
        card.save()
        recorded = {
            h.field_name: (h.old_value, h.new_value)
            for h in CreditCardFieldHistory.objects.filter(card=card)
        }
        assert recorded["card_network"] == ("", "visa")
        assert recorded["verification_status"] == ("verified", "needs_review")


@pytest.mark.django_db()
class TestReportIssue:
    """POST /credit-cards/{id}/report-issue/."""

    def url(self, card):
        return f"{LIST_URL}{card.pk}/report-issue/"

    def test_anonymous_report_creates_review_item(self, api_client):
        card = CreditCardFactory()
        response = api_client.post(
            self.url(card),
            {
                "field": "annual_fee",
                "message": "The fee is wrong",
                "suggested_value": "1500",
                "contact_email": "me@example.com",
            },
            format="json",
        )
        assert response.status_code == 201
        item = ReviewQueue.objects.get(pk=response.data["id"])
        assert item.source == ReviewSource.USER_REPORT
        assert item.status == ReviewStatus.PENDING
        assert (item.credit_card, item.bank) == (card, card.bank)
        assert item.field_name == "annual_fee"
        assert item.proposed_value == "1500"
        assert item.message == "The fee is wrong"
        assert item.contact_email == "me@example.com"
        assert item.crawled_content is None

    def test_field_and_suggestion_are_optional(self, api_client):
        card = CreditCardFactory()
        response = api_client.post(
            self.url(card), {"message": "Looks off"}, format="json"
        )
        assert response.status_code == 201
        item = ReviewQueue.objects.get()
        assert item.field_name == ""
        assert item.proposed_value is None

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"message": ""},
            {"message": "x" * 1001},
            {"message": "ok", "field": "not_a_field"},
            {"message": "ok", "field": "verification_status"},
            {"message": "ok", "contact_email": "not-an-email"},
            {"message": "ok", "suggested_value": "x" * 1001},
        ],
    )
    def test_invalid_reports_are_rejected(self, api_client, payload):
        card = CreditCardFactory()
        response = api_client.post(self.url(card), payload, format="json")
        assert response.status_code == 400
        assert not ReviewQueue.objects.exists()

    def test_cannot_report_a_non_public_card(self, api_client):
        card = CreditCardFactory(verification_status="draft")
        response = api_client.post(self.url(card), {"message": "hi"}, format="json")
        assert response.status_code == 404

    def test_report_is_throttled_per_ip(self, api_client):
        card = CreditCardFactory()
        statuses = [
            api_client.post(
                self.url(card), {"message": f"r{i}"}, format="json"
            ).status_code
            for i in range(6)
        ]
        assert statuses == [201] * 5 + [429]

    def test_endpoint_is_documented_in_openapi(self, api_client, settings):
        settings.SECURE_SSL_REDIRECT = False
        schema = api_client.get("/api/v1/schema/", {"format": "json"}).data
        operation = schema["paths"]["/api/v1/credit-cards/{id}/report-issue/"]["post"]
        assert "201" in operation["responses"]
        assert "ReportIssueRequest" in schema["components"]["schemas"]


@pytest.mark.django_db()
class TestAdminActions:
    """Mark verified / needs review admin actions."""

    def _run(self, action, queryset):
        from django.contrib import admin
        from django.test import RequestFactory

        request = RequestFactory().post("/")
        request.user = User.objects.create_superuser("staff", "s@example.com", "pw")
        request._messages = type("M", (), {"add": lambda *a, **k: None})()
        model_admin = CreditCardAdmin(CreditCard, admin.site)
        getattr(model_admin, action)(request, queryset)
        return request.user

    def test_mark_verified_records_who_and_when(self):
        card = CreditCardFactory(verification_status="draft")
        user = self._run("mark_verified", CreditCard.objects.filter(pk=card.pk))
        card.refresh_from_db()
        assert card.verification_status == VerificationStatus.VERIFIED
        assert card.verified_by == user
        assert card.verified_at is not None
        assert card.is_public

    def test_mark_needs_review_unpublishes(self):
        card = CreditCardFactory()
        self._run("mark_needs_review", CreditCard.objects.filter(pk=card.pk))
        card.refresh_from_db()
        assert card.verification_status == VerificationStatus.NEEDS_REVIEW
        assert not card.is_public


@pytest.mark.django_db()
class TestExportImportCommands:
    """export_verified_cards / import_cards round trip."""

    def test_export_only_verified_and_import_upserts(self, tmp_path):
        bank = BankFactory(name="Round Trip Bank")
        CreditCardFactory(
            bank=bank,
            name="Exported",
            annual_fee=1200,
            card_network="visa",
            source_url="https://bank.test/x",
        )
        CreditCardFactory(bank=bank, name="Draft Only", verification_status="draft")
        path = tmp_path / "cards.json"

        call_command("export_verified_cards", str(path))
        rows = json.loads(path.read_text())
        assert [(r["bank"], r["name"]) for r in rows] == [("Round Trip Bank", "Exported")]
        assert rows[0]["annual_fee"] == "1200.00"

        CreditCard.objects.all().delete()
        call_command("import_cards", str(path))
        card = CreditCard.objects.get(bank__name="Round Trip Bank", name="Exported")
        assert card.annual_fee == 1200
        assert card.card_network == "visa"
        assert card.verification_status == VerificationStatus.VERIFIED
        assert card.is_public

        rows[0]["annual_fee"] = "999"
        rows[0]["verification_status"] = "draft"
        path.write_text(json.dumps(rows))
        call_command("import_cards", str(path))
        card.refresh_from_db()
        assert CreditCard.objects.count() == 1
        assert card.annual_fee == 999
        assert card.verification_status == VerificationStatus.DRAFT

    def test_import_rejects_unknown_fields(self, tmp_path):
        from django.core.management.base import CommandError

        path = tmp_path / "bad.json"
        path.write_text(json.dumps([{"bank": "B", "name": "N", "bogus": 1}]))
        with pytest.raises(CommandError):
            call_command("import_cards", str(path))
        assert not CreditCard.objects.exists()
