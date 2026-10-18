"""Crawler safety: drafts, no overwrite of verified cards, sanity rules, approvals."""

import pytest

from django.core.exceptions import ValidationError

from banks.enums import ReviewSource, ReviewStatus
from banks.factories import BankFactory
from banks.models import ReviewQueue
from banks.services import CreditCardDataService, ReviewQueueService
from banks.services.llm_parser import LLMContentParser
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard, CreditCardFieldHistory


@pytest.fixture()
def bank():
    return BankFactory()


@pytest.fixture()
def service():
    return CreditCardDataService()


def crawl(service, bank, **card):
    return service.update_credit_card_data(bank.id, [card])


@pytest.mark.django_db()
class TestNewCards:
    def test_new_card_is_created_as_non_public_draft(self, service, bank):
        crawl(service, bank, name="Fresh", annual_fee=500, interest_rate_apr=20)
        card = CreditCard.objects.get(bank=bank, name="Fresh")
        assert card.verification_status == "draft"
        assert not card.is_public
        assert card.annual_fee == 500

    @pytest.mark.parametrize(
        "values",
        [
            {"interest_rate_apr": 30},
            {"interest_rate_apr": 25.01},
            {"interest_rate_apr": -5},
            {"annual_fee": -100},
            {"annual_fee": 100001},
        ],
    )
    def test_sanity_failures_force_needs_review(self, service, bank, values):
        crawl(service, bank, name="Odd", **values)
        assert CreditCard.objects.get(name="Odd").verification_status == "needs_review"

    def test_boundary_values_stay_draft(self, service, bank):
        crawl(service, bank, name="Edge", annual_fee=100000, interest_rate_apr=25)
        assert CreditCard.objects.get(name="Edge").verification_status == "draft"

    @pytest.mark.parametrize(
        "name",
        [
            "Nexus Debit Card",
            "Visa/ Mastercard (International) Debit Card",
            "Prepaid Card",
        ],
    )
    def test_debit_and_prepaid_cards_are_not_added(self, service, bank, name):
        assert crawl(service, bank, name=name, annual_fee=500) == 0
        assert not CreditCard.objects.filter(bank=bank).exists()

    def test_text_fields_are_cut_to_each_model_field_length(self, service, bank):
        long_text = "x" * 1500
        crawl(
            service,
            bank,
            name="Long",
            cash_advance_fee=long_text,
            late_payment_fee=long_text,
            lounge_access_international=long_text,
            supplementary_card_fee=long_text,
        )
        card = CreditCard.objects.get(bank=bank, name="Long")
        assert len(card.cash_advance_fee) == 255
        assert len(card.late_payment_fee) == 255
        assert len(card.supplementary_card_fee) == 255
        assert len(card.lounge_access_international) == 1000

    @pytest.mark.parametrize("name", ["", "   ", None, "TK. 5,000", "5,000"])
    def test_missing_or_fee_like_name_is_skipped(self, service, bank, name):
        assert crawl(service, bank, name=name, annual_fee=500) == 0
        assert not CreditCard.objects.filter(bank=bank).exists()

    def test_new_fields_are_normalized_and_unknowns_stay_unset(self, service, bank):
        crawl(
            service,
            bank,
            name="Rich",
            card_network="Visa",
            is_islamic="yes",
            is_dual_currency=None,
            min_monthly_income="BDT 50,000",
            supplementary_card_fee="Free",
            foreign_transaction_fee=None,
            source_url="https://bank.test/rich",
            apply_url="javascript:alert(1)",
        )
        card = CreditCard.objects.get(name="Rich")
        assert card.card_network == "visa"
        assert card.is_islamic is True
        assert card.is_dual_currency is None
        assert card.min_monthly_income == 50000
        assert card.supplementary_card_fee == "Free"
        assert card.foreign_transaction_fee == ""
        assert card.source_url == "https://bank.test/rich"
        assert card.apply_url == ""


