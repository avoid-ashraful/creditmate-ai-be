"""Tests for the Claude Code CLI provider (``subprocess.run`` mocked)."""

import json
import subprocess
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from django.core.management import call_command

from common.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseError,
)
from common.llm.providers import claude_code
from common.llm.providers.claude_code import ClaudeCodeCLIProvider
from common.llm.services import LLMOrchestrator

RUN = "common.llm.providers.claude_code.subprocess.run"


@pytest.fixture()
def provider(settings, tmp_path, monkeypatch):
    settings.CLAUDE_CODE_ENABLED = True
    settings.CLAUDE_CODE_USE_API_KEY = False
    monkeypatch.setattr(claude_code, "_WORK_DIR", tmp_path)
    with patch(
        "common.llm.providers.claude_code.shutil.which", return_value="/bin/claude"
    ):
        yield ClaudeCodeCLIProvider()


def completed(payload=None, returncode=0, stdout=None, stderr=""):
    if stdout is None:
        stdout = json.dumps(payload)
    return subprocess.CompletedProcess(["claude"], returncode, stdout, stderr)


def success(text):
    return {"type": "result", "subtype": "success", "is_error": False, "result": text}


def test_availability_follows_setting_and_binary(settings):
    settings.CLAUDE_CODE_ENABLED = True
    with patch("common.llm.providers.claude_code.shutil.which", return_value="/x/claude"):
        assert ClaudeCodeCLIProvider().is_available()
        settings.CLAUDE_CODE_ENABLED = False
        assert not ClaudeCodeCLIProvider().is_available()
    settings.CLAUDE_CODE_ENABLED = True
    with patch("common.llm.providers.claude_code.shutil.which", return_value=None):
        provider = ClaudeCodeCLIProvider()
        assert not provider.is_available()
        with pytest.raises(LLMConfigurationError):
            provider.generate_response("hi")


def test_prompt_goes_on_stdin_with_slim_flags(provider, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    with patch(RUN, return_value=completed(success("OK"))) as run:
        assert provider.generate_response("long prompt", system_prompt="sys") == "OK"

    args, kwargs = run.call_args
    command = args[0]
    assert kwargs["input"] == "long prompt"
    assert "long prompt" not in command
    assert command[:2] == ["/bin/claude", "-p"]
    assert command[command.index("--model") + 1] == "haiku"
    assert command[command.index("--system-prompt") + 1] == "sys"
    for flag in ("--strict-mcp-config", "--no-session-persistence"):
        assert flag in command
    assert command[command.index("--tools") + 1] == ""
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]


def test_usage_is_logged(provider, caplog):
    payload = {**success("OK"), "usage": {"input_tokens": 2, "output_tokens": 4}}
    with caplog.at_level("INFO", logger="common.llm.providers.claude_code"):
        with patch(RUN, return_value=completed(payload)):
            provider.generate_response("x")
    assert "input=2" in caplog.text and "output=4" in caplog.text


def test_api_key_kept_when_enabled(provider, settings, monkeypatch):
    settings.CLAUDE_CODE_USE_API_KEY = True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    with patch(RUN, return_value=completed(success("OK"))) as run:
        provider.generate_response("x")
    assert run.call_args.kwargs["env"]["ANTHROPIC_API_KEY"] == "sk-secret"


@pytest.mark.parametrize(
    "text, expected",
    [
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ("```\n[1, 2]\n```", "[1, 2]"),
        ('  {"a": 1}  ', '{"a": 1}'),
    ],
)
def test_fences_stripped(provider, text, expected):
    with patch(RUN, return_value=completed(success(text))):
        assert provider.generate_response("x") == expected


@pytest.mark.parametrize(
    "text, error",
    [
        ("Claude AI usage limit reached|1760000000", LLMRateLimitError),
        ("API Error: 429 rate limit", LLMRateLimitError),
        ("Invalid API key · Please run /login", LLMAuthenticationError),
        ("Not logged in", LLMAuthenticationError),
        ("something odd", LLMResponseError),
    ],
)
def test_error_results_are_mapped(provider, text, error):
    payload = {"type": "result", "subtype": "error", "is_error": True, "result": text}
    with patch(RUN, return_value=completed(payload, returncode=1)):
        with pytest.raises(error):
            provider.generate_response("x")


