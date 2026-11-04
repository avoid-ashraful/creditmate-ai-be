"""Parser fixtures for the BB lending chart.

The fixture mirrors the real chart's structure (verified live, October
2026 edition): data rows have 14 cells; SC.2 rows have a blank bank-code
cell and belong to the bank above; the housing column is index 9 and the
consumer-credit column is index 10.
"""

from decimal import Decimal

from django.test import TestCase

from banks.models import Bank
from loans.constants import ChartCategory
from loans.ingestion.bb_lending_chart import ingest_lending_chart, parse_lending_chart
from loans.models import LendingChartSnapshot, LoanChartBand

HEADER = (
    "<tr><th>Bank</th><th>Sub</th><th>Agri</th><th>Term L</th><th>Term S</th>"
    "<th>WC L</th><th>WC S</th><th>Export</th><th>Trade</th>"
    "<th>Housing loan</th><th>Consumer credit</th><th>Card</th>"
    "<th>NBFI</th><th>Other</th></tr>"
)


def _row(code, sub, housing, consumer):
    cells = [
        code,
        sub,
        "1-2",
        "1-2",
        "1-2",
        "1-2",
        "1-2",
        "1-2",
        "1-2",
        housing,
        consumer,
        "25",
        "1-2",
        "1-2",
    ]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


FIXTURE_HTML = f"""
<html><body><p>Interest Rate of Advance ... October, 2026</p>
<table>{HEADER}
{_row("BRAC", "SC.1", "9.22-11.22", "9.72-11.72")}
{_row("", "SC.2", "10.00-12.00", "")}
{_row("EBL", "SC.1", "9.50-9.99", "9.25-13.25")}
{_row("Padma", "SC.1", "", "12.00-14.00")}
</table></body></html>
"""


class ParseTests(TestCase):
    def test_parse_merges_subcategories(self):
        edition, month, banks, _anomalies = parse_lending_chart(FIXTURE_HTML)
        self.assertEqual(edition, "October, 2026")
        self.assertEqual(month.isoformat(), "2026-10-01")
        by_code = {b["code"]: b for b in banks}
        self.assertEqual(set(by_code), {"BRAC", "EBL", "Padma"})
        # SC.1 housing 9.22-11.22 merged with SC.2 10.00-12.00 -> 9.22-12.00
        self.assertEqual(
            by_code["BRAC"]["categories"][ChartCategory.HOUSING],
            (Decimal("9.22"), Decimal("12.00")),
        )
        self.assertEqual(
            by_code["BRAC"]["categories"][ChartCategory.CONSUMER_CREDIT],
            (Decimal("9.72"), Decimal("11.72")),
        )
        self.assertNotIn(ChartCategory.HOUSING, by_code["Padma"]["categories"])

    def test_ingest_creates_bands_and_is_idempotent(self):
        Bank.objects.create(name="BRAC Bank PLC")
        stats = ingest_lending_chart(FIXTURE_HTML)
        self.assertEqual(stats["banks_seen"], 3)
        self.assertTrue(stats["snapshot_created"])
        # BRAC housing + consumer, EBL housing + consumer, PADMA consumer = 5
        self.assertEqual(LoanChartBand.objects.count(), 5)
        brac = LoanChartBand.objects.get(
            bank__name="BRAC Bank PLC", category=ChartCategory.HOUSING
        )
        self.assertEqual(brac.rate_min, Decimal("9.22"))
        self.assertEqual(brac.rate_max, Decimal("12.00"))
        # Padma has no catalogue bank -> institution fallback row
        padma = LoanChartBand.objects.get(
            bank__isnull=True,
            institution_name="Padma Bank",
            category=ChartCategory.CONSUMER_CREDIT,
        )
        self.assertEqual(padma.rate_min, Decimal("12.00"))
        # Second run of the same edition writes nothing.
        stats2 = ingest_lending_chart(FIXTURE_HTML)
        self.assertFalse(stats2["snapshot_created"])
        self.assertEqual(stats2["bands_written"], 0)
        self.assertEqual(LendingChartSnapshot.objects.count(), 1)
        self.assertEqual(LoanChartBand.objects.count(), 5)
