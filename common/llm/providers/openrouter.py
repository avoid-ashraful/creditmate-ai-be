"""
OpenRouter LLM provider implementation.

This module provides access to various LLM models through the OpenRouter API,
which acts as a unified gateway to multiple language models.
"""

import logging

from openai import OpenAI

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


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter LLM provider implementation.

    Provides access to various LLM models through OpenRouter API with
    comprehensive error handling and configuration management.
    """

    def __init__(self):
        """Initialize OpenRouter provider."""
        super().__init__("openrouter")
        self.client = None
        self.base_url = "https://openrouter.ai/api/v1"
        self.default_model = "deepseek/deepseek-chat-v3-0324:free"
        self.configure()

    def configure(self):
        """Configure OpenRouter provider with API key and settings.

        Returns
        -------
        bool
            True if configuration successful, False otherwise
        """
        try:
            api_key = getattr(settings, "OPENROUTER_API_KEY", "")
            if not api_key:
                logger.warning("OpenRouter API key not configured")
                self._is_configured = False
                return False

            self.client = OpenAI(
                base_url=self.base_url,
                api_key=api_key,
            )
            self._is_configured = True
            logger.info("OpenRouter provider configured successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to configure OpenRouter provider: {e}")
            self._is_configured = False
            return False

    def is_available(self):
        """Check if OpenRouter provider is available.

        Returns
        -------
        bool
            True if provider is configured and client is ready
        """
        return self._is_configured and self.client is not None

    def generate_response(
        self,
        prompt,
        system_prompt=None,
        model=None,
        temperature=0.1,
        max_tokens=4000,
        **kwargs,
    ):
        """Generate response using OpenRouter API.

        Parameters
        ----------
        prompt : str
            The main prompt to send to the LLM
        system_prompt : str, optional
            System prompt to set context/behavior
        model : str, optional
            Specific model to use (defaults to self.default_model)
        temperature : float
            Sampling temperature (0.0 to 1.0)
        max_tokens : int
            Maximum tokens in response
        **kwargs : dict
            Additional OpenAI API parameters

        Returns
        -------
        str
            Generated response from the LLM

        Raises
        ------
        LLMConfigurationError
            If provider is not properly configured
        LLMAuthenticationError
            If API authentication fails
        LLMRateLimitError
            If rate limit is exceeded
        LLMNetworkError
            If network communication fails
        LLMResponseError
            If response is invalid or empty
        """
        if not self.is_available():
            raise LLMConfigurationError(
                "OpenRouter provider is not properly configured",
                provider=self.provider_name,
            )

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://creditmate.ai",
                    "X-Title": "Credit Mate AI",
                },
                model=model or self.default_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            if not response.choices:
                raise LLMResponseError(
                    "No response choices returned from OpenRouter",
                    provider=self.provider_name,
                )

            content = response.choices[0].message.content
            if not content:
                raise LLMResponseError(
                    "Empty response content from OpenRouter", provider=self.provider_name
                )

            logger.debug(
                f"OpenRouter response generated successfully (model: {model or self.default_model})"
            )
            return content.strip()

        except Exception as e:
            # Map OpenAI exceptions to our custom exceptions
            error_message = str(e).lower()

            if "authentication" in error_message or "unauthorized" in error_message:
                raise LLMAuthenticationError(
                    f"OpenRouter authentication failed: {e}",
                    provider=self.provider_name,
                    original_error=e,
                )
            elif "rate limit" in error_message or "quota" in error_message:
                raise LLMRateLimitError(
                    f"OpenRouter rate limit exceeded: {e}",
                    provider=self.provider_name,
                    original_error=e,
                )
            elif "timeout" in error_message or "connection" in error_message:
                raise LLMNetworkError(
                    f"OpenRouter network error: {e}",
                    provider=self.provider_name,
                    original_error=e,
                )
            else:
                raise LLMResponseError(
                    f"OpenRouter API error: {e}",
                    provider=self.provider_name,
                    original_error=e,
                )

    def validate_response(self, response):
        """Validate OpenRouter response.

        Parameters
        ----------
        response : str
            Response to validate

        Returns
        -------
        bool
            True if response is valid (non-empty string)
        """
        return isinstance(response, str) and len(response.strip()) > 0

    def get_available_models(self):
        """Get list of available models from OpenRouter.

        Note: This is a placeholder for future enhancement.
        OpenRouter provides many models - this could be extended to
        dynamically fetch and cache available models.

        Returns
        -------
        list
            List of available model identifiers
        """
        return [
            self.default_model,
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "google/gemma-2-9b-it:free",
        ]
