"""Offline regressions for fee denomination, product identity and proposal noise."""

from unittest.mock import MagicMock

import pytest

from banks.factories import BankFactory
from banks.models import ReviewQueue
from banks.services.credit_card_data_service import CreditCardDataService
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from banks.validators import CreditCardDataValidator
from credit_cards.factories import CreditCardFactory
from credit_cards.models import CreditCard


@pytest.mark.django_db
class TestForeignAnnualFees:
    @pytest.mark.parametrize(
        "fee", ["USD 50", "$ 25", "US$100", "EUR 80", "GBP 20", "JPY 1000"]
    )
    @pytest.mark.parametrize("path", ["direct", "validator", "multi", "focused"])
    def test_foreign_fee_stays_null_and_wording_survives(self, fee, path):
        card = {"name": "Foreign Platinum", "annual_fee": fee}
        if path == "validator":
            card = CreditCardDataValidator.sanitize_credit_card_data(card)
        elif path in {"multi", "focused"}:
            import json

            extractor = MultiPassLLMExtractor(provider=MagicMock())
            parse = (
                extractor._parse_cards
                if path == "multi"
                else extractor._parse_focused_cards
            )
            card = parse(json.dumps([card]))[0]
        bank = BankFactory()
        assert CreditCardDataService().update_credit_card_data(bank.pk, [card]) == 1
        saved = CreditCard.objects.get(bank=bank)
        assert saved.annual_fee is None
        assert f"Annual fee details: {fee}" in saved.additional_features

    @pytest.mark.parametrize(
        "extra",
        [
            {"annual_fee_currency": "USD"},
            {"annual_fee_details": "USD 50"},
            {"additional_features": ["Annual fee details: USD 50"]},
        ],
    )
    def test_numeric_foreign_output_with_currency_evidence_is_not_bdt(self, extra):
        bank = BankFactory()
        CreditCardDataService().update_credit_card_data(
            bank.pk, [{"name": "FC", "annual_fee": 50, **extra}]
        )
        assert CreditCard.objects.get(bank=bank).annual_fee is None

    def test_foreign_fee_does_not_propose_bdt_change_for_verified_card(self):
        card = CreditCardFactory(name="FC", annual_fee=None)
        CreditCardDataService().update_credit_card_data(
            card.bank_id, [{"name": "FC", "annual_fee": "USD 50"}]
        )
        assert not ReviewQueue.objects.filter(field_name="annual_fee").exists()


