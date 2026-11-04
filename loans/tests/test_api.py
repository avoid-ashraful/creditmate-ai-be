"""API tests: filters, scenario costing/flags, history auth, caps."""

import datetime
from decimal import Decimal

from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.test import TestCase

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from loans.models import LoanChartBand, LoanProduct, RegulatoryCap

VERIFIED = VerificationStatus.VERIFIED


def make_product(bank, **kwargs):
    defaults = {
        "bank": bank,
        "loan_type": "personal",
        "verification_status": VERIFIED,
        "is_active": True,
    }
    defaults.update(kwargs)
    return LoanProduct.objects.create(**defaults)


class LoanApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bank = Bank.objects.create(name="Test Bank PLC")
        cls.islamic_bank = Bank.objects.create(name="Test Islami Bank PLC")
        cls.personal = make_product(
            cls.bank,
            name="Test Personal Loan",
            rate_min=Decimal("9.72"),
            rate_max=Decimal("11.72"),
            rate_source="annexure_a",
            amount_min_bdt=50000,
            amount_max_bdt=2000000,
            tenure_min_months=12,
            tenure_max_months=60,
            min_income_by_segment={"salaried": 30000, "business": 50000},
            processing_fee_percent=Decimal("0.50"),
            processing_fee_cap_bdt=15000,
        )
        cls.islamic = make_product(
            cls.islamic_bank,
            name="Test Islamic Finance",
            is_islamic=True,
            rate_min=Decimal("14.00"),
            rate_max=Decimal("15.00"),
            rate_source="annexure_a",
        )
        cls.draft = make_product(
            cls.bank,
            name="Draft Loan",
            verification_status=VerificationStatus.DRAFT,
        )
        RegulatoryCap.objects.create(
            key="personal_loan_ceiling",
            effective_from=datetime.date(2026, 5, 5),
            params={
                "max_amount_bdt": 4000000,
                "unsecured_max_bdt": 1000000,
                "max_tenure_months": 96,
            },
        )

    def setUp(self):
        # Reset throttle buckets between tests (dedicated test Redis DB).
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()

    def test_list_only_public(self):
        response = self.client.get("/api/v1/loan-products/")
        names = [row["name"] for row in response.data["results"]]
        self.assertIn("Test Personal Loan", names)
        self.assertNotIn("Draft Loan", names)

    def test_filters(self):
        response = self.client.get("/api/v1/loan-products/", {"is_islamic": "true"})
        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Test Islamic Finance"])
        response = self.client.get("/api/v1/loan-products/", {"amount": 3000000})
        names = [row["name"] for row in response.data["results"]]
        self.assertNotIn("Test Personal Loan", names)  # max 20 lakh

    def test_islamic_rate_label(self):
        response = self.client.get(f"/api/v1/loan-products/{self.islamic.slug}/")
        self.assertEqual(response.data["rate_label"], "expected_profit")
        response = self.client.get(f"/api/v1/loan-products/{self.personal.slug}/")
        self.assertEqual(response.data["rate_label"], "interest")

    def test_scenario_band_ends(self):
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {
                "loan_type": "personal",
                "amount": 1000000,
                "tenure_months": 60,
                "monthly_income": 80000,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        result = results[self.personal.slug]
        self.assertTrue(result["eligible"])
        # Hand-computed: EMI at 9.72% ~= 21,109.54; at 11.72% ~= 22,103.21
        self.assertAlmostEqual(
            Decimal(result["at_min_rate"]["emi"]),
            Decimal("21109.54"),
            delta=Decimal("1.00"),
        )
        self.assertAlmostEqual(
            Decimal(result["at_max_rate"]["emi"]),
            Decimal("22103.21"),
            delta=Decimal("1.00"),
        )
        # Processing fee 0.50% of 10 lakh = 5,000; +15% VAT = 5,750, in total cost
        self.assertEqual(Decimal(result["processing_fee"]), Decimal("5000.00"))
        total_min = Decimal(result["at_min_rate"]["total_cost"])
        expected = (
            Decimal("1000000")
            + Decimal(result["at_min_rate"]["total_interest"])
            + Decimal("5750.00")
        )
        self.assertEqual(total_min, expected)
        self.assertEqual(result["band"]["source"], "annexure_a")

    def test_scenario_flags(self):
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {
                "loan_type": "personal",
                "amount": 3000000,
                "tenure_months": 84,
                "monthly_income": 20000,
            },
            format="json",
        )
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        result = results[self.personal.slug]
        self.assertFalse(result["eligible"])
        codes = [f["code"] for f in result["flags"]]
        self.assertIn("amount_above_max", codes)
        self.assertIn("tenure_above_max", codes)
        self.assertIn("income_below_minimum", codes)
        income_flag = next(
            f for f in result["flags"] if f["code"] == "income_below_minimum"
        )
        # The reason quotes the published segment figures
        self.assertIn("salaried Tk 30,000", income_flag["message"])
        self.assertIn("business Tk 50,000", income_flag["message"])

    def test_scenario_chart_fallback_band(self):
        make_product(
            self.bank,
            name="No Own Band Loan",
            amount_max_bdt=4000000,
            tenure_max_months=96,
        )
        LoanChartBand.objects.create(
            bank=self.bank,
            category="consumer_credit",
            rate_min=Decimal("10.00"),
            rate_max=Decimal("12.00"),
            edition_label="October, 2026",
        )
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {"loan_type": "personal", "amount": 500000, "tenure_months": 36},
            format="json",
        )
        results = {r["product"]["name"]: r for r in response.data["results"]}
        fallback = results["No Own Band Loan"]
        self.assertEqual(fallback["band"]["source"], "bb_chart")
        self.assertIsNotNone(fallback["at_min_rate"])

    def test_scenario_formula_product_has_no_emi(self):
        make_product(
            self.bank,
            name="Formula Loan",
            loan_type="secured_against_deposit",
            spread_over_deposit_rate=Decimal("3.00"),
        )
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {
                "loan_type": "secured_against_deposit",
                "amount": 500000,
                "tenure_months": 36,
            },
            format="json",
        )
        results = {r["product"]["name"]: r for r in response.data["results"]}
        formula = results["Formula Loan"]
        self.assertIsNone(formula["band"])
        self.assertIsNone(formula["at_min_rate"])
        self.assertIn("spread", formula["note"])

    def test_scenario_simple_interest(self):
        bhbfc = make_product(
            None,
            institution_name="BHBFC Test",
            lender_type="govt",
            name="Simple Home",
            loan_type="home",
            rate_min=Decimal("9.00"),
            rate_max=Decimal("9.00"),
            rate_source="manual",
            uses_simple_interest=True,
            tenure_max_months=360,
        )
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {"loan_type": "home", "amount": 1000000, "tenure_months": 300},
            format="json",
        )
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        result = results[bhbfc.slug]
        self.assertEqual(
            Decimal(result["at_min_rate"]["total_interest"]),
            Decimal("2250000.00"),
        )
        self.assertEqual(Decimal(result["at_min_rate"]["emi"]), Decimal("10833.33"))

    def test_field_history_requires_auth(self):
        response = self.client.get(
            f"/api/v1/loan-products/{self.personal.slug}/field-history/"
        )
        self.assertEqual(response.status_code, 403)
        user = get_user_model().objects.create_user(username="loan-tester", password="x")
        self.client.force_authenticate(user)
        response = self.client.get(
            f"/api/v1/loan-products/{self.personal.slug}/field-history/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        # A tracked change is recorded by the signal
        self.personal.rate_max = Decimal("12.50")
        self.personal.save()
        response = self.client.get(
            f"/api/v1/loan-products/{self.personal.slug}/field-history/"
        )
        fields = [row["field_name"] for row in response.data]
        self.assertIn("rate_max", fields)

    def test_regulatory_caps_action(self):
        response = self.client.get("/api/v1/loan-products/regulatory-caps/")
        self.assertEqual(response.status_code, 200)
        keys = [row["key"] for row in response.data]
        self.assertIn("personal_loan_ceiling", keys)