def test_api_error_terminal_reason_is_network(provider):
    payload = {"is_error": True, "subtype": "error", "terminal_reason": "api_error"}
    with patch(RUN, return_value=completed(payload, returncode=1)):
        with pytest.raises(LLMNetworkError):
            provider.generate_response("x")


def test_non_json_failure_uses_stderr(provider):
    done = completed(stdout="", returncode=1, stderr="usage limit reached")
    with patch(RUN, return_value=done):
        with pytest.raises(LLMRateLimitError):
            provider.generate_response("x")


@pytest.mark.parametrize("stdout", ["not json", "[1]", ""])
def test_malformed_output_is_response_error(provider, stdout):
    with patch(RUN, return_value=completed(stdout=stdout)):
        with pytest.raises(LLMResponseError):
            provider.generate_response("x")


def test_empty_result_is_response_error(provider):
    with patch(RUN, return_value=completed(success("  "))):
        with pytest.raises(LLMResponseError):
            provider.generate_response("x")


@pytest.mark.parametrize(
    "exc", [subprocess.TimeoutExpired("claude", 1), FileNotFoundError("claude")]
)
def test_timeout_and_os_errors_are_network_errors(provider, exc):
    with patch(RUN, side_effect=exc):
        with pytest.raises(LLMNetworkError):
            provider.generate_response("x")


def test_concurrency_slot_blocks_second_holder(provider):
    provider.timeout = 0
    with provider._concurrency_slot():
        with pytest.raises(LLMNetworkError):
            with provider._concurrency_slot():
                pass
    with provider._concurrency_slot():  # released afterwards
        pass


def test_concurrency_allows_configured_slots(provider):
    provider.timeout = 0
    provider.max_concurrency = 2
    with provider._concurrency_slot(), provider._concurrency_slot():
        pass


def failing(error):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.generate_response.side_effect = error
    return fake


def serving(text="ok"):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.validate_response.return_value = True
    fake.generate_response.return_value = text
    return fake


def orchestrator_with(**fakes):
    instance = LLMOrchestrator(providers=[])
    instance.providers = fakes
    return instance


@pytest.mark.parametrize("error", [LLMRateLimitError("q"), LLMAuthenticationError("a")])
def test_orchestrator_falls_through_without_retrying(error):
    gemini, claude = failing(error), serving("from claude")
    result = orchestrator_with(gemini=gemini, claude_code=claude).generate_response(
        "p", max_retries=3
    )
    assert result["provider"] == "claude_code"
    assert gemini.generate_response.call_count == 1


def test_orchestrator_skips_unavailable_providers():
    gemini = serving()
    gemini.is_available.return_value = False
    result = orchestrator_with(gemini=gemini, claude_code=serving()).generate_response(
        "p"
    )
    assert result["provider"] == "claude_code"
    gemini.generate_response.assert_not_called()


def test_orchestrator_default_order_from_settings(settings):
    settings.LLM_PROVIDER_ORDER = ["claude_code", "gemini"]
    with patch("common.llm.providers.claude_code.shutil.which", return_value=None):
        assert LLMOrchestrator().provider_order == ["claude_code", "gemini"]
    assert LLMOrchestrator(providers=["gemini"]).provider_order == ["gemini"]


def test_orchestrator_preferred_provider_still_first():
    claude = serving("c")
    result = orchestrator_with(gemini=serving("g"), claude_code=claude).generate_response(
        "p", preferred_provider="claude_code"
    )
    assert result["provider"] == "claude_code"


def test_llm_status_lists_and_pings(settings):
    settings.LLM_PROVIDER_ORDER = ["claude_code"]
    settings.CLAUDE_CODE_ENABLED = True
    out = StringIO()
    with patch(
        "common.llm.providers.claude_code.shutil.which", return_value="/bin/claude"
    ):
        with patch(RUN, return_value=completed(success("OK"))):
            call_command("llm_status", "--ping", stdout=out)
    text = out.getvalue()
    assert "Provider order: claude_code" in text
    assert "claude_code: available" in text
    assert "ping: ok" in text
