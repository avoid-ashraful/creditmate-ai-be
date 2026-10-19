"""Offline coverage of capability filtering, retries and shared vision budgets."""

from unittest.mock import MagicMock

import pytest

from common.llm.budget import llm_call_budget
from common.llm.exceptions import (
    AllLLMProvidersFailedError,
    LLMAuthenticationError,
    LLMBudgetExhaustedError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
)
from common.llm.services import LLMOrchestrator


def provider(images=True):
    """Build a provider that cannot contact a real service."""
    fake = MagicMock()
    fake.supports_images = images
    fake.is_available.return_value = True
    fake.validate_response.return_value = True
    fake.generate_from_images.return_value = "[]"
    return fake


def orchestrator(**providers):
    """Build an orchestrator without configuring vendor clients."""
    instance = LLMOrchestrator.__new__(LLMOrchestrator)
    instance.providers = providers
    return instance


def test_vision_filters_capabilities_and_preserves_preference():
    text, first, preferred = provider(False), provider(), provider()
    result = orchestrator(
        text=text, first=first, preferred=preferred
    ).generate_from_images(
        "extract", ["page.png"], preferred_provider="preferred", system_prompt="strict"
    )
    assert result["provider"] == "preferred"
    preferred.generate_from_images.assert_called_once_with(
        prompt="extract", image_paths=["page.png"], system_prompt="strict"
    )
    first.generate_from_images.assert_not_called()
    text.generate_response.assert_not_called()
    text.generate_from_images.assert_not_called()


@pytest.mark.parametrize("failure", [LLMRateLimitError, LLMAuthenticationError])
def test_quota_and_auth_fall_through_without_retry(failure):
    first, second = provider(), provider()
    first.generate_from_images.side_effect = failure("unavailable")
    with llm_call_budget(2) as budget:
        result = orchestrator(first=first, second=second).generate_from_images(
            "extract", ["image.png"], max_retries=3
        )
        assert budget.used == 2
    assert result["provider"] == "second"
    assert first.generate_from_images.call_count == 1
    assert result["attempts"] == ["first_attempt_1", "second_attempt_1"]
    assert "first_attempt_1" in result["errors"]


def test_vision_retries_share_budget_with_text_and_do_not_call_past_limit():
    fake = provider()
    fake.generate_from_images.side_effect = LLMResponseError("bad JSON")
    service = orchestrator(fake=fake)
    with llm_call_budget(3) as budget:
        service.generate_response("text")
        with pytest.raises(LLMBudgetExhaustedError):
            service.generate_from_images("extract", ["image.png"], max_retries=3)
        assert budget.used == 3
        assert fake.generate_from_images.call_count == 2


def test_vision_unavailable_does_not_spend_budget():
    fake = provider(False)
    with llm_call_budget(2) as budget:
        with pytest.raises(LLMConfigurationError, match="image-capable"):
            orchestrator(text=fake).generate_from_images("extract", ["image.png"])
        assert budget.used == 0


def test_empty_image_list_is_rejected():
    with pytest.raises(LLMConfigurationError, match="At least one image"):
        orchestrator().generate_from_images("extract", [])


def test_all_vision_failures_are_aggregated():
    fake = provider()
    fake.generate_from_images.side_effect = LLMResponseError("bad output")
    with pytest.raises(AllLLMProvidersFailedError) as error:
        orchestrator(fake=fake).generate_from_images("extract", ["image.png"])
    assert list(error.value.failures) == ["fake_attempt_1", "fake_attempt_2"]
