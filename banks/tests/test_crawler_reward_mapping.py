"""Crawler mapping for the structured reward fields (conservative, never overwrites)."""

import pytest

from banks.enums import ReviewSource
from banks.factories import BankFactory
from banks.models import ReviewQueue
from banks.services import CreditCardDataService
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard

EARN_RULE = {
    "category": "groceries",
    "points_per_unit": 10,
    "spend_unit_bdt": 100,
    "text": "Earn 10 points per BDT 100 at groceries.",
}
CASHBACK_RULE = {
    "category": "dining",
    "percent": 5,
    "cap_text": "up to BDT 300 monthly",
    "text": "5% dining cashback.",
}


@pytest.fixture()
def bank():
    return BankFactory()


@pytest.fixture()
def service():
    return CreditCardDataService()


def crawl(service, bank, **card):
    return service.update_credit_card_data(bank.id, [card])


@pytest.mark.django_db()
class TestCrawlerRewardMapping:
    def test_new_draft_keeps_only_well_formed_reward_rules(self, service, bank):
        crawl(
            service,
            bank,
            name="Reward Draft",
            reward_program_name="MyRewards",
            reward_earn_rules=[
                EARN_RULE,
                {
                    "category": "not-a-category",
                    "points_per_unit": 1,
                    "spend_unit_bdt": 50,
                },
                {"category": "all", "points_per_unit": 0, "spend_unit_bdt": 50},
            ],
            cashback_rules=[
                CASHBACK_RULE,
                {"category": "dining", "percent": -1},
            ],
            reward_point_value_bdt="0.3333",
            points_expiry_text="36 months",
            reward_source_url="https://bank.example.test/rewards",
        )
        card = CreditCard.objects.get(name="Reward Draft")
        assert card.verification_status == "draft"
        assert card.reward_program_name == "MyRewards"
        assert card.reward_earn_rules == [EARN_RULE]
        assert card.cashback_rules == [CASHBACK_RULE]
        assert str(card.reward_point_value_bdt) == "0.3333"
        assert card.points_expiry_text == "36 months"
        assert card.reward_source_url == "https://bank.example.test/rewards"

    def test_malformed_reward_payload_does_not_drop_the_card(self, service, bank):
        crawl(
            service,
            bank,
            name="Noisy Rewards",
            reward_earn_rules="not-a-list",
            cashback_rules={"percent": 5},
            reward_point_value_bdt="free",
        )
        card = CreditCard.objects.get(name="Noisy Rewards")
        assert card.reward_earn_rules == []
        assert card.cashback_rules == []
        assert card.reward_point_value_bdt is None

    def test_verified_card_reward_change_becomes_a_proposal(self, service, bank):
        card = CreditCardFactory(
            bank=bank,
            name="Gold",
            reward_program_name="Old Program",
            reward_earn_rules=[],
        )
        crawl(
            service,
            bank,
            name="Gold",
            reward_program_name="New Program",
            reward_earn_rules=[EARN_RULE],
        )
        card.refresh_from_db()
        assert card.reward_program_name == "Old Program"
        assert card.reward_earn_rules == []
        proposals = {
            item.field_name: item for item in ReviewQueue.objects.filter(credit_card=card)
        }
        assert set(proposals) == {"reward_program_name", "reward_earn_rules"}
        assert all(
            item.source == ReviewSource.CRAWLER_PROPOSAL for item in proposals.values()
        )
        assert proposals["reward_earn_rules"].proposed_value == [EARN_RULE]

    def test_unchanged_reward_rules_propose_nothing(self, service, bank):
        CreditCardFactory(
            bank=bank,
            name="Gold",
            reward_program_name="MyRewards",
            reward_earn_rules=[EARN_RULE],
        )
        crawl(
            service,
            bank,
            name="Gold",
            reward_program_name="MyRewards",
            reward_earn_rules=[EARN_RULE],
        )
        assert not ReviewQueue.objects.exists()
