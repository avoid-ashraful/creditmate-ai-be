"""Maturity + tax math tests with hand-computed expectations."""

from datetime import date
from decimal import Decimal

import pytest

from deposits import maturity
from deposits.constants import Compounding
from deposits.models import DepositProduct, DepositRate, DepositTaxRule


class TestFdrMaturity:
    def test_annual_compounding(self):
        # 500,000 at 8.25% for 12 months = 500,000 * 1.0825
        assert maturity.fdr_maturity(
            Decimal("500000"), Decimal("8.25"), 12, Compounding.ANNUAL
        ) == Decimal("541250.00")

    def test_quarterly_compounding(self):
        # 100,000 at 8% for 12 months, quarterly: (1.02)^4 = 1.08243216
        assert maturity.fdr_maturity(
            Decimal("100000"), Decimal("8"), 12, Compounding.QUARTERLY
        ) == Decimal("108243.22")

    def test_simple_at_maturity(self):
        # 200,000 at 10% for 6 months, simple: +10,000
        assert maturity.fdr_maturity(
            Decimal("200000"), Decimal("10"), 6, Compounding.AT_MATURITY
        ) == Decimal("210000.00")

    def test_monthly_compounding(self):
        # 100,000 at 12% for 12 months monthly: (1.01)^12 = 1.1268250301...
        assert maturity.fdr_maturity(
            Decimal("100000"), Decimal("12"), 12, Compounding.MONTHLY
        ) == Decimal("112682.50")


class TestDpsMaturity:
    def test_matches_dbbl_published_table(self):
        # DBBL Deposit Plus published maturity values at 9.50%
        # (BDT 500/month) — the engine must reproduce them to the taka.
        for months, expected in [(36, 20897), (60, 38514), (96, 72054), (120, 100328)]:
            value = maturity.dps_maturity(Decimal("500"), Decimal("9.50"), months)
            assert abs(value - Decimal(expected)) < Decimal("1"), (months, value)

    def test_zero_rate(self):
        assert maturity.dps_maturity(Decimal("1000"), Decimal("0"), 12) == Decimal(
            "12000.00"
        )

    def test_goal_seek_round_trip(self):
        instalment = maturity.dps_instalment_for_target(
            Decimal("100328"), Decimal("9.50"), 120
        )
        assert abs(instalment - Decimal("500")) < Decimal("1")


@pytest.fixture
def tax_rules(db):
    DepositTaxRule.objects.create(
        key="bank_interest_source_tax",
        effective_from=date(2024, 7, 1),
        params={"with_tin": "10", "without_tin": "15"},
    )
    DepositTaxRule.objects.create(
        key="sanchayapatra_source_tax",
        effective_from=date(2026, 2, 1),
        params={
            "threshold": "500000",
            "at_or_below_threshold": "5",
            "above_threshold": "10",
            "pensioner_exempt_up_to": "500000",
        },
    )


def make_product(**kwargs):
    defaults = {
        "institution_name": "Test Bank",
        "kind": "fdr",
        "name": "Test FDR",
        "compounding": Compounding.ANNUAL,
    }
    defaults.update(kwargs)
    return DepositProduct(**defaults)


@pytest.mark.django_db
class TestSourceTax:
    def test_bank_with_tin(self, tax_rules):
        product = make_product()
        assert maturity.source_tax_rate_pct(product, has_tin=True) == Decimal("10")

    def test_bank_without_tin(self, tax_rules):
        product = make_product()
        assert maturity.source_tax_rate_pct(product, has_tin=False) == Decimal("15")

    def test_sanchayapatra_thresholds(self, tax_rules):
        product = make_product(
            is_benchmark=True,
            slug="national-savings-directorate-sanchayapatra-paribar-sanchayapatra",
        )
        assert maturity.source_tax_rate_pct(
            product, total_holding=Decimal("500000")
        ) == Decimal("5")
        assert maturity.source_tax_rate_pct(
            product, total_holding=Decimal("500001")
        ) == Decimal("10")

    def test_pensioner_exemption(self, tax_rules):
        product = make_product(
            is_benchmark=True,
            slug="national-savings-directorate-sanchayapatra-pensioner-sanchayapatra",
        )
        assert maturity.source_tax_rate_pct(
            product, total_holding=Decimal("500000")
        ) == Decimal("0")
        assert maturity.source_tax_rate_pct(
            product, total_holding=Decimal("600000")
        ) == Decimal("10")


@pytest.mark.django_db
class TestEvaluateProduct:
    def test_fdr_net_of_tax(self, tax_rules):
        product = make_product()
        row = DepositRate(
            product=product,
            tenure_months_min=12,
            tenure_months_max=24,
            rate_min=Decimal("8.25"),
            rate_max=Decimal("8.25"),
        )
        result = maturity.evaluate_product(
            product, row, months=12, amount=Decimal("500000"), has_tin=True
        )
        # gross 541,250; interest 41,250; tax 10% = 4,125; net 537,125.
        assert result["gross_maturity"] == Decimal("541250.00")
        assert result["interest_earned"] == Decimal("41250.00")
        assert result["source_tax"] == Decimal("4125.00")
        assert result["net_maturity"] == Decimal("537125.00")

    def test_range_ranked_at_lower_bound(self, tax_rules):
        product = make_product()
        row = DepositRate(
            product=product,
            tenure_months_min=12,
            tenure_months_max=24,
            rate_min=Decimal("7.25"),
            rate_max=Decimal("8.00"),
        )
        result = maturity.evaluate_product(
            product, row, months=12, amount=Decimal("100000"), has_tin=True
        )
        assert result["is_range"] is True
        # Ranking figure uses 7.25 (lower bound).
        assert result["gross_maturity"] == Decimal("107250.00")
        assert result["net_maturity_at_max_rate"] is not None
        assert result["net_maturity_at_max_rate"] > result["net_maturity"]