@pytest.mark.django_db()
class TestVerifiedCardsAreNeverOverwritten:
    def test_differing_values_become_review_proposals(self, service, bank):
        card = CreditCardFactory(
            bank=bank, name="Gold", annual_fee=1000, cash_advance_fee="2.5%"
        )
        crawl(service, bank, name="Gold", annual_fee=2000, cash_advance_fee="2.5%")

        card.refresh_from_db()
        assert card.annual_fee == 1000
        item = ReviewQueue.objects.get()
        assert item.source == ReviewSource.CRAWLER_PROPOSAL
        assert (item.credit_card, item.field_name) == (card, "annual_fee")
        assert item.proposed_value == 2000.0
        assert item.status == ReviewStatus.PENDING

    def test_repeat_crawl_does_not_duplicate_pending_proposals(self, service, bank):
        CreditCardFactory(bank=bank, name="Gold", annual_fee=1000)
        for _ in range(2):
            crawl(service, bank, name="Gold", annual_fee=2000)
        assert ReviewQueue.objects.count() == 1

    def test_unchanged_or_empty_values_propose_nothing(self, service, bank):
        CreditCardFactory(
            bank=bank, name="Gold", annual_fee=1000, reward_points_policy="x"
        )
        crawl(
            service,
            bank,
            name="Gold",
            annual_fee=1000,
            reward_points_policy="",
            interest_rate_apr=None,
        )
        assert not ReviewQueue.objects.exists()

    def test_inactive_card_is_not_reactivated(self, service, bank):
        card = CreditCardFactory(bank=bank, name="Gone", is_active=False, annual_fee=1)
        crawl(service, bank, name="Gone", annual_fee=1)
        card.refresh_from_db()
        assert card.is_active is False
        assert card.verification_status == "verified"


@pytest.mark.django_db()
class TestNameVariantsDoNotDuplicate:
    def test_variant_of_a_verified_name_proposes_instead_of_duplicating(self, service):
        bank = BankFactory(name="City Bank PLC")
        card = CreditCardFactory(
            bank=bank,
            name="City Bank American Express Blue Credit Card",
            annual_fee=2500,
            verification_status="verified",
        )
        crawl(service, bank, name="Blue American Express Credit Card", annual_fee=1250)
        assert CreditCard.objects.filter(bank=bank).count() == 1
        card.refresh_from_db()
        assert card.annual_fee == 2500
        assert ReviewQueue.objects.get(credit_card=card).field_name == "annual_fee"

    def test_variant_of_a_draft_name_updates_it(self, service):
        bank = BankFactory(name="Prime Bank PLC")
        CreditCardFactory(
            bank=bank, name="Visa Platinum Credit Card", verification_status="draft"
        )
        crawl(service, bank, name="PRIME BANK VISA PLATINUM", annual_fee=4000)
        assert CreditCard.objects.filter(bank=bank).count() == 1
        assert CreditCard.objects.get(bank=bank).annual_fee == 4000

    def test_ambiguous_variant_creates_a_separate_draft(self, service):
        bank = BankFactory(name="UCB PLC")
        for name in ("Visa Gold Card", "Gold Visa Credit Card"):
            CreditCardFactory(bank=bank, name=name, verification_status="draft")
        crawl(service, bank, name="Gold Visa", annual_fee=1000)
        assert CreditCard.objects.filter(bank=bank).count() == 3


@pytest.mark.django_db()
class TestDraftCardUpdates:
    def test_draft_is_updated_but_known_values_are_never_nulled(self, service, bank):
        card = CreditCardFactory(
            bank=bank,
            name="Draft",
            verification_status="draft",
            annual_fee=1000,
            interest_rate_apr=20,
            cash_advance_fee="2.5%",
            is_active=False,
        )
        crawl(
            service,
            bank,
            name="Draft",
            annual_fee=None,
            interest_rate_apr=22,
            cash_advance_fee="",
        )
        card.refresh_from_db()
        assert card.annual_fee == 1000
        assert card.cash_advance_fee == "2.5%"
        assert card.interest_rate_apr == 22
        assert card.is_active is False
        assert card.verification_status == "draft"
        assert not ReviewQueue.objects.exists()

    def test_sanity_failure_moves_draft_to_needs_review(self, service, bank):
        card = CreditCardFactory(bank=bank, name="Draft", verification_status="draft")
        crawl(service, bank, name="Draft", interest_rate_apr=60)
        card.refresh_from_db()
        assert card.verification_status == "needs_review"


