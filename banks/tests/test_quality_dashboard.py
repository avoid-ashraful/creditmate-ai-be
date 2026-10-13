"""Tests for the data-quality dashboard service and admin view.

Covers the metric helpers in ``banks.services.quality_dashboard`` (per-bank
success rates, missing annual-fee/APR counts, 7/30-day confidence windows,
OCR-vs-text comparison, alert thresholds, and the no-denominator/no-score
safety) plus the login + is_staff protection of the ``/admin/data-quality/``
view.
"""

from datetime import timedelta

import pytest

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from banks.enums import ProcessingStatus
from banks.factories import BankDataSourceFactory, BankFactory, CrawledContentFactory
from banks.models import CrawledContent
from banks.services import quality_dashboard
from credit_cards.factories import CreditCardFactory

CONFIDENCE_ALERT_THRESHOLD = quality_dashboard.CONFIDENCE_ALERT_THRESHOLD
SUCCESS_RATE_ALERT_THRESHOLD = quality_dashboard.SUCCESS_RATE_ALERT_THRESHOLD


def make_content(
    bank,
    status=ProcessingStatus.COMPLETED,
    method="pdf_text",
    confidence=None,
    missing=None,
    days_ago=None,
):
    """Create a CrawledContent for a bank with configurable quality fields.

    Parameters
    ----------
    bank : Bank
        The bank the content's data source belongs to.
    status : str, optional
        Processing status for the created row.
    method : str, optional
        Extraction method (``pdf_text``, ``ocr``, ``image_ocr``, ...).
    confidence : float or None, optional
        Extraction confidence to store on the row.
    missing : list of str, optional
        Critical fields reported as missing on the row.
    days_ago : int or None, optional
        When given, backdate ``crawled_at`` by this many days.

    Returns
    -------
    CrawledContent
        The created row.
    """
    data_source = BankDataSourceFactory(bank=bank)
    content = CrawledContentFactory(
        data_source=data_source,
        processing_status=status,
        extraction_method=method,
        extraction_confidence=confidence,
        missing_critical_fields=missing or [],
    )
    if days_ago is not None:
        CrawledContent.objects.filter(pk=content.pk).update(
            crawled_at=timezone.now() - timedelta(days=days_ago)
        )
        content.refresh_from_db()
    return content


def alert_kinds(alerts, scope=None, bank_id=None):
    """Return the alert kinds matching scope/bank filters."""
    return [
        alert["kind"]
        for alert in alerts
        if (scope is None or alert["scope"] == scope)
        and (bank_id is None or alert["bank_id"] == bank_id)
    ]


@pytest.mark.django_db
class TestSuccessRate:
    """The success rate is completed / (completed + failed), None-safe."""

    def test_success_rate_ratio(self):
        assert quality_dashboard.success_rate(3, 1) == 0.75
        assert quality_dashboard.success_rate(2, 0) == 1.0
        assert quality_dashboard.success_rate(0, 2) == 0.0

    def test_success_rate_no_denominator_returns_none(self):
        assert quality_dashboard.success_rate(0, 0) is None

    def test_bank_success_rate_ignores_open_states(self):
        bank = BankFactory()
        make_content(bank, status=ProcessingStatus.COMPLETED)
        make_content(bank, status=ProcessingStatus.COMPLETED)
        make_content(bank, status=ProcessingStatus.COMPLETED)
        make_content(bank, status=ProcessingStatus.FAILED)
        make_content(bank, status=ProcessingStatus.PENDING)
        make_content(bank, status=ProcessingStatus.PROCESSING)

        summary = quality_dashboard.bank_summary(bank)
        assert summary["total_contents"] == 6
        assert summary["completed"] == 3
        assert summary["failed"] == 1
        assert summary["pending"] == 1
        assert summary["processing"] == 1
        assert summary["success_rate"] == 0.75

    def test_bank_without_terminal_states_has_none_rate(self):
        bank = BankFactory()
        make_content(bank, status=ProcessingStatus.PENDING)
        assert quality_dashboard.bank_summary(bank)["success_rate"] is None

    def test_bank_without_content_has_none_rate(self):
        bank = BankFactory()
        summary = quality_dashboard.bank_summary(bank)
        assert summary["success_rate"] is None
        assert summary["total_contents"] == 0


