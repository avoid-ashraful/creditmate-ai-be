"""Regression tests for unit/period/waiver safety (inbox quality review).

The fee is stored and displayed as BDT and the APR is an annual rate, so these
values must never be silently relabeled into a critical field:

* foreign currency amounts (``"USD 100"``, ``"$95"``),
* non-annual periods (``"100 per month"``, ``"2% per month"``),
* conditional waiver wording (``"Waived"``, ``"Exempted"``).

Each rejection keeps the value unknown (``NULL``), records an explicit reason,
and must not count as an extracted value in the confidence score. Genuine
numeric ``0`` and the unambiguous wording (``"Free"``, ``"Nil"``,
``"No annual fee"``) stay valid. No conversion rate or fee default is invented.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from banks.factories import BankDataSourceFactory, BankFactory
from banks.models import CrawledContent
from banks.services.bank_data_crawler import BankDataCrawlerService
from banks.services.llm_parser import LLMContentParser
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from banks.services.quality_scoring import (
    REASON_CONDITIONAL_WAIVER,
    REASON_FOREIGN_CURRENCY,
    REASON_NON_ANNUAL_PERIOD,
    score_extraction,
)
from banks.services.quality_validator import ExtractionQualityValidator
from credit_cards.models import CreditCard

DOCUMENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | "
) * 30

VALID_CARD = {"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}


class FakeProvider:
    """Offline LLM stand-in returning canned JSON."""

    def __init__(self, responses, available=True):
        self.responses = list(responses)
        self.available = available
        self.prompts = []

    def is_available(self):
        return self.available

    def generate_response(self, prompt, **kwargs):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.responses) - 1)
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return {"response": response, "provider": "fake-provider"}


def build_crawler(responses):
    extractor = MultiPassLLMExtractor(provider=FakeProvider(responses))
    parser = LLMContentParser(multi_pass_extractor=extractor)
    crawler = BankDataCrawlerService(
        multi_pass_extractor=extractor, llm_parser=parser
    )
    crawler.content_extractor.extract_content = MagicMock(
        return_value=("raw content", DOCUMENT)
    )
    return crawler


class TestScoringRejectsUnsafeUnits:
    """Confidence must not count foreign/monthly/waiver values as extracted."""

    @pytest.mark.parametrize(
        "annual_fee",
        ["USD 100", "$95.00", "Rs. 100", "100 per month", "Waived", "Exempted"],
    )
    def test_unsafe_fee_scores_lower_than_a_valid_fee(self, annual_fee):
        valid = score_extraction(
            DOCUMENT, [dict(VALID_CARD, annual_fee=5000)], "pdf_text"
        )
        unsafe = score_extraction(
            DOCUMENT, [dict(VALID_CARD, annual_fee=annual_fee)], "pdf_text"
        )

        assert unsafe.confidence < valid.confidence
        assert unsafe.missing_critical_fields == ["annual_fee"]
        assert "invalid_annual_fee" in unsafe.issues
        assert "missing_annual_fee" not in unsafe.issues

    @pytest.mark.parametrize(
        "annual_fee,reason",
        [
            ("USD 100", REASON_FOREIGN_CURRENCY),
            ("$95.00", REASON_FOREIGN_CURRENCY),
            ("100 per month", REASON_NON_ANNUAL_PERIOD),
            ("Waived", REASON_CONDITIONAL_WAIVER),
            ("Exempted", REASON_CONDITIONAL_WAIVER),
        ],
    )
    def test_rejection_reason_is_recorded(self, annual_fee, reason):
        quality = score_extraction(
            DOCUMENT, [dict(VALID_CARD, annual_fee=annual_fee)], "pdf_text"
        )
        assert quality.invalid_reasons == {"annual_fee": reason}
        assert quality.details["invalid_reasons"] == {"annual_fee": reason}

    @pytest.mark.parametrize("apr", ["2% per month", "monthly 2.5%"])
    def test_monthly_rate_is_not_an_annual_apr(self, apr):
        quality = score_extraction(
            DOCUMENT, [dict(VALID_CARD, interest_rate_apr=apr)], "pdf_text"
        )
        assert quality.missing_critical_fields == ["interest_rate_apr"]
        assert quality.invalid_reasons == {
            "interest_rate_apr": REASON_NON_ANNUAL_PERIOD
        }

    def test_genuine_zero_and_free_wording_stay_valid(self):
        for fee in (0, 0.0, "Free", "Nil", "No annual fee"):
            quality = score_extraction(
                DOCUMENT, [dict(VALID_CARD, annual_fee=fee)], "pdf_text"
            )
            assert quality.missing_critical_fields == []
            assert quality.invalid_reasons == {}
            assert quality.confidence > 0.8, fee


class TestMultiPassRecordsUnsafeUnits:
    """The multi-pass pipeline NULLs unsafe values and keeps the reason."""

    def test_foreign_currency_fee_is_null_with_reason(self):
        responses = [
            json.dumps(
                [
                    {
                        "name": "Gold",
                        "annual_fee": "USD 100",
                        "interest_rate_apr": "20% p.a.",
                    }
                ]
            )
        ]
        extractor = MultiPassLLMExtractor(
            provider=FakeProvider(responses), confidence_threshold=0.0
        )
        result = extractor.extract(DOCUMENT, "Sonali Bank PLC", method="pdf_text")

        assert result.credit_cards[0]["annual_fee"] is None
        assert result.credit_cards[0]["interest_rate_apr"] == 20.0
        assert "invalid_annual_fee" in result.issues
        assert result.invalid_reasons == {"annual_fee": REASON_FOREIGN_CURRENCY}
        validation_pass = result.passes[-1]
        assert validation_pass["invalid_reasons"] == {
            "annual_fee": REASON_FOREIGN_CURRENCY
        }

    def test_monthly_fee_and_monthly_rate_are_null(self):
        responses = [
            json.dumps(
                [
                    {
                        "name": "Gold",
                        "annual_fee": "TK 500 per month",
                        "interest_rate_apr": "2% per month",
                    }
                ]
            )
        ]
        extractor = MultiPassLLMExtractor(
            provider=FakeProvider(responses), confidence_threshold=0.0
        )
        result = extractor.extract(DOCUMENT, "BRAC Bank PLC", method="pdf_text")

        card = result.credit_cards[0]
        assert card["annual_fee"] is None
        assert card["interest_rate_apr"] is None
        assert result.invalid_reasons == {
            "annual_fee": REASON_NON_ANNUAL_PERIOD,
            "interest_rate_apr": REASON_NON_ANNUAL_PERIOD,
        }

    def test_conditional_waiver_is_null_not_zero(self):
        responses = [
            json.dumps(
                [
                    {
                        "name": "Gold",
                        "annual_fee": "Waived if annual spend exceeds BDT 500,000",
                        "interest_rate_apr": 20.0,
                    }
                ]
            )
        ]
        extractor = MultiPassLLMExtractor(
            provider=FakeProvider(responses), confidence_threshold=0.0
        )
        result = extractor.extract(DOCUMENT, "City Bank PLC", method="pdf_text")

        assert result.credit_cards[0]["annual_fee"] is None  # never 0
        assert result.invalid_reasons == {
            "annual_fee": REASON_CONDITIONAL_WAIVER
        }


@pytest.mark.django_db
class TestCrawlerStoresUnsafeUnitsAsNull:
    """End to end: unsafe values end up NULL with a reviewable reason."""

    @pytest.mark.parametrize(
        "annual_fee,reason",
        [
            ("USD 100", REASON_FOREIGN_CURRENCY),
            ("TK 500 per month", REASON_NON_ANNUAL_PERIOD),
            ("Waived", REASON_CONDITIONAL_WAIVER),
        ],
    )
    def test_unsafe_fee_is_stored_null_with_reason(self, annual_fee, reason):
        responses = [
            json.dumps(
                [{"name": "Gold", "annual_fee": annual_fee, "interest_rate_apr": 20.0}]
            )
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(content_type="pdf")

        assert crawler.crawl_bank_data_source(source.id) is True

        card = CreditCard.objects.get(bank=source.bank)
        assert card.annual_fee is None  # NULL, not 0

        content = CrawledContent.objects.get(data_source=source)
        assert content.missing_critical_fields == ["annual_fee"]
        assert content.needs_manual_review is True

        summary = ExtractionQualityValidator.quality_summary(content)
        assert summary["invalid_reasons"] == {"annual_fee": reason}

    def test_valid_zero_and_free_are_still_stored(self):
        responses = [
            json.dumps(
                [
                    {"name": "Free Card", "annual_fee": 0, "interest_rate_apr": 18.0},
                    {"name": "Worded Free", "annual_fee": "Free", "interest_rate_apr": 19.0},
                ]
            )
        ]
        crawler = build_crawler(responses)
        source = BankDataSourceFactory(
            bank=BankFactory(name="Sonali Bank PLC"), content_type="pdf"
        )

        assert crawler.crawl_bank_data_source(source.id) is True

        assert CreditCard.objects.get(bank=source.bank, name="Free Card").annual_fee == 0
        assert (
            CreditCard.objects.get(bank=source.bank, name="Worded Free").annual_fee == 0
        )

        content = CrawledContent.objects.get(data_source=source)
        assert content.missing_critical_fields == []
        assert ExtractionQualityValidator.quality_summary(content)["invalid_reasons"] == {}

    def test_legacy_path_also_nulls_unsafe_units(self):
        """The single-pass fallback shares the same normalization rules."""
        crawler = BankDataCrawlerService()
        source = BankDataSourceFactory(content_type="webpage")

        with (
            patch.object(
                crawler.content_extractor,
                "extract_content",
                return_value=("raw", DOCUMENT),
            ),
            patch.object(
                crawler.llm_parser,
                "parse_comprehensive_data",
                return_value=(
                    [{"name": "Legacy", "annual_fee": "$95.00", "interest_rate_apr": 20.0}],
                    [{"name": "Legacy", "annual_fee": "$95.00"}],
                ),
            ),
        ):
            assert crawler.crawl_bank_data_source(source.id) is True

        assert CreditCard.objects.get(bank=source.bank).annual_fee is None