class TestParserKeepsNewFieldsAndSanityFlags:
    def test_extra_fields_survive_and_out_of_range_is_flagged(self):
        from types import SimpleNamespace

        parser = LLMContentParser.__new__(LLMContentParser)
        from banks.validators import CreditCardDataValidator

        parser.validator = CreditCardDataValidator()
        result = SimpleNamespace(
            credit_cards=[
                {
                    "name": "A",
                    "annual_fee": -50,
                    "interest_rate_apr": 20,
                    "card_network": "visa",
                    "is_islamic": None,
                }
            ],
            issues=[],
            provider_used="test",
        )
        validated = parser._apply_validation_stage(result).credit_cards[0]
        assert validated["card_network"] == "visa"
        assert validated["annual_fee"] is None
        assert validated["sanity_flags"] == ["annual_fee out of range"]

    @pytest.mark.django_db()
    def test_flag_forces_needs_review_end_to_end(self):
        bank = BankFactory()
        CreditCardDataService().update_credit_card_data(
            bank.id, [{"name": "A", "annual_fee": None, "sanity_flags": ["x"]}]
        )
        assert CreditCard.objects.get(name="A").verification_status == "needs_review"


@pytest.mark.django_db()
class TestApprovalAppliesProposal:
    def _proposal(self, service, bank, **card):
        CreditCardFactory(bank=bank, name="Gold", annual_fee=1000)
        crawl(service, bank, name="Gold", **card)
        return ReviewQueue.objects.get()

    def test_approve_applies_value_and_records_history(
        self, service, bank, django_user_model
    ):
        item = self._proposal(service, bank, annual_fee=2000)
        reviewer = django_user_model.objects.create_user("rev", password="pw")

        ReviewQueueService().approve(item, reviewer=reviewer)

        card = item.credit_card
        card.refresh_from_db()
        assert card.annual_fee == 2000
        assert card.verification_status == "verified"
        history = CreditCardFieldHistory.objects.get(card=card, field_name="annual_fee")
        assert (history.old_value, history.new_value) == ("1000.00", "2000.00")
        item.refresh_from_db()
        assert (item.status, item.reviewed_by) == (ReviewStatus.APPROVED, reviewer)

    def test_reject_leaves_card_untouched(self, service, bank):
        item = self._proposal(service, bank, annual_fee=2000)
        ReviewQueueService().reject(item)
        item.credit_card.refresh_from_db()
        assert item.credit_card.annual_fee == 1000

    def test_approving_a_user_report_applies_the_suggested_value(self):
        card = CreditCardFactory(card_network="")
        item = ReviewQueue.objects.create(
            bank=card.bank,
            credit_card=card,
            source=ReviewSource.USER_REPORT,
            field_name="card_network",
            proposed_value="mastercard",
            message="wrong network",
        )
        ReviewQueueService().approve(item)
        card.refresh_from_db()
        assert card.card_network == "mastercard"

    def test_invalid_suggestion_raises_and_changes_nothing(self):
        card = CreditCardFactory(annual_fee=1000)
        item = ReviewQueue.objects.create(
            bank=card.bank,
            credit_card=card,
            source=ReviewSource.USER_REPORT,
            field_name="annual_fee",
            proposed_value="about a thousand",
            message="wrong",
        )
        with pytest.raises(ValidationError):
            ReviewQueueService().approve(item)
        card.refresh_from_db()
        item.refresh_from_db()
        assert card.annual_fee == 1000
        assert item.status == ReviewStatus.PENDING

    def test_report_without_value_is_just_marked_approved(self):
        card = CreditCardFactory(annual_fee=1000)
        item = ReviewQueue.objects.create(
            bank=card.bank, credit_card=card, source=ReviewSource.USER_REPORT, message="?"
        )
        ReviewQueueService().approve(item)
        card.refresh_from_db()
        assert card.annual_fee == 1000
        assert item.status == ReviewStatus.APPROVED
