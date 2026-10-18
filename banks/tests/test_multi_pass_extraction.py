"""Offline tests for multi-pass LLM extraction (Phase 2.1).

A fake provider returns canned JSON, so no LLM key, network access or paid
call is ever made. The tests cover pass triggering, merging, provenance, the
real validation stage (zero vs missing vs invalid) and provider failure paths.
"""

import json

import pytest

from banks.exceptions import AIParsingError
from banks.services.multi_pass_extractor import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    FOCUSED_PASS,
    STANDARD_PASS,
    VALIDATION_PASS,
    MultiPassExtractionResult,
    MultiPassLLMExtractor,
)

LONG_DOCUMENT = (
    "SCHEDULE OF CHARGES - Credit Card annual fee interest rate APR charges "
    "cash advance table | tk. 5,000 | 20% per annum | credit card fees | "
) * 25


class FakeProvider:
    """Test double implementing the ExtractionProvider interface."""

    def __init__(self, responses=None, available=True, raise_error=False):
        self.responses = list(responses or [])
        self.available = available
        self.raise_error = raise_error
        self.prompts = []

    def is_available(self):
        return self.available

    def generate_response(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.raise_error:
            raise RuntimeError("provider exploded")
        index = min(len(self.prompts) - 1, len(self.responses) - 1)
        response = self.responses[index] if self.responses else "[]"
        if isinstance(response, Exception):
            raise response
        return {"response": response, "provider": "fake-provider"}


def make_extractor(responses, provider_kwargs=None, **extractor_kwargs):
    provider = FakeProvider(responses, **(provider_kwargs or {}))
    return MultiPassLLMExtractor(provider=provider, **extractor_kwargs), provider


class TestPassOrchestration:
    """Pass 1 always runs; pass 2 runs only when pass 1 scores below threshold."""

    def test_default_threshold_is_documented(self):
        assert 0.0 <= DEFAULT_CONFIDENCE_THRESHOLD <= 1.0

    def test_high_confidence_skips_focused_pass(self):
        cards = [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC", method="pdf_text")

        pass_names = [record["pass"] for record in result.passes]
        assert pass_names == [STANDARD_PASS, VALIDATION_PASS]
        assert result.details["focused_pass_ran"] is False
        assert result.missing_critical_fields == []
        # content x completeness x coverage stays high and bounded
        assert 0.8 <= result.confidence <= 1.0

    def test_low_confidence_triggers_focused_pass(self):
        incomplete = [{"name": "Gold", "annual_fee": None, "interest_rate_apr": None}]
        focused = {
            "cards": [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
        }
        extractor, provider = make_extractor(
            [json.dumps(incomplete), json.dumps(focused)],
            confidence_threshold=1.1,
        )
        result = extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC", method="pdf_text")

        pass_names = [record["pass"] for record in result.passes]
        assert pass_names == [STANDARD_PASS, FOCUSED_PASS, VALIDATION_PASS]
        assert result.details["focused_pass_ran"] is True
        assert len(provider.prompts) == 2
        # Focused pass values were merged in
        assert result.credit_cards[0]["annual_fee"] == 5000.0
        assert result.credit_cards[0]["interest_rate_apr"] == 20.0

    def test_default_threshold_runs_focused_for_incomplete_first_pass(self):
        incomplete = [{"name": "Gold", "annual_fee": None, "interest_rate_apr": None}]
        focused = {
            "cards": [
                {"name": "Gold", "annual_fee": "TK 5,000", "interest_rate_apr": "20%"}
            ]
        }
        extractor, _ = make_extractor([json.dumps(incomplete), json.dumps(focused)])
        result = extractor.extract(LONG_DOCUMENT, "BRAC Bank PLC", method="pdf_text")

        assert result.details["focused_pass_ran"] is True
        assert result.credit_cards[0]["annual_fee"] == 5000.0
        assert result.credit_cards[0]["interest_rate_apr"] == 20.0
        assert "annual_fee" not in result.missing_critical_fields

    def test_passes_are_ordered_and_complete(self):
        cards = [{"name": "Gold", "annual_fee": 0, "interest_rate_apr": 20.0}]
        extractor, _ = make_extractor([json.dumps(cards)])
        result = extractor.extract(LONG_DOCUMENT, "City Bank PLC")

        names = [record["pass"] for record in result.passes]
        assert names == [STANDARD_PASS, VALIDATION_PASS]
        for record in result.passes:
            assert {"pass", "provider", "cards_found", "confidence"} <= set(record)
            assert 0.0 <= record["confidence"] <= 1.0

    def test_bank_specific_prompt_is_used(self):
        extractor, provider = make_extractor(["[]"], confidence_threshold=0.0)
        extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC")

        assert "Sonali" in provider.prompts[0]
        assert LONG_DOCUMENT[:200] in provider.prompts[0]

    def test_focused_prompt_differs_from_standard_prompt(self):
        incomplete = [{"name": "Gold", "annual_fee": None, "interest_rate_apr": None}]
        extractor, provider = make_extractor(
            [json.dumps(incomplete), json.dumps({"cards": []})],
            confidence_threshold=1.1,
        )
        extractor.extract(LONG_DOCUMENT, "Janata Bank PLC")
        assert len(provider.prompts) == 2
        assert provider.prompts[0] != provider.prompts[1]


class TestValidationStage:
    """The real validation stage runs before final scoring/storage."""

    def test_invalid_values_become_null_and_are_reported(self):
        cards = [
            {
                "name": "Gold",
                "annual_fee": "abc",
                "interest_rate_apr": True,
            }
        ]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Islami Bank Bangladesh PLC")

        assert result.credit_cards[0]["annual_fee"] is None
        assert result.credit_cards[0]["interest_rate_apr"] is None
        assert "annual_fee" in result.missing_critical_fields
        assert "interest_rate_apr" in result.missing_critical_fields
        assert "invalid_annual_fee" in result.issues
        assert "invalid_interest_rate_apr" in result.issues

    def test_genuine_zero_fee_is_valid_not_missing(self):
        cards = [{"name": "Free Card", "annual_fee": 0, "interest_rate_apr": 20.0}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Agrani Bank PLC")

        assert result.credit_cards[0]["annual_fee"] == 0.0
        assert "annual_fee" not in result.missing_critical_fields
        assert "invalid_annual_fee" not in result.issues
        assert "missing_annual_fee" not in result.issues
        assert 0.8 <= result.confidence <= 1.0

    def test_free_wording_is_normalized_to_zero(self):
        cards = [{"name": "Free Card", "annual_fee": "Free", "interest_rate_apr": 18.0}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Rupali Bank PLC")

        assert result.credit_cards[0]["annual_fee"] == 0.0
        assert "annual_fee" not in result.missing_critical_fields

    def test_missing_markers_stay_null(self):
        cards = [{"name": "Card", "annual_fee": "N/A", "interest_rate_apr": None}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC")

        assert result.credit_cards[0]["annual_fee"] is None
        assert sorted(result.missing_critical_fields) == [
            "annual_fee",
            "interest_rate_apr",
        ]
        assert "missing_annual_fee" in result.issues
        assert "invalid_annual_fee" not in result.issues

    def test_extra_document_columns_are_preserved(self):
        cards = [
            {
                "name": "Gold",
                "annual_fee": 5000,
                "interest_rate_apr": 20.0,
                "CIB Fee": "BDT 100",
            }
        ]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Dutch-Bangla Bank PLC")

        assert result.credit_cards[0]["CIB Fee"] == "BDT 100"

    def test_currency_strings_are_normalized_before_scoring(self):
        cards = [{"name": "Gold", "annual_fee": "TK 5,000", "interest_rate_apr": "20%"}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "City Bank PLC")

        assert result.credit_cards[0]["annual_fee"] == 5000.0
        assert result.credit_cards[0]["interest_rate_apr"] == 20.0


class TestProviderFailures:
    """Provider failures must be recorded, bounded and never silent."""

    def test_provider_unavailable_raises_configuration_error(self):
        extractor, _ = make_extractor(["[]"], provider_kwargs={"available": False})
        with pytest.raises(AIParsingError):
            extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC")
        assert extractor.is_provider_available() is False

    def test_provider_exception_is_recorded_as_issues(self):
        extractor, _ = make_extractor([], provider_kwargs={"raise_error": True})
        result = extractor.extract(LONG_DOCUMENT, "BRAC Bank PLC")

        assert result.credit_cards == []
        assert result.confidence == 0.0
        assert any(issue.startswith("standard_pass_error") for issue in result.issues)
        assert any(issue.startswith("focused_pass_error") for issue in result.issues)
        error_records = [
            record for record in result.passes if record.get("error") is not None
        ]
        assert len(error_records) >= 1

    def test_unparseable_response_yields_no_cards(self):
        extractor, _ = make_extractor(["this is not json"], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Janata Bank PLC")
        assert result.credit_cards == []
        assert result.confidence == 0.0

    def test_confidence_is_bounded_for_every_outcome(self):
        outcomes = [
            ["[]"],
            ["not json"],
            [json.dumps([{"name": "X"}])],
            [json.dumps([{"name": "X", "annual_fee": 0, "interest_rate_apr": 0}])],
        ]
        for responses in outcomes:
            extractor, _ = make_extractor(responses, confidence_threshold=0.0)
            result = extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC")
            assert 0.0 <= result.confidence <= 1.0, responses

    def test_empty_document_scores_zero(self):
        extractor, _ = make_extractor(
            [json.dumps([{"name": "X", "annual_fee": 5, "interest_rate_apr": 5}])],
            confidence_threshold=0.0,
        )
        result = extractor.extract("", "Sonali Bank PLC")
        assert result.confidence == 0.0


class TestResultShape:
    """MultiPassExtractionResult carries everything the crawler needs."""

    def test_result_defaults(self):
        result = MultiPassExtractionResult()
        assert result.credit_cards == []
        assert result.confidence == 0.0
        assert result.issues == []
        assert result.passes == []
        assert result.provider_used is None

    def test_unextracted_critical_fields_helper(self):
        extractor, _ = make_extractor(["[]"])
        missing = extractor.unextracted_critical_fields(
            [{"name": "A", "annual_fee": 0, "interest_rate_apr": None}, "junk"]
        )
        assert missing == ["interest_rate_apr"]

    @pytest.mark.parametrize("method", ["pdf_text", "ocr", "webpage", "unknown"])
    def test_method_is_used_for_scoring_without_breaking_bounds(self, method):
        cards = [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": 20.0}]
        extractor, _ = make_extractor([json.dumps(cards)], confidence_threshold=0.0)
        result = extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC", method=method)
        assert 0.0 <= result.confidence <= 1.0
        assert result.provider_used == "fake-provider"


class TestMergeCards:
    """Merging never loses data and never overwrites good values."""

    def test_focused_values_fill_missing_fields_only(self):
        base = [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": None}]
        focused = [{"name": "Gold", "annual_fee": 9999, "interest_rate_apr": 20.0}]
        merged = MultiPassLLMExtractor.merge_cards(base, focused)

        assert merged[0]["annual_fee"] == 5000  # kept
        assert merged[0]["interest_rate_apr"] == 20.0  # filled

    def test_invalid_base_value_is_replaced_by_focused_value(self):
        base = [{"name": "Gold", "annual_fee": "abc", "interest_rate_apr": None}]
        focused = [{"name": "Gold", "annual_fee": 5000, "interest_rate_apr": None}]
        merged = MultiPassLLMExtractor.merge_cards(base, focused)
        assert merged[0]["annual_fee"] == 5000

    def test_base_card_without_name_is_matched_positionally(self):
        base = [{"name": "", "annual_fee": 1000, "interest_rate_apr": None}]
        focused = [{"name": "Platinum", "annual_fee": 2000, "interest_rate_apr": 20.0}]
        merged = MultiPassLLMExtractor.merge_cards(base, focused)
        assert merged[0]["name"] == "Platinum"
        assert merged[0]["annual_fee"] == 1000
        assert merged[0]["interest_rate_apr"] == 20.0

    def test_extra_base_cards_are_kept(self):
        base = [
            {"name": "A", "annual_fee": 1, "interest_rate_apr": 1},
            {"name": "B", "annual_fee": 2, "interest_rate_apr": 2},
        ]
        merged = MultiPassLLMExtractor.merge_cards(base, [])
        assert len(merged) == 2


class TestTruncatedModelOutput:
    """A response cut off at the token limit keeps its complete cards."""

    def test_complete_cards_of_a_truncated_array_are_kept(self):
        cards = [
            {"name": "Gold", "annual_fee": 5000},
            {"name": "Classic", "annual_fee": 0},
        ]
        truncated = json.dumps(cards)[:-12] + ', {"name": "Cut", "annual_fee": 3'
        payload = MultiPassLLMExtractor._load_json(truncated)
        assert [card["name"] for card in payload] == ["Gold"]

    def test_truncated_wrapped_object_is_salvaged(self):
        text = (
            '{"cards": [{"name": "Gold", "additional_features": ["a", "b"]}, {"name": "Cu'
        )
        payload = MultiPassLLMExtractor._load_json(text)
        assert payload == [{"name": "Gold", "additional_features": ["a", "b"]}]

    def test_text_without_any_complete_card_is_unparseable(self):
        assert MultiPassLLMExtractor._load_json('[{"name": "Cu') is None

    def test_standard_pass_gets_a_large_output_budget(self):
        recorded = {}

        class Recording(FakeProvider):
            def generate_response(self, prompt, **kwargs):
                recorded.update(kwargs)
                return super().generate_response(prompt, **kwargs)

        extractor = MultiPassLLMExtractor(
            provider=Recording(["[]"]), confidence_threshold=0.0
        )
        extractor.extract(LONG_DOCUMENT, "Sonali Bank PLC", method="pdf_text")
        assert recorded["max_tokens"] >= 16000


class TestLongDocuments:
    def test_content_past_twelve_thousand_chars_reaches_the_prompt(self):
        marker = "CARD TABLE ON LATE PAGE"
        content = "x" * 40000 + marker
        extractor, provider = make_extractor(["[]"], confidence_threshold=0.0)
        extractor.extract(content, "Sonali Bank PLC", method="pdf_text")
        assert marker in provider.prompts[0]