@pytest.mark.django_db
class TestMissingFieldCounts:
    """Missing annual-fee/APR counts cover content and joined cards."""

    def test_content_missing_counts(self):
        bank = BankFactory()
        make_content(bank, missing=["annual_fee"])
        make_content(bank, missing=["interest_rate_apr"])
        make_content(bank, missing=["annual_fee", "interest_rate_apr"])

        summary = quality_dashboard.bank_summary(bank)
        assert summary["content_missing_annual_fee"] == 2
        assert summary["content_missing_apr"] == 2

    def test_failed_rows_do_not_count_as_missing_content(self):
        bank = BankFactory()
        make_content(
            bank,
            status=ProcessingStatus.FAILED,
            missing=["annual_fee", "interest_rate_apr"],
        )
        summary = quality_dashboard.bank_summary(bank)
        assert summary["content_missing_annual_fee"] == 0
        assert summary["content_missing_apr"] == 0

    def test_null_numeric_card_values_counted_via_join(self):
        bank = BankFactory()
        CreditCardFactory(bank=bank, annual_fee=None, interest_rate_apr=None)
        CreditCardFactory(bank=bank, annual_fee=50, interest_rate_apr=None)
        CreditCardFactory(bank=bank, annual_fee=None, interest_rate_apr=18.5)

        summary = quality_dashboard.bank_summary(bank)
        assert summary["cards_null_annual_fee"] == 2
        assert summary["cards_null_apr"] == 2

    def test_counts_are_bank_scoped(self):
        bank_a = BankFactory()
        bank_b = BankFactory()
        make_content(bank_a, missing=["annual_fee"])
        make_content(bank_b, missing=["annual_fee"])
        CreditCardFactory(bank=bank_a, annual_fee=None, interest_rate_apr=None)

        summary_a = quality_dashboard.bank_summary(bank_a)
        summary_b = quality_dashboard.bank_summary(bank_b)
        assert summary_a["content_missing_annual_fee"] == 1
        assert summary_b["content_missing_annual_fee"] == 1
        assert summary_a["cards_null_annual_fee"] == 1
        assert summary_b["cards_null_annual_fee"] == 0


@pytest.mark.django_db
class TestConfidenceWindows:
    """7-day and 30-day averages only use scored content in the window."""

    def test_averages_respect_windows(self):
        bank = BankFactory()
        make_content(bank, confidence=0.9, days_ago=2)
        make_content(bank, confidence=0.5, days_ago=10)
        make_content(bank, confidence=0.7, days_ago=40)
        make_content(bank, confidence=None, days_ago=1)

        summary = quality_dashboard.bank_summary(bank)
        assert summary["average_confidence_7d"] == 0.9
        assert summary["average_confidence_30d"] == 0.7
        assert summary["scored_7d"] == 1
        assert summary["scored_30d"] == 2

    def test_no_scored_content_returns_none(self):
        bank = BankFactory()
        make_content(bank, confidence=None, days_ago=1)
        summary = quality_dashboard.bank_summary(bank)
        assert summary["average_confidence_7d"] is None
        assert summary["average_confidence_30d"] is None
        assert summary["scored_7d"] == 0
        assert summary["scored_30d"] == 0


@pytest.mark.django_db
class TestMethodComparison:
    """OCR content is separated from text-based content in the comparison."""

    def test_ocr_vs_text_completion_and_success(self):
        bank = BankFactory()
        make_content(bank, method="ocr", status=ProcessingStatus.COMPLETED)
        make_content(bank, method="ocr", status=ProcessingStatus.COMPLETED)
        make_content(bank, method="ocr", status=ProcessingStatus.FAILED)
        make_content(bank, method="image_ocr", status=ProcessingStatus.COMPLETED)
        make_content(bank, method="pdf_text", status=ProcessingStatus.COMPLETED)
        make_content(bank, method="pdf_text", status=ProcessingStatus.COMPLETED)
        make_content(bank, method="webpage", status=ProcessingStatus.PENDING)
        make_content(bank, method="csv", status=ProcessingStatus.FAILED)

        comparison = quality_dashboard.method_comparison()

        ocr = comparison["ocr"]
        assert ocr["total_contents"] == 4
        assert ocr["completed"] == 3
        assert ocr["failed"] == 1
        assert ocr["completion_rate"] == 0.75
        assert ocr["success_rate"] == 0.75

        text = comparison["text"]
        assert text["total_contents"] == 4
        assert text["completed"] == 2
        assert text["failed"] == 1
        assert text["completion_rate"] == 0.5
        assert text["success_rate"] == round(2 / 3, 4)

    def test_unscoped_methods_fall_into_unknown(self):
        BankFactory()
        make_content(BankFactory(), method="")
        make_content(BankFactory(), method="mystery_method")

        unknown = quality_dashboard.method_comparison()["unknown"]
        assert unknown["total_contents"] == 2

    def test_empty_database_rates_are_none(self):
        comparison = quality_dashboard.method_comparison()
        for bucket in comparison.values():
            assert bucket["total_contents"] == 0
            assert bucket["completion_rate"] is None
            assert bucket["success_rate"] is None


