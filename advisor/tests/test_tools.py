"""Tool-layer tests: real services, no LLM involved (plan §7.3 PR 2.1)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from advisor import tools
from advisor.tools import run_tool
from banks.factories import BankFactory
from credit_cards.factories import CreditCardFactory
from credit_cards.constants import VerificationStatus
from loans.models import LoanProduct


def make_card(**kwargs):
    kwargs.setdefault("verification_status", VerificationStatus.VERIFIED)
    kwargs.setdefault("is_active", True)
    return CreditCardFactory(**kwargs)


@pytest.mark.django_db
class TestSearchAndDetail:
    def test_search_returns_public_only(self):
        bank = BankFactory(name="Advisor Bank")
        make_card(bank=bank, name="Advisor Gold")
        CreditCardFactory(
            bank=bank, name="Draft Card", verification_status=VerificationStatus.DRAFT
        )
        out, _ = run_tool("search_cards", {"query": "Advisor"})
        names = [c.name for c in out.cards]
        assert "Advisor Gold" in names
        assert "Draft Card" not in names

    def test_detail_and_missing_apr_is_none_not_zero(self):
        card = make_card(name="No APR Card", interest_rate_apr=None, is_islamic=True)
        out, _ = run_tool("get_card_detail", {"card_id": card.id})
        assert out.card.apr_percent is None

    def test_compare_reports_differing_fields(self):
        a = make_card(
            name="A", annual_fee=Decimal("1500"), interest_rate_apr=Decimal("25")
        )
        b = make_card(name="B", annual_fee=Decimal("0"), interest_rate_apr=Decimal("25"))
        out, _ = run_tool("compare_cards", {"card_ids": [a.id, b.id]})
        assert "annual_fee_bdt" in out.differing_fields
        assert "apr_percent" not in out.differing_fields

    def test_compare_requires_two_to_four(self):
        with pytest.raises(ValidationError):
            run_tool("compare_cards", {"card_ids": [1]})


@pytest.mark.django_db
class TestEligibilityTool:
    def test_verdicts_use_engine_vocabulary(self):
        make_card(name="Income Card", min_monthly_income=Decimal("30000"))
        out, _ = run_tool(
            "check_eligibility",
            {"monthly_income_bdt": "60000", "cib_status": "clean"},
        )
        verdicts = {r.verdict for r in out.results}
        assert verdicts <= {"eligible", "likely", "unknown", "not_yet"}
        assert out.disclaimer  # engine disclaimer carried through

    def test_no_eligibility_fields_on_advisor_models(self):
        """The privacy invariant, pinned: no model may gain such a field."""
        from advisor.models import AdvisorMessage, AdvisorSession

        forbidden = ("income", "tin", "cib", "employment")
        for model in (AdvisorSession, AdvisorMessage):
            field_names = [f.name for f in model._meta.get_fields()]
            for name in field_names:
                assert not any(
                    word in name for word in forbidden
                ), f"{model.__name__}.{name} would persist eligibility inputs"


@pytest.mark.django_db
class TestCalculatorTool:
    def test_emi_matches_loans_costs(self):
        out, _ = run_tool(
            "calculate_emi_or_payoff",
            {
                "mode": "emi",
                "principal_bdt": "100000",
                "annual_rate_percent": "12",
                "months": 12,
            },
        )
        assert out.monthly_emi_bdt == "8884.88"  # textbook value

    def test_payoff_warns_when_payment_below_first_interest(self):
        out, _ = run_tool(
            "calculate_emi_or_payoff",
            {
                "mode": "payoff",
                "principal_bdt": "100000",
                "annual_rate_percent": "25",
                "monthly_payment_bdt": "1000",
            },
        )
        assert out.months_to_clear is None
        assert out.warning and "does not cover" in out.warning

    def test_missing_apr_never_treated_as_zero(self):
        card = make_card(name="Islamic", is_islamic=True, interest_rate_apr=None)
        with pytest.raises(ValueError):
            run_tool(
                "calculate_emi_or_payoff",
                {
                    "mode": "emi",
                    "principal_bdt": "10000",
                    "card_id": card.id,
                    "months": 6,
                },
            )


@pytest.mark.django_db
class TestSearchProducts:
    def test_loans_return_bands_and_profit_label(self):
        bank = BankFactory(name="Loan Bank")
        LoanProduct.objects.create(
            bank=bank,
            name="Home Loan X",
            loan_type="home",
            rate_min=Decimal("8.50"),
            rate_max=Decimal("11.00"),
            is_active=True,
            verification_status=VerificationStatus.VERIFIED,
        )
        out, _ = run_tool("search_products", {"product_type": "loans"})
        assert len(out.products) == 1
        product = out.products[0]
        assert product.rate_min_percent == "8.50"
        assert product.rate_max_percent == "11.00"
        assert product.rate_kind == "interest"


class TestRegistry:
    def test_all_tools_read_only(self):
        assert tools.TOOL_REGISTRY
        assert all(s.scope == "read-only" for s in tools.TOOL_REGISTRY.values())
        assert set(tools.TOOL_REGISTRY) == set(tools.TOOL_FUNCTIONS)

    def test_retrieve_grounding_degrades_without_retrieval_app(self):
        out, _ = run_tool("retrieve_grounding", {"query": "travel card"})
        # retrieval app may or may not be merged; either way no exception
        assert isinstance(out.available, bool)
        if not out.available:
            assert out.chunks == []

    def test_forbidden_phrase_detection(self):
        assert tools.contains_forbidden_phrase("You are pre-approved!")
        assert not tools.contains_forbidden_phrase("The bank decides.")
