"""Hand-computed EMI / total-cost checks for loans.costs.

Expected figures were computed independently (standard amortisation
formula + month-by-month schedule) before being written here:

* Tk 10,00,000 at 11.72% for 60 months -> EMI ~= 22,103.21,
  total interest ~= 326,192.80
* Tk 10,00,000 at 9.72% for 60 months -> EMI ~= 21,109.54,
  total interest ~= 266,572.12
* Tk 5,00,000 at 12% for 12 months -> EMI ~= 44,424.39,
  total interest ~= 33,092.74
"""

from decimal import Decimal

from django.test import SimpleTestCase

from loans import costs


class EmiMathTests(SimpleTestCase):
    def test_emi_at_band_max(self):
        emi = costs.monthly_emi(1_000_000, Decimal("11.72"), 60)
        self.assertAlmostEqual(emi, Decimal("22103.21"), delta=Decimal("1.00"))

    def test_emi_at_band_min(self):
        emi = costs.monthly_emi(1_000_000, Decimal("9.72"), 60)
        self.assertAlmostEqual(emi, Decimal("21109.54"), delta=Decimal("1.00"))

    def test_totals_from_simulation(self):
        emi, total_interest, total = costs.amortisation_totals(500_000, Decimal("12"), 12)
        self.assertAlmostEqual(emi, Decimal("44424.39"), delta=Decimal("1.00"))
        self.assertAlmostEqual(total_interest, Decimal("33092.74"), delta=Decimal("5.00"))
        self.assertEqual(total, Decimal("500000") + total_interest)

    def test_zero_rate(self):
        emi, total_interest, total = costs.amortisation_totals(120_000, Decimal("0"), 12)
        self.assertEqual(emi, Decimal("10000.00"))
        self.assertEqual(total_interest, Decimal("0"))
        self.assertEqual(total, Decimal("120000"))

    def test_simple_interest_bhbfc_style(self):
        # Tk 10 lakh at 9% simple for 25 years: interest = 10,00,000*9%*25
        emi, total_interest, total = costs.amortisation_totals(
            1_000_000, Decimal("9"), 300, simple_interest=True
        )
        self.assertEqual(total_interest, Decimal("2250000.00"))
        self.assertEqual(emi, Decimal("10833.33"))
        self.assertEqual(total, Decimal("3250000.00"))


class ProcessingFeeTests(SimpleTestCase):
    class _Product:
        processing_fee_percent = Decimal("0.50")
        processing_fee_percent_max = None
        processing_fee_cap_bdt = 15000

    def test_cap_applies(self):
        fee = costs.processing_fee(self._Product(), 1_000_000)
        # 0.50% of 10 lakh = 5,000 (below the 15,000 cap)
        self.assertEqual(fee, Decimal("5000.00"))
        fee = costs.processing_fee(self._Product(), 10_000_000)
        # 0.50% of 1 crore = 50,000 -> capped at 15,000
        self.assertEqual(fee, Decimal("15000.00"))

    def test_range_uses_highest_percent(self):
        product = self._Product()
        product.processing_fee_percent_max = Decimal("1.00")
        product.processing_fee_cap_bdt = None
        fee = costs.processing_fee(product, 1_000_000)
        self.assertEqual(fee, Decimal("10000.00"))

    def test_vat(self):
        self.assertEqual(costs.fee_with_vat(Decimal("10000")), Decimal("11500.00"))
        self.assertIsNone(costs.fee_with_vat(None))