@pytest.mark.django_db
class TestProductIdentity:
    @pytest.mark.parametrize("flags", [(False, True), (True, False)])
    def test_mtb_islamic_and_conventional_same_tier_are_separate_and_repeatable(
        self, flags
    ):
        bank = BankFactory(name="MTB PLC")
        service = CreditCardDataService()
        for _ in range(2):
            for islamic in flags:
                assert (
                    service.update_credit_card_data(
                        bank.pk,
                        [
                            {
                                "name": "Visa Platinum",
                                "annual_fee": 1000 if islamic else 3000,
                                "is_islamic": islamic,
                                "card_network": "visa",
                                "source_url": f"https://mtb.test/{islamic}.pdf",
                            }
                        ],
                    )
                    == 1
                )
        assert CreditCard.objects.filter(bank=bank).count() == 2
        assert CreditCard.objects.get(bank=bank, is_islamic=True).annual_fee == 1000
        assert CreditCard.objects.get(bank=bank, is_islamic=False).annual_fee == 3000
        assert set(CreditCard.objects.values_list("verification_status", flat=True)) == {
            "draft"
        }

    def test_verified_match_uses_name_network_and_islamic_flag(self):
        bank = BankFactory(name="MTB PLC")
        conventional = CreditCardFactory(
            bank=bank,
            name="MTB Visa Platinum",
            card_network="visa",
            is_islamic=False,
            annual_fee=3000,
        )
        islamic = CreditCardFactory(
            bank=bank,
            name="MTB Islamic Visa Platinum",
            card_network="visa",
            is_islamic=True,
            annual_fee=1000,
        )
        CreditCardDataService().update_credit_card_data(
            bank.pk,
            [
                {
                    "name": "Platinum Visa",
                    "is_islamic": True,
                    "card_network": "visa",
                    "annual_fee": 1500,
                }
            ],
        )
        assert CreditCard.objects.filter(bank=bank).count() == 2
        assert ReviewQueue.objects.get(field_name="annual_fee").credit_card == islamic
        conventional.refresh_from_db()
        assert conventional.annual_fee == 3000

    def test_verified_match_is_preferred_over_draft(self):
        bank = BankFactory()
        verified = CreditCardFactory(bank=bank, name="Visa Gold", card_network="visa")
        CreditCardFactory(
            bank=bank,
            name="Gold Visa Card",
            card_network="visa",
            verification_status="draft",
        )
        service = CreditCardDataService()
        assert (
            service._find_card(bank.pk, "Visa Gold", {"card_network": "visa"}) == verified
        )

    def test_ambiguous_verified_match_creates_draft_even_for_exact_name(self):
        bank = BankFactory()
        for name in ("Visa Gold", "Gold Visa Card"):
            CreditCardFactory(bank=bank, name=name, card_network="visa")
        assert (
            CreditCardDataService().update_credit_card_data(
                bank.pk, [{"name": "Visa Gold", "card_network": "visa"}]
            )
            == 1
        )
        assert (
            CreditCard.objects.filter(bank=bank, verification_status="draft").count() == 1
        )

    @pytest.mark.parametrize("context", ["source", "line"])
    def test_distinct_source_product_lines_do_not_overwrite_drafts(self, context):
        bank = BankFactory()
        service = CreditCardDataService()
        for _ in range(2):
            for index in range(2):
                extra = (
                    {"source_url": f"https://bank.test/{index}.pdf"}
                    if context == "source"
                    else {"product_line": f"Line {index}"}
                )
                assert (
                    service.update_credit_card_data(
                        bank.pk, [{"name": "Gold", "annual_fee": 1000 + index, **extra}]
                    )
                    == 1
                )
        assert CreditCard.objects.filter(bank=bank).count() == 2

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Visa/Mastercard Gold", {"Visa Gold", "Mastercard Gold"}),
            (
                "Classic mastercard/VISA Card",
                {"mastercard Classic Card", "VISA Classic Card"},
            ),
            (
                "Visa Platinum/Mastercard Titanium",
                {"Visa Platinum", "Mastercard Titanium"},
            ),
        ],
    )
    def test_merged_family_splits_into_network_drafts(self, name, expected):
        bank = BankFactory()
        assert (
            CreditCardDataService().update_credit_card_data(
                bank.pk, [{"name": name, "annual_fee": 1000}]
            )
            == 2
        )
        cards = CreditCard.objects.filter(bank=bank)
        assert set(cards.values_list("name", flat=True)) == expected
        assert set(cards.values_list("card_network", flat=True)) == {"visa", "mastercard"}
        assert all(card.annual_fee == 1000 for card in cards)

    def test_family_matches_verified_cards_per_network(self):
        bank = BankFactory()
        for network in ("visa", "mastercard"):
            CreditCardFactory(
                bank=bank, name=f"{network} Gold", card_network=network, annual_fee=1000
            )
        assert (
            CreditCardDataService().update_credit_card_data(
                bank.pk, [{"name": "Visa/Mastercard Gold", "annual_fee": 2000}]
            )
            == 2
        )
        assert CreditCard.objects.filter(bank=bank).count() == 2
        assert ReviewQueue.objects.filter(field_name="annual_fee").count() == 2


