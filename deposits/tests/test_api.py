"""API tests for deposit products: list/detail, scenario ranking, history."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from deposits.models import DepositProduct, DepositRate, DepositTaxRule

LIST_URL = "/api/v1/deposit-products/"
SCENARIO_URL = "/api/v1/deposit-products/scenario/"


@pytest.fixture
def client():
    return APIClient()


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


def make_product(bank=None, institution_name="", verified=True, **kwargs):
    defaults = {
        "kind": "fdr",
        "name": "Test Product",
        "verification_status": (
            VerificationStatus.VERIFIED if verified else VerificationStatus.DRAFT
        ),
    }
    defaults.update(kwargs)
    return DepositProduct.objects.create(
        bank=bank, institution_name=institution_name, **defaults
    )


def add_rate(product, t_min, t_max, rate, rate_max=None):
    return DepositRate.objects.create(
        product=product,
        tenure_months_min=t_min,
        tenure_months_max=t_max,
        rate_min=Decimal(rate),
        rate_max=Decimal(rate_max if rate_max is not None else rate),
    )


@pytest.fixture
def catalogue(db):
    bank_a = Bank.objects.create(name="Alpha Bank")
    bank_b = Bank.objects.create(name="Beta Bank")
    high = make_product(bank=bank_a, name="Alpha FDR")
    add_rate(high, 6, 24, "9.00")
    low = make_product(bank=bank_b, name="Beta FDR")
    add_rate(low, 6, 24, "8.00")
    long_only = make_product(bank=bank_b, name="Beta Long FDR")
    add_rate(long_only, 36, 36, "10.00")
    islamic = make_product(
        bank=bank_a,
        name="Alpha Mudaraba",
        is_islamic=True,
        rate_type="expected_profit",
    )
    add_rate(islamic, 6, 24, "8.50")
    draft = make_product(bank=bank_a, name="Draft FDR", verified=False)
    add_rate(draft, 6, 24, "12.00")
    benchmark = make_product(
        institution_name="National Savings Directorate (Sanchayapatra)",
        name="Benchmark Scheme",
        kind="scheme",
        is_benchmark=True,
        compounding="at_maturity",
    )
    add_rate(benchmark, 12, 12, "11.83")
    dps = make_product(bank=bank_a, name="Alpha DPS", kind="dps")
    add_rate(dps, 36, 120, "9.50")
    return {
        "high": high,
        "low": low,
        "islamic": islamic,
        "benchmark": benchmark,
        "dps": dps,
    }


@pytest.mark.django_db
class TestListAndDetail:
    def test_list_excludes_drafts(self, client, catalogue):
        response = client.get(LIST_URL)
        assert response.status_code == 200
        names = {r["name"] for r in response.data["results"]}
        assert "Draft FDR" not in names
        assert "Alpha FDR" in names

    def test_kind_filter(self, client, catalogue):
        response = client.get(LIST_URL, {"kind": "dps"})
        names = {r["name"] for r in response.data["results"]}
        assert names == {"Alpha DPS"}

    def test_benchmark_flag_filter(self, client, catalogue):
        response = client.get(LIST_URL, {"is_benchmark": "true"})
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["is_benchmark"] is True

    def test_detail_by_slug_includes_rates(self, client, catalogue):
        slug = catalogue["high"].slug
        response = client.get(f"{LIST_URL}{slug}/")
        assert response.status_code == 200
        assert response.data["slug"] == slug
        assert len(response.data["rates"]) == 1
        assert response.data["institution_display_name"] == "Alpha Bank"


@pytest.mark.django_db
class TestScenario:
    def test_fdr_ranking_by_net_maturity(self, client, catalogue, tax_rules):
        response = client.post(
            SCENARIO_URL,
            {"kind": "fdr", "amount": "500000", "months": 12},
            format="json",
        )
        assert response.status_code == 200
        data = response.data
        names = [r["product"]["name"] for r in data["results"]]
        # 9.00% ranks above 8.50% (Islamic) above 8.00%; the 36-month-only
        # product has no covering rate and is counted as excluded.
        assert names == ["Alpha FDR", "Alpha Mudaraba", "Beta FDR"]
        assert data["excluded_without_rate"] == 1
        top = data["results"][0]
        # 500,000 at 9% annual = 545,000 gross; interest 45,000; tax 10%.
        assert Decimal(top["gross_maturity"]) == Decimal("545000.00")
        assert Decimal(top["net_maturity"]) == Decimal("540500.00")

    def test_benchmarks_separate_from_ranking(self, client, catalogue, tax_rules):
        response = client.post(
            SCENARIO_URL,
            {"kind": "fdr", "amount": "500000", "months": 12},
            format="json",
        )
        data = response.data
        ranked_names = {r["product"]["name"] for r in data["results"]}
        assert "Benchmark Scheme" not in ranked_names
        assert len(data["benchmarks"]) == 1
        bench = data["benchmarks"][0]
        assert bench["product"]["is_benchmark"] is True
        # 500,000 at 11.83% simple = 559,150 gross; interest 59,150;
        # sanchayapatra tax at exactly 5 lakh holding = 5% -> 2,957.50.
        assert Decimal(bench["gross_maturity"]) == Decimal("559150.00")
        assert Decimal(bench["source_tax"]) == Decimal("2957.50")

    def test_islamic_only_filter(self, client, catalogue, tax_rules):
        response = client.post(
            SCENARIO_URL,
            {
                "kind": "fdr",
                "amount": "100000",
                "months": 12,
                "islamic_only": True,
            },
            format="json",
        )
        names = [r["product"]["name"] for r in response.data["results"]]
        assert names == ["Alpha Mudaraba"]

    def test_dps_scenario(self, client, catalogue, tax_rules):
        response = client.post(
            SCENARIO_URL,
            {"kind": "dps", "monthly_instalment": "500", "months": 36},
            format="json",
        )
        assert response.status_code == 200
        results = response.data["results"]
        assert [r["product"]["name"] for r in results] == ["Alpha DPS"]
        # DBBL-published maturity for 500/mo at 9.50% over 3 years.
        gross = Decimal(results[0]["gross_maturity"])
        assert abs(gross - Decimal("20897")) < Decimal("1")

    def test_dps_scenario_includes_benchmarks_not_results(
        self, client, catalogue, tax_rules
    ):
        # Benchmarks are kind="scheme": a DPS scenario must still surface
        # them in `benchmarks` (evaluated on total contributions) and
        # never rank them among bank products.
        response = client.post(
            SCENARIO_URL,
            {"kind": "dps", "monthly_instalment": "500", "months": 12},
            format="json",
        )
        assert response.status_code == 200
        data = response.data
        ranked_names = {r["product"]["name"] for r in data["results"]}
        assert "Benchmark Scheme" not in ranked_names
        # The only DPS product's rates start at 36 months, so at a
        # 12-month horizon nothing is ranked.
        assert data["results"] == []
        assert len(data["benchmarks"]) == 1
        bench = data["benchmarks"][0]
        assert bench["product"]["name"] == "Benchmark Scheme"
        # Total contributions 500 x 12 = 6,000 as a lump sum at 11.83%
        # simple (at_maturity) for 12 months -> 6,709.80 gross; holding
        # 6,000 <= 5 lakh -> 5% source tax on the 709.80 interest.
        assert Decimal(bench["gross_maturity"]) == Decimal("6709.80")
        assert Decimal(bench["source_tax"]) == Decimal("35.49")
        assert Decimal(bench["net_maturity"]) == Decimal("6674.31")

    def test_scenario_validation(self, client, catalogue):
        response = client.post(SCENARIO_URL, {"kind": "dps", "months": 12}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestFieldHistory:
    def test_anonymous_ok(self, client, catalogue):
        """Field history is public (redesign decision D1)."""
        slug = catalogue["high"].slug
        response = client.get(f"{LIST_URL}{slug}/field-history/")
        assert response.status_code == 200
        assert "results" in response.data

    def test_authenticated_ok(self, client, catalogue):
        user = get_user_model().objects.create_user(
            username="history-reader", password="x"
        )
        client.force_authenticate(user)
        slug = catalogue["high"].slug
        response = client.get(f"{LIST_URL}{slug}/field-history/")
        assert response.status_code == 200
