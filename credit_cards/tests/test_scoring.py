"""Tests for the CreditMate Score (credit_cards.scoring) and its API surface."""

from decimal import Decimal

import pytest

from banks.models import Bank
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard
from credit_cards.scoring import COMPONENT_MAX, evaluate_score, score_breakdown

LIST_URL = "/api/v1/credit-cards/"


def make_card(**overrides):
    """An unsaved card with neutral, fully-specified scored fields."""
    fields = {
        "name": "Test Card",
        "bank": Bank(name="Test Bank"),
        "annual_fee": Decimal("3000"),
        "annual_fee_waiver_policy": None,
        "interest_rate_apr": Decimal("25"),
        "lounge_access_international": "",
        "lounge_access_domestic": "",
        "reward_points_policy": "",
        "reward_earn_rules": [],
        "cashback_rules": [],
        "reward_point_value_bdt": None,
        "source_url": "https://bank.example.test/card",
        "verification_status": "verified",
    }
    fields.update(overrides)
    return CreditCard(**fields)


def component(card, key):
    return score_breakdown(card)[key]


class TestWeights:
    def test_component_maxima_sum_to_ten(self):
        assert sum(COMPONENT_MAX.values()) == Decimal("10")

    def test_breakdown_covers_all_components(self):
        breakdown = score_breakdown(make_card())
        assert list(breakdown) == list(COMPONENT_MAX)
        for item in breakdown.values():
            assert 0 <= item["points"] <= item["max"]
            assert item["reason"]


class TestAnnualCost:
    def test_low_fee_outscores_high_fee_on_cost(self):
        low = component(make_card(annual_fee=Decimal("500")), "annual_cost")
        high = component(make_card(annual_fee=Decimal("20000")), "annual_cost")
        assert low["points"] > high["points"]

    def test_low_fee_outscores_high_fee_overall(self):
        low = evaluate_score(make_card(annual_fee=Decimal("500")))["score"]
        high = evaluate_score(make_card(annual_fee=Decimal("20000")))["score"]
        assert low > high

    def test_zero_fee_gets_full_cost_points(self):
        cost = component(make_card(annual_fee=Decimal("0")), "annual_cost")
        assert cost["points"] == cost["max"] == 3.0

    def test_waiver_adds_points(self):
        without = component(make_card(), "annual_cost")
        with_waiver = component(
            make_card(annual_fee_waiver_policy={"conditions": "Spend to waive"}),
            "annual_cost",
        )
        assert with_waiver["points"] == without["points"] + 0.5

    def test_missing_fee_is_neutral_not_zero(self):
        missing = component(make_card(annual_fee=None), "annual_cost")
        free = component(make_card(annual_fee=Decimal("0")), "annual_cost")
        pricey = component(make_card(annual_fee=Decimal("27500")), "annual_cost")
        assert pricey["points"] < missing["points"] < free["points"]
        assert "not published" in missing["reason"]


class TestInterest:
    def test_lower_apr_scores_higher(self):
        low = component(make_card(interest_rate_apr=Decimal("18")), "interest")
        cap = component(make_card(interest_rate_apr=Decimal("25")), "interest")
        assert low["points"] == 2.0
        assert cap["points"] < low["points"]
        assert "cap" in cap["reason"]

    def test_missing_apr_is_neutral(self):
        missing = component(make_card(interest_rate_apr=None), "interest")
        assert missing["points"] == 1.0
        assert "not published" in missing["reason"]

    def test_islamic_card_without_apr_is_neutral_with_reason(self):
        card = make_card(interest_rate_apr=None, is_islamic=True)
        interest = component(card, "interest")
        assert interest["points"] == 1.0
        assert "Islamic" in interest["reason"]


class TestRewards:
    def test_earn_rules_earn_points(self):
        card = make_card(
            reward_earn_rules=[
                {"spend_unit_bdt": 50, "points_per_unit": 1, "category": "all"}
            ]
        )
        rewards = component(card, "rewards")
        # 2 points per BDT 100 -> 1.0 of the 1.5 earn sub-score.
        assert rewards["points"] == 1.0

    def test_cashback_adds_points(self):
        card = make_card(
            cashback_rules=[{"percent": 5, "category": "all", "text": "5% back"}]
        )
        assert component(card, "rewards")["points"] == 0.55

    def test_no_published_rewards_scores_zero(self):
        assert component(make_card(), "rewards")["points"] == 0

    def test_documented_policy_adds_points(self):
        card = make_card(reward_points_policy="1 point per BDT 50 spent.")
        assert component(card, "rewards")["points"] == 0.3


class TestPerks:
    def test_unlimited_both_directions_is_full_points(self):
        card = make_card(
            lounge_access_international="Unlimited",
            lounge_access_domestic="Unlimited",
        )
        assert component(card, "perks")["points"] == 1.5

    def test_stated_no_access_scores_zero(self):
        card = make_card(
            lounge_access_international="No lounge access",
            lounge_access_domestic="None",
        )
        assert component(card, "perks")["points"] == 0

    def test_unpublished_lounge_is_neutral_not_zero(self):
        perks = component(make_card(), "perks")
        assert perks["points"] == 0.4  # 0.2 neutral per direction