@pytest.mark.django_db
class TestAlerts:
    """Alerts fire on low confidence/success and never on missing data."""

    def test_low_confidence_alert(self):
        bank = BankFactory()
        make_content(bank, confidence=0.4, days_ago=2)

        totals = quality_dashboard.totals_summary()
        banks = [quality_dashboard.bank_summary(bank)]
        alerts = quality_dashboard.build_alerts(totals, banks)

        assert "low_confidence" in alert_kinds(alerts, scope="overall")
        assert "low_confidence" in alert_kinds(alerts, scope="bank", bank_id=bank.pk)

    def test_confidence_at_threshold_is_not_flagged(self):
        bank = BankFactory()
        make_content(bank, confidence=CONFIDENCE_ALERT_THRESHOLD, days_ago=1)

        totals = quality_dashboard.totals_summary()
        alerts = quality_dashboard.build_alerts(
            totals, [quality_dashboard.bank_summary(bank)]
        )

        assert "low_confidence" not in alert_kinds(alerts)

    def test_low_success_rate_alert(self):
        bank = BankFactory()
        make_content(bank, status=ProcessingStatus.COMPLETED, confidence=0.9)
        make_content(bank, status=ProcessingStatus.COMPLETED, confidence=0.9)
        make_content(bank, status=ProcessingStatus.FAILED)
        make_content(bank, status=ProcessingStatus.FAILED)
        make_content(bank, status=ProcessingStatus.FAILED)

        totals = quality_dashboard.totals_summary()
        banks = [quality_dashboard.bank_summary(bank)]
        alerts = quality_dashboard.build_alerts(totals, banks)

        assert "low_success_rate" in alert_kinds(alerts, scope="overall")
        assert "low_success_rate" in alert_kinds(alerts, scope="bank", bank_id=bank.pk)
        # Confidence is fine here; only the success alert should exist.
        assert "low_confidence" not in alert_kinds(alerts, scope="bank", bank_id=bank.pk)

    def test_success_at_threshold_is_not_flagged(self):
        bank = BankFactory()
        for _ in range(7):
            make_content(bank)
        for _ in range(3):
            make_content(bank, status=ProcessingStatus.FAILED)

        summary = quality_dashboard.bank_summary(bank)
        assert summary["success_rate"] == SUCCESS_RATE_ALERT_THRESHOLD
        alerts = quality_dashboard.build_alerts(
            quality_dashboard.totals_summary(), [summary]
        )
        assert "low_success_rate" not in alert_kinds(alerts)

    def test_no_data_produces_no_alerts(self):
        totals = quality_dashboard.totals_summary()
        alerts = quality_dashboard.build_alerts(totals, [])
        assert alerts == []
        assert totals["success_rate"] is None
        assert totals["average_confidence_7d"] is None
        assert totals["average_confidence_30d"] is None


@pytest.mark.django_db
class TestDashboardSnapshot:
    """The assembled snapshot is consistent and safe on empty data."""

    def test_snapshot_includes_all_sections(self):
        bank = BankFactory()
        make_content(bank, confidence=0.8)

        snapshot = quality_dashboard.build_dashboard()
        assert "generated_at" in snapshot
        assert snapshot["totals"]["banks"] == 1
        assert snapshot["totals"]["success_rate"] == 1.0
        assert snapshot["banks"][0]["bank_name"] == bank.name
        assert set(snapshot["methods"]) == {"ocr", "text", "unknown"}
        assert isinstance(snapshot["alerts"], list)

    def test_empty_database_snapshot_is_safe(self):
        snapshot = quality_dashboard.build_dashboard()
        assert snapshot["banks"] == []
        assert snapshot["totals"]["total_contents"] == 0
        assert snapshot["totals"]["success_rate"] is None
        assert snapshot["alerts"] == []


@pytest.mark.django_db
class TestDataQualityViewAccessControl:
    """The view requires login and is_staff, like the Django admin."""

    @pytest.fixture(autouse=True)
    def no_ssl_redirect(self, settings):
        """Keep test enforces focus on the auth gate, not https redirects."""
        settings.SECURE_SSL_REDIRECT = False

    def setup_method(self):
        self.client = Client()
        self.url = reverse("data-quality-dashboard")

    def test_anonymous_redirected_to_admin_login(self):
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert "/admin/login/" in response["Location"]

    def test_authenticated_non_staff_is_redirected_to_admin_login(self):
        get_user_model().objects.create_user(username="operator", password="password123")
        assert self.client.login(username="operator", password="password123")
        response = self.client.get(self.url)
        # staff_member_required, like the admin itself, bounces non-staff
        # users to the admin login page rather than serving the snapshot.
        assert response.status_code == 302
        assert "/admin/login/" in response["Location"]
        assert response["Location"] != reverse("admin:logout")

    def test_staff_receives_json_snapshot(self):
        get_user_model().objects.create_user(
            username="admin", password="password123", is_staff=True
        )
        assert self.client.login(username="admin", password="password123")
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")

        payload = response.json()
        for key in ("generated_at", "totals", "banks", "methods", "alerts"):
            assert key in payload

    def test_staff_receives_real_metrics(self):
        bank = BankFactory()
        make_content(bank, status=ProcessingStatus.COMPLETED, confidence=0.9)
        make_content(bank, status=ProcessingStatus.FAILED)

        get_user_model().objects.create_user(
            username="admin", password="password123", is_staff=True
        )
        assert self.client.login(username="admin", password="password123")
        payload = self.client.get(self.url).json()
        assert payload["totals"]["total_contents"] == 2
        assert payload["totals"]["success_rate"] == 0.5
        assert payload["banks"][0]["bank_name"] == bank.name

    def test_staff_post_is_method_not_allowed(self):
        get_user_model().objects.create_user(
            username="admin", password="password123", is_staff=True
        )
        assert self.client.login(username="admin", password="password123")
        response = self.client.post(self.url)
        assert response.status_code == 405
