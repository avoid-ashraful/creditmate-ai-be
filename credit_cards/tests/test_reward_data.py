"""Tests for verified, structured reward data on credit cards."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from django.core.exceptions import ValidationError
from django.core.management import call_command

from banks.factories import BankFactory
from credit_cards.api.serializers import CreditCardListSerializer, CreditCardSerializer
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard, CreditCardFieldHistory

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "credit_cards" / "fixtures" / "verified_cards_2026-10-18.json"
MERGE_SCRIPT = ROOT / "scripts" / "merge_reward_data.py"

EARN_RULES = [
    {
        "category": "groceries",
        "points_per_unit": 10,
        "spend_unit_bdt": 100,
        "text": "Earn 10 points per BDT 100 at partner groceries.",
    }
]
CASHBACK_RULES = [
    {
        "category": "dining",
        "percent": 5,
        "cap_text": "up to BDT 300 monthly",
        "text": "5% cashback on dining up to BDT 300 monthly.",
    }
]


def load_merge_script():
    """Import the standalone merge script as a module."""
    spec = importlib.util.spec_from_file_location("merge_reward_data", MERGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reward_fields():
    """Return a complete, valid reward payload for a card."""
    return {
        "reward_program_name": "MyRewards",
        "reward_earn_rules": EARN_RULES,
        "cashback_rules": CASHBACK_RULES,
        "reward_point_value_bdt": Decimal("0.3333"),
        "points_expiry_text": "Points expire after 36 months.",
        "reward_source_url": "https://bank.example.test/rewards",
    }


@pytest.mark.django_db()
class TestRewardModelFields:
    def test_defaults_are_empty_and_point_value_is_null(self):
        card = CreditCardFactory()
        card.refresh_from_db()
        assert card.reward_program_name == ""
        assert card.reward_earn_rules == []
        assert card.cashback_rules == []
        assert card.reward_point_value_bdt is None
        assert card.points_expiry_text == ""
        assert card.reward_source_url == ""

    def test_valid_reward_payload_passes_full_clean(self):
        card = CreditCardFactory(bank=BankFactory(), **reward_fields())
        card.full_clean()
        assert card.reward_earn_rules == EARN_RULES
        assert card.cashback_rules == CASHBACK_RULES

    @pytest.mark.parametrize(
        "rules",
        [
            [{"category": "unknown", "points_per_unit": 1, "spend_unit_bdt": 50}],
            [{"category": "all", "points_per_unit": 0, "spend_unit_bdt": 50}],
            [{"category": "all", "points_per_unit": -1, "spend_unit_bdt": 50}],
            [{"category": "all", "points_per_unit": 1, "spend_unit_bdt": 0}],
            [{"category": "all", "points_per_unit": "two", "spend_unit_bdt": 50}],
            ["not-a-dict"],
            {"category": "all", "points_per_unit": 1, "spend_unit_bdt": 50},
        ],
    )
    def test_invalid_earn_rules_are_rejected(self, rules):
        card = CreditCardFactory(bank=BankFactory(), reward_earn_rules=rules)
        with pytest.raises(ValidationError):
            card.full_clean()

    @pytest.mark.parametrize(
        "rules",
        [
            [{"category": "unknown", "percent": 5}],
            [{"category": "dining", "percent": 0}],
            [{"category": "dining", "percent": -2}],
            [{"category": "dining", "percent": "five"}],
            [{"category": "dining"}],
            [{"category": "dining", "percent": 5}, "bad"],
        ],
    )
    def test_invalid_cashback_rules_are_rejected(self, rules):
        card = CreditCardFactory(bank=BankFactory(), cashback_rules=rules)
        with pytest.raises(ValidationError):
            card.full_clean()

    def test_negative_point_value_is_rejected(self):
        card = CreditCardFactory(
            bank=BankFactory(), reward_point_value_bdt=Decimal("-0.1")
        )
        with pytest.raises(ValidationError):
            card.full_clean()


@pytest.mark.django_db()
class TestRewardFieldHistory:
    def test_reward_fields_are_tracked(self):
        card = CreditCardFactory(bank=BankFactory())
        card.reward_program_name = "MyRewards"
        card.reward_earn_rules = EARN_RULES
        card.cashback_rules = CASHBACK_RULES
        card.reward_point_value_bdt = Decimal("0.3333")
        card.points_expiry_text = "36 months"
        card.reward_source_url = "https://bank.example.test/rewards"
        card.save()

        history = {
            entry.field_name: entry
            for entry in CreditCardFieldHistory.objects.filter(card=card)
        }
        assert set(history) == {
            "reward_program_name",
            "reward_earn_rules",
            "cashback_rules",
            "reward_point_value_bdt",
            "points_expiry_text",
            "reward_source_url",
        }
        assert history["reward_earn_rules"].new_value == EARN_RULES
        assert history["reward_point_value_bdt"].new_value == "0.3333"


@pytest.mark.django_db()
class TestRewardSerializers:
    def test_list_serializer_includes_reward_data(self):
        card = CreditCardFactory(bank=BankFactory(), **reward_fields())
        data = CreditCardListSerializer(card).data
        assert data["reward_program_name"] == "MyRewards"
        assert data["reward_earn_rules"] == EARN_RULES
        assert data["cashback_rules"] == CASHBACK_RULES
        assert data["reward_point_value_bdt"] == "0.3333"
        assert data["points_expiry_text"] == "Points expire after 36 months."
        assert data["reward_source_url"] == "https://bank.example.test/rewards"

    def test_detail_serializer_includes_reward_data(self):
        card = CreditCardFactory(bank=BankFactory(), **reward_fields())
        data = CreditCardSerializer(card).data
        assert data["reward_program_name"] == "MyRewards"
        assert data["reward_earn_rules"] == EARN_RULES
        assert data["cashback_rules"] == CASHBACK_RULES
        assert data["reward_point_value_bdt"] == "0.3333"


@pytest.mark.django_db()
class TestRewardImportExport:
    def test_import_and_export_round_trip_the_reward_fields(self, tmp_path):
        source = tmp_path / "cards.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "bank": "Reward Bank",
                        "name": "Reward Card",
                        "reward_points_policy": "Verbatim policy",
                        "reward_program_name": "MyRewards",
                        "reward_earn_rules": EARN_RULES,
                        "cashback_rules": CASHBACK_RULES,
                        "reward_point_value_bdt": "0.3333",
                        "points_expiry_text": "36 months",
                        "reward_source_url": "https://bank.example.test/rewards",
                        "verification_status": "verified",
                    }
                ]
            ),
            encoding="utf-8",
        )
        call_command("import_cards", str(source))

        card = CreditCard.objects.get(name="Reward Card")
        assert card.reward_earn_rules == EARN_RULES
        assert card.cashback_rules == CASHBACK_RULES
        assert card.reward_point_value_bdt == Decimal("0.3333")

        destination = tmp_path / "exported.json"
        call_command("export_verified_cards", str(destination))
        exported = json.loads(destination.read_text(encoding="utf-8"))[0]
        assert exported["reward_program_name"] == "MyRewards"
        assert exported["reward_earn_rules"] == EARN_RULES
        assert exported["cashback_rules"] == CASHBACK_RULES
        assert exported["reward_point_value_bdt"] == "0.3333"
        assert exported["points_expiry_text"] == "36 months"
        assert exported["reward_source_url"] == "https://bank.example.test/rewards"


class TestRewardMergeScript:
    def test_merge_matches_by_card_name_fills_policy_and_is_idempotent(self, tmp_path):
        module = load_merge_script()
        rewards_dir = tmp_path / "rewards"
        rewards_dir.mkdir()
        (rewards_dir / "city.json").write_text(
            json.dumps(
                {
                    "bank_slug": "city",
                    "bank": "The City Bank PLC",
                    "cards": [
                        {
                            "card_name": "Reward Card",
                            "reward_program_name": "MyRewards",
                            "earn_rules": EARN_RULES,
                            "cashback_rules": CASHBACK_RULES,
                            "point_value_bdt": 0.5,
                            "points_expiry_text": "36 months",
                            "source_url": "https://bank.example.test/rewards",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        rows = [
            {
                "bank": "City Bank PLC",
                "name": "Reward Card",
                "reward_points_policy": "",
                "annual_fee": 1000,
            },
            {"bank": "City Bank PLC", "name": "Other Card", "annual_fee": 0},
        ]

        first = module.merge_rewards(rows, rewards_dir)
        assert first["matched"] == 1
        assert first["unmatched_cards"] == []
        assert rows[0]["annual_fee"] == 1000
        assert rows[0]["reward_point_value_bdt"] == "0.5"
        assert rows[0]["reward_points_policy"] == (
            f"{EARN_RULES[0]['text']} {CASHBACK_RULES[0]['text']}"
        )
        assert "reward_earn_rules" not in rows[1]

        before = json.dumps(rows, sort_keys=True)
        second = module.merge_rewards(rows, rewards_dir)
        assert second["matched"] == 1
        assert json.dumps(rows, sort_keys=True) == before

    def test_merge_keeps_existing_policy_and_reports_unmatched(self, tmp_path):
        module = load_merge_script()
        rewards_dir = tmp_path / "rewards"
        rewards_dir.mkdir()
        (rewards_dir / "bank.json").write_text(
            json.dumps(
                {
                    "bank": "Nowhere Bank",
                    "cards": [{"card_name": "Missing Card", "earn_rules": EARN_RULES}],
                }
            ),
            encoding="utf-8",
        )
        rows = [
            {
                "bank": "City Bank PLC",
                "name": "Reward Card",
                "reward_points_policy": "Keep me",
            }
        ]
        result = module.merge_rewards(rows, rewards_dir)
        assert result["matched"] == 0
        assert result["unmatched_files"] == ["bank.json (bank 'Nowhere Bank')"]
        assert rows[0]["reward_points_policy"] == "Keep me"


class TestVerifiedRewardFixture:
    def test_fixture_has_reward_data_for_every_published_card(self):
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
        reward_fields = {
            "reward_program_name",
            "reward_earn_rules",
            "cashback_rules",
            "reward_point_value_bdt",
            "points_expiry_text",
            "reward_source_url",
        }
        with_reward_record = [row for row in rows if reward_fields <= set(row)]
        assert len(with_reward_record) == 105
        assert all(row["verification_status"] == "verified" for row in with_reward_record)
        assert sum(1 for row in rows if row.get("reward_earn_rules")) == 66
        assert sum(1 for row in rows if row.get("cashback_rules")) == 15
        assert (
            sum(1 for row in rows if row.get("reward_point_value_bdt") is not None) == 7
        )
        assert sum(1 for row in rows if row.get("points_expiry_text")) == 11
