"""Tests for the Gemini provider on the ``google-genai`` SDK (client mocked)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.genai import errors as genai_errors
from PIL import Image

from common.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseError,
)
from common.llm.providers.gemini import GeminiProvider


@pytest.fixture()
def client(settings):
    """Provider with a mocked ``genai.Client``; yields (provider, client mock)."""
    settings.GEMINI_API_KEY = "test-key"
    settings.GEMINI_MODEL = "gemini-flash-latest"
    with patch("common.llm.providers.gemini.genai.Client") as client_cls:
        yield GeminiProvider(), client_cls.return_value, client_cls


def api_error(cls, code, status="ERR", message="boom"):
    return cls(code, {"error": {"code": code, "status": status, "message": message}})


def test_configure_builds_client_with_api_key(client):
    provider, _, client_cls = client
    client_cls.assert_called_once_with(api_key="test-key")
    assert provider.is_available()


def test_unconfigured_without_api_key(settings):
    settings.GEMINI_API_KEY = ""
    provider = GeminiProvider()
    assert not provider.is_available()
    with pytest.raises(LLMConfigurationError):
        provider.generate_response("hi")


def test_generate_response_uses_models_generate_content(client):
    provider, mock_client, _ = client
    mock_client.models.generate_content.return_value = MagicMock(text='  {"a": 1}  ')

    result = provider.generate_response(
        "extract", system_prompt="be strict", temperature=0.1, max_tokens=50
    )

    assert result == '{"a": 1}'
    mock_client.models.generate_content.assert_called_once_with(
        model="gemini-flash-latest",
        contents="be strict\n\nextract",
        config={"temperature": 0.1, "max_output_tokens": 50},
    )


def test_extra_kwargs_reach_the_config_for_json_mode(client):
    provider, mock_client, _ = client
    mock_client.models.generate_content.return_value = MagicMock(text="{}")
    provider.generate_response("x", response_mime_type="application/json")
    config = mock_client.models.generate_content.call_args.kwargs["config"]
    assert config == {"response_mime_type": "application/json"}


def test_no_config_passes_none(client):
    provider, mock_client, _ = client
    mock_client.models.generate_content.return_value = MagicMock(text="ok")
    provider.generate_response("x")
    assert mock_client.models.generate_content.call_args.kwargs["config"] is None


def test_images_are_inline_sdk_parts_not_generation_options(client, tmp_path):
    provider, mock_client, _ = client
    paths = [tmp_path / "one.png", tmp_path / "two.jpg"]
    for path in paths:
        Image.new("RGB", (5, 5)).save(path)
    mock_client.models.generate_content.return_value = MagicMock(text="[]")
    assert (
        provider.generate_from_images(
            "extract", paths, system_prompt="strict", temperature=0.1
        )
        == "[]"
    )
    kwargs = mock_client.models.generate_content.call_args.kwargs
    assert kwargs["contents"][0] == "strict\n\nextract"
    for part, path, mime in zip(
        kwargs["contents"][1:], paths, ["image/png", "image/jpeg"]
    ):
        assert part.inline_data.data == path.read_bytes()
        assert part.inline_data.mime_type == mime
    assert kwargs["config"] == {"temperature": 0.1}


@pytest.mark.parametrize("text", [None, ""])
def test_empty_response_is_an_error(client, text):
    provider, mock_client, _ = client
    mock_client.models.generate_content.return_value = MagicMock(text=text)
    with pytest.raises(LLMResponseError):
        provider.generate_response("x")


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            api_error(genai_errors.ClientError, 401, "UNAUTHENTICATED"),
            LLMAuthenticationError,
        ),
        (
            api_error(genai_errors.ClientError, 403, "PERMISSION_DENIED"),
            LLMAuthenticationError,
        ),
        (
            api_error(
                genai_errors.ClientError, 400, "INVALID_ARGUMENT", "API key not valid"
            ),
            LLMAuthenticationError,
        ),
        (
            api_error(genai_errors.ClientError, 429, "RESOURCE_EXHAUSTED"),
            LLMRateLimitError,
        ),
        (api_error(genai_errors.ServerError, 503, "UNAVAILABLE"), LLMNetworkError),
        (httpx.ConnectTimeout("timed out"), LLMNetworkError),
        (RuntimeError("response blocked by safety"), LLMResponseError),
        (api_error(genai_errors.ClientError, 400, "INVALID_ARGUMENT"), LLMResponseError),
    ],
)
def test_errors_are_mapped(client, error, expected):
    provider, mock_client, _ = client
    mock_client.models.generate_content.side_effect = error
    with pytest.raises(expected) as raised:
        provider.generate_response("x")
    assert raised.value.original_error is error
