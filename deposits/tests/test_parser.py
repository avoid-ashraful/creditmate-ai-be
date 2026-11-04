"""Tests for the BB deposit-chart parser and ingestion (fixture-driven)."""

from decimal import Decimal
from pathlib import Path

import pytest

from deposits.ingestion.bb_chart import (
    detect_anomalies,
    ingest_chart,
    parse_chart,
    parse_rate_cell,
)
from deposits.models import (
    DepositChartSnapshot,
    DepositFieldHistory,
    DepositProduct,
    DepositRate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseRateCell:
    def test_single(self):
        assert parse_rate_cell("8.25") == (Decimal("8.25"), Decimal("8.25"))

    def test_range(self):
        assert parse_rate_cell("7.25-8.00") == (Decimal("7.25"), Decimal("8.00"))

    def test_blank(self):
        assert parse_rate_cell("") is None
        assert parse_rate_cell("   ") is None

    def test_range_with_spaces(self):
        assert parse_rate_cell("9.06 - 11.39") == (
            Decimal("9.06"),
            Decimal("11.39"),
        )


class TestParseChart:
    def test_conventional_edition_and_rows(self):
        chart = parse_chart(load("bb_chart_conventional_oct2026.html"))
        assert chart.edition_label == "October, 2026"
        assert chart.edition_month.isoformat() == "2026-10-01"
        assert len(chart.rows) == 61

    def test_islamic_window_rows(self):
        chart = parse_chart(load("bb_chart_islamic_oct2026.html"))
        assert len(chart.rows) == 19
        codes = {r["code"] for r in chart.rows}
        assert "THE CITY" in codes and "PUBALI" in codes

    def test_singles_ranges_blanks(self):
        chart = parse_chart(load("bb_chart_conventional_oct2026.html"))
        by_code = {r["code"]: r for r in chart.rows}
        # AGRANI 1-<2y FD is a point rate.
        assert by_code["AGRANI"]["fd"][2] == (Decimal("8.25"), Decimal("8.25"))
        # BASIC 1-<2y FD is a range.
        assert by_code["BASIC"]["fd"][2] == (Decimal("7.50"), Decimal("9.75"))
        # BDBL publishes nothing for the last two FD bands.
        assert by_code["BDBL"]["fd"][3] is None
        assert by_code["BDBL"]["fd"][4] is None

    def test_anomaly_detection(self):
        chart = parse_chart(load("bb_chart_conventional_oct2026.html"))
        anomalies = detect_anomalies(chart.rows)
        types = {a["type"] for a in anomalies}
        assert "identical_fd_ladder" in types
        ladder = next(a for a in anomalies if a["type"] == "identical_fd_ladder")
        assert {"EXIM", "FIRST SECU", "GIBL"} <= set(ladder["banks"])
        high = next(a for a in anomalies if a["type"] == "suspiciously_high_flat_rates")
        assert high["banks"] == ["AB-BANK"]


@pytest.mark.django_db
class TestIngestChart:
    URL = "https://www.bb.org.bd/en/index.php/financialactivity/interestdeposit"

    def test_ingest_creates_products_and_rates(self):
        from banks.models import Bank

        Bank.objects.create(name="BRAC Bank PLC")
        Bank.objects.create(name="Islami Bank Bangladesh Limited")
        report = ingest_chart(
            load("bb_chart_conventional_oct2026.html"), "conventional", self.URL
        )
        assert report["banks_seen"] == 61
        assert report["products_created"] == 61
        assert report["rates_created"] == DepositRate.objects.count() > 200

        brac = DepositProduct.objects.get(slug__contains="brac-bank-plc")
        assert brac.bank.name == "BRAC Bank PLC"
        assert brac.is_generic is True
        assert brac.verification_status == "verified"
        band = brac.rates.get(tenure_months_min=12, tenure_months_max=24)
        assert band.rate_min == Decimal("7.25")
        assert band.rate_max == Decimal("8.00")

        islami = DepositProduct.objects.get(slug__contains="islami-bank-bangladesh")
        assert islami.is_islamic is True
        assert islami.rate_type == "expected_profit"

        # PKB is not in the card catalogue -> institution_name fallback.
        pkb = DepositProduct.objects.get(institution_name="Probashi Kallyan Bank")
        assert pkb.bank is None

    def test_islamic_window_chart_creates_separate_family(self):
        from banks.models import Bank

        Bank.objects.create(name="City Bank PLC")
        report = ingest_chart(
            load("bb_chart_islamic_oct2026.html"), "islamic_window", self.URL
        )
        assert report["products_created"] == 19
        city = DepositProduct.objects.get(
            slug__contains="city-bank-plc", institution_type="islamic_window"
        )
        assert city.rate_type == "expected_profit"
        band = city.rates.get(tenure_months_min=3, tenure_months_max=6)
        assert band.rate_min == Decimal("2.59")

    def test_idempotent_rerun(self):
        html = load("bb_chart_conventional_oct2026.html")
        ingest_chart(html, "conventional", self.URL)
        counts = (
            DepositProduct.objects.count(),
            DepositRate.objects.count(),
            DepositFieldHistory.objects.count(),
        )
        report = ingest_chart(html, "conventional", self.URL)
        assert report["products_created"] == 0
        assert report["rates_created"] == 0
        assert report["rates_updated"] == 0
        assert report["history_rows"] == 0
        assert counts == (
            DepositProduct.objects.count(),
            DepositRate.objects.count(),
            DepositFieldHistory.objects.count(),
        )

    def test_rate_change_writes_history(self):
        html = load("bb_chart_conventional_oct2026.html")
        ingest_chart(html, "conventional", self.URL)
        # AGRANI's 6m-1y FD band (8.38) appears exactly once in the chart.
        changed = html.replace(">8.38<", ">8.60<", 1)
        assert changed != html
        report = ingest_chart(changed, "conventional", self.URL)
        assert report["rates_updated"] == 1
        assert report["history_rows"] == 1
        history = DepositFieldHistory.objects.get(field_name="rate_6_12")
        assert Decimal(history.old_value["rate_min"]) == Decimal("8.38")
        assert Decimal(history.new_value["rate_min"]) == Decimal("8.60")

    def test_rate_appearance_writes_history(self):
        html = load("bb_chart_conventional_oct2026.html")
        ingest_chart(html, "conventional", self.URL)
        product = DepositProduct.objects.get(
            institution_name="Bangladesh Development Bank"
        )
        # BDBL publishes nothing for the 2-<3y FD band in this edition.
        assert not product.rates.filter(
            tenure_months_min=24, tenure_months_max=36
        ).exists()
        # Fill the first blank FD cell of BDBL's row (the 2-<3y band).
        marker = '<td class="text-left">BDBL</td>'
        head, _, tail = html.partition(marker)
        row_end = tail.index("</tr>")
        row = tail[:row_end].replace(
            '<td class="text-left"></td>', '<td class="text-left">9.25</td>', 1
        )
        changed = head + marker + row + tail[row_end:]
        assert changed != html
        report = ingest_chart(changed, "conventional", self.URL)
        assert report["rates_created"] == 1
        assert report["history_rows"] == 1
        rate = product.rates.get(tenure_months_min=24, tenure_months_max=36)
        assert rate.rate_min == Decimal("9.25")
        history = DepositFieldHistory.objects.get(
            product=product, field_name="rate_24_36"
        )
        assert history.old_value is None
        assert Decimal(history.new_value["rate_min"]) == Decimal("9.25")

    def test_unparseable_cell_keeps_existing_rate(self):
        html = load("bb_chart_conventional_oct2026.html")
        ingest_chart(html, "conventional", self.URL)
        # AGRANI's 6m-1y FD band (8.38) becomes unreadable in the next
        # fetch: that must NOT be read as the rate disappearing.
        changed = html.replace(">8.38<", ">TBD<", 1)
        assert changed != html
        report = ingest_chart(changed, "conventional", self.URL)
        assert report["rates_deleted"] == 0
        product = DepositProduct.objects.get(
            institution_name="Agrani Bank", slug__contains="agrani"
        )
        band = product.rates.get(tenure_months_min=6, tenure_months_max=12)
        assert band.rate_min == Decimal("8.38")
        # …and the cell is flagged on the snapshot for human review.
        snapshot = DepositChartSnapshot.objects.get(
            source="conventional", edition_label="October, 2026"
        )
        anomaly_types = {a["type"] for a in snapshot.anomalies}
        assert "unparseable_rate_cell" in anomaly_types
        assert "unparseable_rate_cell" in {a["type"] for a in report["anomalies"]}
