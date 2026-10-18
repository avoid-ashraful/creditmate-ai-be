"""
Claude Code CLI LLM provider implementation.

This module runs the locally installed Claude Code CLI in print mode
(``claude -p``) with the Haiku model, so the crawler can use a Claude
subscription login instead of a paid API key. It is meant for development and
low-volume crawling; the CLI must be logged in as the OS user running the
process (``claude`` login or ``claude setup-token``).
"""

import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

from common.llm.base import BaseLLMProvider
from common.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseError,
)

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You extract structured data from text. Follow the user's instructions exactly "
    "and reply with only the requested output."
)
_WORK_DIR = Path(tempfile.gettempdir()) / "creditmate-claude-code"
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)
_RATE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "limit reached",
    "quota",
    "overloaded",
    "too many requests",
    "429",
)
_AUTH_MARKERS = (
    "not logged in",
    "/login",
    "invalid api key",
    "authentication",
    "unauthorized",
    "oauth",
    "401",
)


class ClaudeCodeCLIProvider(BaseLLMProvider):
    """LLM provider backed by the Claude Code CLI in print mode.

    Each call spawns ``claude -p`` in an empty temp directory with tools, MCP
    servers, settings and the default system prompt stripped, so it costs a few
    hundred tokens of overhead. Calls are serialised across processes with
    file locks (``CLAUDE_CODE_MAX_CONCURRENCY`` slots).
    """

    def __init__(self):
        """Initialize Claude Code CLI provider."""
        super().__init__("claude_code")
        self.binary = None
        self.model = "haiku"
        self.timeout = 180
        self.max_concurrency = 1
        self.configure()

    def configure(self):
        """Read settings and locate the CLI binary.

        Returns
        -------
        bool
            True if the provider is enabled and the binary was found
        """
        self.model = getattr(settings, "CLAUDE_CODE_MODEL", "haiku")
        self.timeout = int(getattr(settings, "CLAUDE_CODE_TIMEOUT_SECONDS", 180))
        self.max_concurrency = max(
            1, int(getattr(settings, "CLAUDE_CODE_MAX_CONCURRENCY", 1))
        )
        self.binary = shutil.which(getattr(settings, "CLAUDE_CODE_BIN", "claude"))
        enabled = getattr(settings, "CLAUDE_CODE_ENABLED", True)
        self._is_configured = bool(enabled and self.binary)
        if not self._is_configured:
            logger.info("Claude Code CLI provider disabled or binary not found")
        return self._is_configured

    def is_available(self):
        """Check if the CLI provider can be used.

        Returns
        -------
        bool
            True if enabled and the binary exists
        """
        return self._is_configured and self.binary is not None

    def generate_response(self, prompt, system_prompt=None, **kwargs):
        """Generate response by running the Claude Code CLI.

        Parameters
        ----------
        prompt : str
            The main prompt; sent on stdin because PDFs produce long prompts
        system_prompt : str, optional
            Replaces the CLI's default system prompt
        **kwargs : dict
            Ignored (temperature, max_tokens, ... have no CLI equivalent)

        Returns
        -------
        str
            Generated text with any markdown code fence stripped

        Raises
        ------
        LLMConfigurationError
            If the provider is disabled or the binary is missing
        LLMAuthenticationError
            If the CLI is not logged in
        LLMRateLimitError
            If the subscription usage/rate limit is hit
        LLMNetworkError
            On timeout, OS errors or API errors before a model call
        LLMResponseError
            If the output is malformed or empty
        """
        if not self.is_available():
            raise LLMConfigurationError(
                "Claude Code CLI provider is disabled or the binary was not found",
                provider=self.provider_name,
            )

        command = [
            self.binary,
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--disable-slash-commands",
            "--exclude-dynamic-system-prompt-sections",
            "--system-prompt",
            system_prompt or DEFAULT_SYSTEM_PROMPT,
        ]
        started = time.monotonic()
        with self._concurrency_slot():
            completed = self._run(command, prompt)
        result = self._parse_output(completed)
        logger.debug(
            f"Claude Code CLI response generated in {time.monotonic() - started:.1f}s"
        )
        return result

    def _run(self, command, prompt):
        """Run the CLI, mapping process-level failures to LLM errors.

        Parameters
        ----------
        command : list of str
            Full argv
        prompt : str
            Text written to stdin

        Returns
        -------
        subprocess.CompletedProcess
            Finished process (any exit code)
        """
        _WORK_DIR.mkdir(parents=True, exist_ok=True)
        try:
            return subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=_WORK_DIR,
                env=self._build_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise LLMNetworkError(
                f"Claude Code CLI timed out after {self.timeout}s",
                provider=self.provider_name,
                original_error=e,
            )
        except OSError as e:
            raise LLMNetworkError(
                f"Claude Code CLI could not be started: {e}",
                provider=self.provider_name,
                original_error=e,
            )

    @staticmethod
    def _build_env():
        """Build the child environment.

        Returns
        -------
        dict
            Copy of the environment; ``ANTHROPIC_API_KEY`` is removed unless
            ``CLAUDE_CODE_USE_API_KEY`` is True so the subscription login is used
        """
        env = os.environ.copy()
        if not getattr(settings, "CLAUDE_CODE_USE_API_KEY", False):
            env.pop("ANTHROPIC_API_KEY", None)
        return env

    @contextmanager
    def _concurrency_slot(self):
        """Hold one of ``max_concurrency`` cross-process file-lock slots.

        Raises
        ------
        LLMNetworkError
            If no slot frees up within the timeout
        """
        _WORK_DIR.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            for slot in range(self.max_concurrency):
                handle = open(_WORK_DIR / f"slot{slot}.lock", "w")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    handle.close()
                    continue
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()
                return
            if time.monotonic() >= deadline:
                raise LLMNetworkError(
                    "Timed out waiting for a free Claude Code CLI slot",
                    provider=self.provider_name,
                )
            time.sleep(0.5)

    def _parse_output(self, completed):
        """Turn a finished CLI process into response text or an LLM error.

        Parameters
        ----------
        completed : subprocess.CompletedProcess
            Finished CLI process

        Returns
        -------
        str
            Response text with fences stripped

        Raises
        ------
        LLMAuthenticationError, LLMRateLimitError, LLMNetworkError, LLMResponseError
            Depending on the failure
        """
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise ValueError("not an object")
        except ValueError:
            if completed.returncode != 0:
                self._raise_for_failure(stderr or stdout, completed.returncode)
            raise LLMResponseError(
                "Claude Code CLI returned malformed output", provider=self.provider_name
            )

        result = payload.get("result")
        failed = (
            payload.get("is_error")
            or payload.get("subtype") != "success"
            or completed.returncode != 0
        )
        if failed:
            self._raise_for_failure(
                result if isinstance(result, str) and result else stderr or stdout,
                completed.returncode,
                payload.get("terminal_reason"),
            )
        if not isinstance(result, str) or not result.strip():
            raise LLMResponseError(
                "Empty response from Claude Code CLI", provider=self.provider_name
            )
        usage = payload.get("usage") or {}
        logger.info(
            "Claude Code CLI usage: input=%s cache_creation=%s cache_read=%s output=%s "
            "cost_usd=%s duration_ms=%s",
            usage.get("input_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("cache_read_input_tokens"),
            usage.get("output_tokens"),
            payload.get("total_cost_usd"),
            payload.get("duration_ms"),
        )
        return self._strip_fences(result)

    def _raise_for_failure(self, text, returncode, terminal_reason=None):
        """Map CLI failure text to the matching LLM exception.

        Parameters
        ----------
        text : str
            Error text from the CLI
        returncode : int
            Process exit code
        terminal_reason : str, optional
            ``terminal_reason`` field of the JSON result

        Raises
        ------
        LLMAuthenticationError, LLMRateLimitError, LLMNetworkError, LLMResponseError
            Depending on the text
        """
        lowered = (text or "").lower()
        message = f"Claude Code CLI failed (exit {returncode}): {(text or '')[:300]}"
        if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
            error_class = LLMRateLimitError
        elif any(marker in lowered for marker in _AUTH_MARKERS):
            error_class = LLMAuthenticationError
        elif terminal_reason == "api_error":
            error_class = LLMNetworkError
        else:
            error_class = LLMResponseError
        raise error_class(message, provider=self.provider_name)

    @staticmethod
    def _strip_fences(text):
        """Remove a surrounding markdown code fence, if any.

        Parameters
        ----------
        text : str
            Raw model text

        Returns
        -------
        str
            Text without the ```json fence
        """
        text = text.strip()
        match = _FENCE_RE.match(text)
        return match.group(1).strip() if match else text

    def validate_response(self, response):
        """Validate Claude Code CLI response.

        Parameters
        ----------
        response : str
            Response to validate

        Returns
        -------
        bool
            True if response is a non-empty string
        """
        return isinstance(response, str) and len(response.strip()) > 0
