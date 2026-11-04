"""Regulatory-cap flagging tests (flags are warnings, never errors)."""

import datetime
from decimal import Decimal

from django.test import TestCase

from banks.models import Bank
from credit_cards.constants import VerificationStatus
from loans.caps import product_cap_flags
from loans.models import LoanProduct, RegulatoryCap


class CapFlagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bank = Bank.objects.create(name="Cap Bank PLC")
        RegulatoryCap.objects.create(
            key="personal_loan_ceiling",
            effective_from=datetime.date(2026, 5, 5),
            params={
                "max_amount_bdt": 4000000,
                "unsecured_max_bdt": 1000000,
                "max_tenure_months": 96,
            },
        )
        RegulatoryCap.objects.create(
            key="housing_loan_ceiling",
            effective_from=datetime.date(2026, 1, 1),
            params={"max_amount_bdt": 40000000, "ltv_percent": 70},
        )

    def _product(self, **kwargs):
        defaults = {
            "bank": self.bank,
            "verification_status": VerificationStatus.VERIFIED,
        }
        defaults.update(kwargs)
        return LoanProduct(**defaults)

    def test_unsecured_marketing_flag(self):
        product = self._product(
            name="Big Unsecured",
            loan_type="personal",
            amount_max_bdt=4000000,  # marketed unsecured (no secured_by)
        )
        flags = product_cap_flags(product)
        self.assertTrue(any("unsecured" in f for f in flags))

    def test_within_caps_no_flags(self):
        product = self._product(
            name="Small Loan",
            loan_type="personal",
            amount_max_bdt=1000000,
            tenure_max_months=60,
        )
        self.assertEqual(product_cap_flags(product), [])

    def test_tenure_flag(self):
        product = self._product(
            name="Long Loan",
            loan_type="personal",
            amount_max_bdt=500000,
            tenure_max_months=120,
        )
        flags = product_cap_flags(product)
        self.assertTrue(any("96-month" in f for f in flags))

    def test_housing_ltv_flag(self):
        product = self._product(
            name="NRB Home",
            loan_type="home",
            amount_max_bdt=40000000,
            ltv_percent=Decimal("75"),
        )
        flags = product_cap_flags(product)
        self.assertTrue(any("75" in f and "LTV" in f for f in flags))

    def test_secured_products_exempt(self):
        product = self._product(
            name="Fast Loan",
            loan_type="secured_against_deposit",
            amount_max_bdt=100000000,
        )
        self.assertEqual(product_cap_flags(product), [])