@pytest.mark.django_db
class TestMaterialProposals:
    @pytest.mark.parametrize(
        "field,current,proposed",
        [
            ("late_payment_fee", "Late Payment Charge: BDT 1000", "BDT 1000"),
            ("late_payment_fee", "Late Payment Charge: BDT 850", "BDT 850"),
            ("late_payment_fee", "Late Payment Charge: BDT 700", "BDT 700"),
            (
                "foreign_transaction_fee",
                "Markup: 3% (additional markup at settlement of any international transaction except USD; applies even if shown in BDT)",
                "3%",
            ),
            (
                "supplementary_card_fee",
                "Supplementary Card Annual Fee: 1st card Free; 2nd card BDT 6,000; 3rd card onwards BDT 6,000",
                "1st Card Free, 2nd Card BDT 6,000, 3rd Card Onwards BDT 6,000",
            ),
            (
                "cash_advance_fee",
                "Tk. 150 or 2.50% +VAT per transaction",
                "2.5 percent or BDT 150 (plus VAT)",
            ),
            ("cash_advance_fee", "USD 4 or 2.5%", "US$4 / 2.50%"),
            (
                "lounge_access_domestic",
                "Complimentary lounge entry",
                "Free domestic lounge access",
            ),
        ],
    )
    def test_identical_figures_do_not_create_proposals(self, field, current, proposed):
        card = CreditCardFactory(name="Gold", **{field: current})
        CreditCardDataService().update_credit_card_data(
            card.bank_id, [{"name": "Gold", field: proposed}]
        )
        assert not ReviewQueue.objects.exists()
        card.refresh_from_db()
        assert getattr(card, field) == current

    @pytest.mark.parametrize(
        "current,proposed",
        [
            ("BDT 850", "BDT 700"),
            ("3%", "4%"),
            ("USD 50", "BDT 50"),
            ("BDT 50", "50%"),
            ("BDT 1000", "BDT 1000 plus 15% VAT"),
        ],
    )
    def test_changed_figures_or_currency_create_proposal(self, current, proposed):
        card = CreditCardFactory(name="Gold", cash_advance_fee=current)
        CreditCardDataService().update_credit_card_data(
            card.bank_id, [{"name": "Gold", "cash_advance_fee": proposed}]
        )
        assert ReviewQueue.objects.get().proposed_value == proposed

    def test_numeric_representations_do_not_create_proposals(self):
        card = CreditCardFactory(name="Gold", annual_fee=1000)
        CreditCardDataService().update_credit_card_data(
            card.bank_id, [{"name": "Gold", "annual_fee": "1,000.00"}]
        )
        assert not ReviewQueue.objects.exists()


@pytest.mark.django_db
def test_nullable_features_do_not_drop_a_card():
    """Optional JSON nulls must not make fee preservation discard the product."""
    bank = BankFactory()
    assert (
        CreditCardDataService().update_credit_card_data(
            bank.pk,
            [
                {
                    "name": "Gold",
                    "annual_fee": "USD 50",
                    "additional_features": None,
                }
            ],
        )
        == 1
    )
    assert CreditCard.objects.get(bank=bank).additional_features == [
        "Annual fee details: USD 50"
    ]


@pytest.mark.django_db
def test_authoritative_source_context_separates_drafts_when_llm_repeats_a_product_url():
    """The crawl URL distinguishes sources even if the model supplies one product link."""
    bank = BankFactory()
    service = CreditCardDataService()
    for index in range(2):
        assert (
            service.update_credit_card_data(
                bank.pk,
                [
                    {
                        "name": "Gold",
                        "source_url": "https://bank.test/product",
                        "annual_fee": 1000 + index,
                    }
                ],
                source_url=f"https://bank.test/schedule-{index}.pdf",
            )
            == 1
        )
    assert set(
        CreditCard.objects.filter(bank=bank).values_list("source_url", flat=True)
    ) == {
        "https://bank.test/schedule-0.pdf",
        "https://bank.test/schedule-1.pdf",
    }