class TestDataConfidence:
    def test_verified_sourced_complete_card_beats_sparse_draft(self):
        complete = make_card(
            annual_fee_waiver_policy={"conditions": "Waiver"},
            reward_earn_rules=[
                {"spend_unit_bdt": 50, "points_per_unit": 1, "category": "all"}
            ],
            reward_point_value_bdt=Decimal("0.5"),
            lounge_access_domestic="Unlimited",
        )
        complete.verified_at = "2026-01-01T00:00:00Z"
        sparse = make_card(
            annual_fee=None,
            interest_rate_apr=None,
            source_url="",
            verification_status="draft",
        )
        assert (
            component(complete, "data_confidence")["points"]
            > component(sparse, "data_confidence")["points"]
        )


class TestDeterminismAndTotals:
    def test_same_card_scores_identically_twice(self):
        card = make_card()
        assert evaluate_score(card) == evaluate_score(card)

    def test_identical_cards_score_identically(self):
        assert evaluate_score(make_card()) == evaluate_score(make_card())

    def test_breakdown_sums_to_total_within_rounding(self):
        card = make_card(
            annual_fee=Decimal("1500"),
            interest_rate_apr=Decimal("24"),
            reward_earn_rules=[
                {"spend_unit_bdt": 80, "points_per_unit": 2, "category": "all"}
            ],
            lounge_access_international="4 visits per year",
        )
        result = evaluate_score(card)
        summed = sum(item["points"] for item in result["breakdown"].values())
        assert abs(summed - result["score"]) <= 0.05 + 1e-9
        assert 0 <= result["score"] <= 10


@pytest.mark.django_db
class TestScoreApiFields:
    def test_list_includes_score_and_breakdown(self, api_client):
        CreditCardFactory()
        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        card = response.data["results"][0]
        assert isinstance(card["creditmate_score"], float)
        breakdown = card["creditmate_score_breakdown"]
        assert list(breakdown) == list(COMPONENT_MAX)
        summed = sum(item["points"] for item in breakdown.values())
        assert abs(summed - card["creditmate_score"]) <= 0.05 + 1e-9

    def test_detail_includes_score_and_breakdown(self, api_client):
        card = CreditCardFactory()
        response = api_client.get(f"{LIST_URL}{card.id}/")
        assert response.status_code == 200
        assert "creditmate_score" in response.data
        assert "data_confidence" in response.data["creditmate_score_breakdown"]


@pytest.mark.django_db
class TestScoreOrdering:
    def _make_fee_ladder(self, count=25):
        """Cards identical except annual fee, so score falls as fee rises."""
        from banks.factories import BankFactory

        bank = BankFactory(name="Ladder Bank")
        cards = []
        for index in range(count):
            cards.append(
                CreditCardFactory(
                    bank=bank,
                    name=f"Ladder Card {index:02d}",
                    annual_fee=Decimal(index * 1000),
                    annual_fee_waiver_policy=None,
                    interest_rate_apr=Decimal("25"),
                    lounge_access_international="",
                    lounge_access_domestic="",
                    reward_points_policy="",
                    reward_earn_rules=[],
                    cashback_rules=[],
                    reward_point_value_bdt=None,
                )
            )
        return cards

    def test_descending_order_spans_page_boundary(self, api_client):
        self._make_fee_ladder()
        page1 = api_client.get(LIST_URL, {"ordering": "-creditmate_score"})
        page2 = api_client.get(LIST_URL, {"ordering": "-creditmate_score", "page": 2})
        assert page1.status_code == page2.status_code == 200
        scores = [c["creditmate_score"] for c in page1.data["results"]]
        scores += [c["creditmate_score"] for c in page2.data["results"]]
        assert len(scores) == 25
        assert scores == sorted(scores, reverse=True)
        # The free card must lead page 1 and the priciest must end page 2.
        assert page1.data["results"][0]["name"] == "Ladder Card 00"
        assert page2.data["results"][-1]["name"] == "Ladder Card 24"

    def test_ascending_order(self, api_client):
        self._make_fee_ladder(count=3)
        response = api_client.get(LIST_URL, {"ordering": "creditmate_score"})
        assert response.status_code == 200
        scores = [c["creditmate_score"] for c in response.data["results"]]
        assert scores == sorted(scores)
        assert response.data["results"][0]["name"] == "Ladder Card 02"


@pytest.mark.django_db
class TestAdvancedSearchScoreOrdering:
    URL = "/api/v1/credit-cards/advanced-search/"

    def test_score_ordering_and_sort_option(self, api_client):
        TestScoreOrdering()._make_fee_ladder(count=3)
        response = api_client.get(self.URL, {"ordering": "-creditmate_score"})
        assert response.status_code == 200
        scores = [c["creditmate_score"] for c in response.data["results"]]
        assert scores == sorted(scores, reverse=True)
        assert response.data["results"][0]["name"] == "Ladder Card 00"

        options = api_client.get(f"{self.URL}sort-options/")
        assert options.status_code == 200
        keys = [opt["key"] for opt in options.data["sort_options"]]
        assert "-creditmate_score" in keys
