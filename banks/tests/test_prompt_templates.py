"""Tests for bank-specific extraction prompt templates (Phase 2.2).

At least five banks must ship a dedicated template, every template must keep
the shared output contract (JSON only, zero vs missing rules), and unknown
banks must fall back to the generic template instead of breaking extraction.
"""

import pytest

from banks.services.prompt_templates import (
    BANK_ALIASES,
    BANK_TEMPLATES,
    CONTENT_PLACEHOLDER,
    BankSpecificPrompts,
)

# Institutions that must have their own template (requirement: 5+ banks).
EXPECTED_INSTITUTIONS = (
    "Sonali",
    "Janata",
    "Agrani",
    "Rupali",
    "BRAC",
    "City",
    "Dutch-Bangla",
    "Islami",
)


@pytest.fixture
def prompts():
    return BankSpecificPrompts()


class TestTemplateCoverage:
    """The registry must cover at least five banks plus a generic fallback."""

    def test_at_least_five_banks_supported(self, prompts):
        supported = prompts.list_supported_banks()
        assert len(supported) >= 5, f"only {len(supported)} bank templates"

    @pytest.mark.parametrize("institution", EXPECTED_INSTITUTIONS)
    def test_each_expected_institution_has_a_template(self, prompts, institution):
        matching = [
            name for name in prompts.list_supported_banks() if institution in name
        ]
        assert matching, f"no template for {institution}"

    def test_expected_institutions_count_is_five_or_more(self):
        assert len(EXPECTED_INSTITUTIONS) >= 5

    def test_every_template_is_non_empty(self, prompts):
        for name in prompts.list_supported_banks():
            template = prompts.templates[name]
            assert template.strip(), f"empty template for {name}"

    def test_aliases_cover_plc_and_limited_naming(self, prompts):
        assert prompts.resolve_bank_key("Sonali Bank PLC") is not None
        assert prompts.resolve_bank_key("Sonali Bank Limited") is not None
        assert prompts.resolve_bank_key("Dutch-Bangla Bank PLC") is not None
        assert prompts.resolve_bank_key("BRAC Bank Limited") is not None

    def test_alias_registry_has_shortcuts(self):
        assert len(BANK_ALIASES) >= 10
        assert BANK_ALIASES["sonali"] == "Sonali Bank Limited"

    def test_unknown_bank_falls_back_to_generic_template(self, prompts):
        unknown = "Meghna Bank International"
        assert prompts.has_bank_specific_template(unknown) is False
        assert prompts.resolve_bank_key(unknown) is None
        assert prompts.get_template_for_bank(unknown) == prompts.get_template_for_bank(
            "Another Unknown Bank Ltd"
        )


class TestPromptConstruction:
    """Prompts combine the bank template, the shared contract and the content."""

    def test_prompt_contains_bank_context_and_content(self, prompts):
        prompt = prompts.get_prompt_for_bank("Sonali Bank PLC", "SAMPLE CONTENT TEXT")
        assert "SAMPLE CONTENT TEXT" in prompt
        assert "Sonali Bank PLC" in prompt

    @pytest.mark.parametrize(
        "bank_name",
        ["Sonali Bank PLC", "Janata Bank PLC", "BRAC Bank PLC", "City Bank PLC"],
    )
    def test_prompt_keeps_output_contract_for_every_bank(self, prompts, bank_name):
        prompt = prompts.get_prompt_for_bank(bank_name, "content")
        assert "ONLY valid JSON" in prompt
        assert "annual_fee" in prompt
        assert "interest_rate_apr" in prompt
        assert "zero" in prompt.lower() or "0" in prompt

    def test_prompt_explains_zero_versus_missing(self, prompts):
        prompt = prompts.get_prompt_for_bank("Agrani Bank PLC", "content")
        assert "never default to 0" in prompt or "never guess" in prompt.lower()

    def test_content_placeholder_is_not_left_in_prompt(self, prompts):
        prompt = prompts.get_prompt_for_bank("Rupali Bank PLC", "body text")
        assert CONTENT_PLACEHOLDER not in prompt

    def test_focused_prompt_only_asks_for_critical_fields(self, prompts):
        focused = prompts.get_focused_prompt("Islami Bank Bangladesh Limited", "text")
        assert "annual_fee" in focused
        assert "interest_rate_apr" in focused
        assert "lounge_access" not in focused  # focused pass ignores optional fields

    def test_different_banks_get_different_prompts(self, prompts):
        sonali = prompts.get_prompt_for_bank("Sonali Bank PLC", "same content")
        brac = prompts.get_prompt_for_bank("BRAC Bank PLC", "same content")
        assert sonali != brac

    def test_generic_fallback_prompt_still_contains_contract(self, prompts):
        prompt = prompts.get_prompt_for_bank("Unknown Bank Ltd", "content")
        assert "ONLY valid JSON" in prompt
        assert "annual_fee" in prompt

    def test_registry_helpers_are_available_on_the_class(self):
        prompts = BankSpecificPrompts()
        assert "Document content:" in prompts.get_prompt_for_bank("Sonali Bank PLC", "x")
        assert "ONLY" in prompts.get_focused_prompt("BRAC Bank PLC", "x")

    @pytest.mark.parametrize("bank_name", [None, "", "   "])
    def test_empty_bank_name_does_not_break_prompt(self, prompts, bank_name):
        prompt = prompts.get_prompt_for_bank(bank_name, "content")
        assert "Document content:" in prompt


class TestPromptBankHints:
    """Templates must tell the model where to look in each bank's document."""

    @pytest.mark.parametrize(
        "bank_name,hint",
        [
            ("Sonali Bank PLC", "TK"),
            ("Dutch-Bangla Bank PLC", "card"),
            ("BRAC Bank PLC", "fee"),
            ("City Bank PLC", "credit card"),
        ],
    )
    def test_template_mentions_relevant_document_context(self, prompts, bank_name, hint):
        template = prompts.get_template_for_bank(bank_name).lower()
        assert hint.lower() in template

    def test_template_registry_import_matches_class_registry(self, prompts):
        assert prompts.templates == BANK_TEMPLATES
        assert prompts.aliases == BANK_ALIASES
