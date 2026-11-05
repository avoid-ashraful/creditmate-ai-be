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
            + Decimal(result["at_min_rate"]["total_interest_or_profit"])
            + Decimal("5750.00")
        )
        self.assertEqual(total_min, expected)
        self.assertEqual(result["band"]["source"], "annexure_a")
        # A product's own band carries no chart category
        self.assertIsNone(result["band"]["category"])
        # The neutral key replaced the old "total_interest" key entirely
        self.assertNotIn("total_interest", result["at_min_rate"])

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
        # The fallback band discloses its chart category
        self.assertEqual(fallback["band"]["category"], "consumer_credit")
        self.assertIsNotNone(fallback["at_min_rate"])

    def test_chart_fallback_category_for_car_and_detail(self):
        # A band-less CAR product falls back to the bank's blended
        # consumer-credit band (the BB chart has no car column) — both
        # the scenario band and the detail effective_rate must say so.
        car = make_product(
            self.bank,
            name="No Own Band Car Loan",
            loan_type="car",
            amount_max_bdt=6000000,
            tenure_max_months=84,
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
            {"loan_type": "car", "amount": 2000000, "tenure_months": 60},
            format="json",
        )
        results = {r["product"]["name"]: r for r in response.data["results"]}
        self.assertEqual(results["No Own Band Car Loan"]["band"]["source"], "bb_chart")
        self.assertEqual(
            results["No Own Band Car Loan"]["band"]["category"], "consumer_credit"
        )
        # Detail serializer: effective_rate carries the same category
        response = self.client.get(f"/api/v1/loan-products/{car.slug}/")
        self.assertEqual(response.data["effective_rate"]["source"], "bb_chart")
        self.assertEqual(response.data["effective_rate"]["category"], "consumer_credit")
        # ...while a product with its own band carries category None
        response = self.client.get(f"/api/v1/loan-products/{self.personal.slug}/")
        self.assertEqual(response.data["effective_rate"]["source"], "annexure_a")
        self.assertIsNone(response.data["effective_rate"]["category"])

    def _scenario_personal(self, **overrides):
        payload = {
            "loan_type": "personal",
            "amount": 500000,
            "tenure_months": 36,
            "monthly_income": 40000,
        }
        payload.update(overrides)
        response = self.client.post(
            "/api/v1/loan-products/scenario/", payload, format="json"
        )
        self.assertEqual(response.status_code, 200)
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        return results[self.personal.slug]

    def test_scenario_income_between_segments_warns_without_flag(self):
        # Minima: salaried 30,000 / business 50,000. Income 40,000 with
        # no segment given: meets salaried, misses business -> warning
        # naming both sides, NO hard income flag, still eligible.
        result = self._scenario_personal()
        self.assertTrue(result["eligible"])
        flag_codes = [f["code"] for f in result["flags"]]
        self.assertNotIn("income_below_minimum", flag_codes)
        warnings = {w["code"]: w["message"] for w in result["warnings"]}
        self.assertIn("income_segment_dependent", warnings)
        self.assertIn("salaried", warnings["income_segment_dependent"])
        self.assertIn("business", warnings["income_segment_dependent"])

    def test_scenario_income_with_segment_below_its_minimum_flags(self):
        result = self._scenario_personal(segment="business")
        self.assertFalse(result["eligible"])
        codes = [f["code"] for f in result["flags"]]
        self.assertIn("income_below_minimum", codes)
        flag = next(f for f in result["flags"] if f["code"] == "income_below_minimum")
        self.assertIn("business", flag["message"])
        self.assertIn("50,000", flag["message"])

    def test_scenario_income_with_segment_meeting_its_minimum_is_clean(self):
        result = self._scenario_personal(segment="salaried")
        self.assertTrue(result["eligible"])
        self.assertNotIn("income_below_minimum", [f["code"] for f in result["flags"]])
        self.assertNotIn(
            "income_segment_dependent", [w["code"] for w in result["warnings"]]
        )

    def test_scenario_income_below_all_segments_flags(self):
        result = self._scenario_personal(monthly_income=20000)
        self.assertFalse(result["eligible"])
        self.assertIn("income_below_minimum", [f["code"] for f in result["flags"]])

    def test_unsecured_warning_despite_higher_published_product_limit(self):
        # Pubali shape: the product publishes an unsecured limit (Tk 20
        # lakh for its own salary-account holders) ABOVE the BB ceiling
        # (Tk 10 lakh). Amounts between the ceiling and the product
        # limit must still get the regulatory warning.
        pubali_like = make_product(
            self.bank,
            name="Generous Unsecured Loan",
            rate_min=Decimal("10.00"),
            rate_max=Decimal("12.00"),
            rate_source="product_page",
            amount_max_bdt=4000000,
            tenure_max_months=96,
            unsecured_max_bdt=2000000,
        )
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {"loan_type": "personal", "amount": 1500000, "tenure_months": 60},
            format="json",
        )
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        warnings = {
            w["code"]: w["message"] for w in results[pubali_like.slug]["warnings"]
        }
        self.assertIn("security_may_be_required", warnings)
        self.assertIn("1,000,000", warnings["security_may_be_required"])
        # Above the product's own published limit, its message wins
        response = self.client.post(
            "/api/v1/loan-products/scenario/",
            {"loan_type": "personal", "amount": 2500000, "tenure_months": 60},
            format="json",
        )
        results = {r["product"]["slug"]: r for r in response.data["results"]}
        warnings = {
            w["code"]: w["message"] for w in results[pubali_like.slug]["warnings"]
        }
        self.assertIn("2,000,000", warnings["security_may_be_required"])

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
            Decimal(result["at_min_rate"]["total_interest_or_profit"]),
            Decimal("2250000.00"),
        )
        self.assertEqual(Decimal(result["at_min_rate"]["emi"]), Decimal("10833.33"))

    def test_field_history_is_public(self):
        """Field history is public (redesign decision D1): anonymous and
        authenticated users get the same payload."""
        response = self.client.get(
            f"/api/v1/loan-products/{self.personal.slug}/field-history/"
        )
        self.assertEqual(response.status_code, 200)
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
