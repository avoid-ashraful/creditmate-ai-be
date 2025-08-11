"""
Gemini LLM provider implementation.

This module provides direct access to Google's Gemini AI models through
the Google Generative AI API.
"""

import logging

import google.generativeai as genai

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


class GeminiProvider(BaseLLMProvider):
    """Gemini LLM provider implementation.

    Provides direct access to Google's Gemini models with comprehensive
    error handling and configuration management.
    """

    def __init__(self):
        """Initialize Gemini provider."""
        super().__init__("gemini")
        self.model = None
        self.default_model_name = "gemini-1.5-flash"
        self.configure()

    def configure(self):
        """Configure Gemini provider with API key and settings.

        Returns
        -------
        bool
            True if configuration successful, False otherwise
        """

        try:
            api_key = getattr(settings, "GEMINI_API_KEY", "")
            if not api_key:
                logger.warning("Gemini API key not configured")
                self._is_configured = False
                return False

            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(self.default_model_name)
            self._is_configured = True
            logger.info("Gemini provider configured successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to configure Gemini provider: {e}")
            self._is_configured = False
            return False

    def is_available(self):
        """Check if Gemini provider is available.

        Returns
        -------
        bool
            True if provider is configured and model is ready
        """
        return self._is_configured and self.model is not None

    def generate_response(
        self, prompt, system_prompt=None, temperature=None, max_tokens=None, **kwargs
    ):
        """Generate response using Gemini API.

        Parameters
        ----------
        prompt : str
            The main prompt to send to the LLM
        system_prompt : str, optional
            System prompt to set context/behavior (combined with main prompt)
        temperature : float, optional
            Sampling temperature (Note: Gemini handles this differently)
        max_tokens : int, optional
            Maximum tokens in response (Note: Gemini uses different limits)
        **kwargs : dict
            Additional Gemini API parameters

        Returns
        -------
        str
            Generated response from Gemini

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
        self._validate_availability()

        try:
            full_prompt = self._build_full_prompt(prompt, system_prompt)
            generation_config = self._build_generation_config(
                temperature, max_tokens, **kwargs
            )
            response = self._call_gemini_api(full_prompt, generation_config)

            return self._process_response(response)

        except Exception as e:
            self._handle_gemini_error(e)

    def _validate_availability(self):
        """Validate that the provider is available.

        Raises
        ------
        LLMConfigurationError
            If provider is not properly configured
        """
        if not self.is_available():
            raise LLMConfigurationError(
                "Gemini provider is not properly configured", provider=self.provider_name
            )

    def _build_full_prompt(self, prompt, system_prompt):
        """Build full prompt combining system and user prompts.

        Parameters
        ----------
        prompt : str
            User prompt
        system_prompt : str, optional
            System prompt

        Returns
        -------
        str
            Combined prompt
        """
        if system_prompt:
            return f"{system_prompt}\n\n{prompt}"
        return prompt

    def _build_generation_config(self, temperature, max_tokens, **kwargs):
        """Build generation configuration for Gemini API.

        Parameters
        ----------
        temperature : float, optional
            Sampling temperature
        max_tokens : int, optional
            Maximum tokens
        **kwargs : dict
            Additional parameters

        Returns
        -------
        dict
            Generation configuration
        """
        config = {}
        if temperature is not None:
            config["temperature"] = temperature
        if max_tokens is not None:
            config["max_output_tokens"] = max_tokens
        config.update(kwargs)
        return config

    def _call_gemini_api(self, prompt, config):
        """Make API call to Gemini.

        Parameters
        ----------
        prompt : str
            Full prompt to send
        config : dict
            Generation configuration

        Returns
        -------
        object
            Gemini API response
        """
        return self.model.generate_content(
            prompt,
            generation_config=config if config else None,
        )

    def _process_response(self, response):
        """Process and validate Gemini response.

        Parameters
        ----------
        response : object
            Gemini API response

        Returns
        -------
        str
            Processed response text

        Raises
        ------
        LLMResponseError
            If response is empty
        """
        if not response.text:
            raise LLMResponseError(
                "Empty response content from Gemini", provider=self.provider_name
            )

        logger.debug(
            f"Gemini response generated successfully (model: {self.default_model_name})"
        )
        return response.text.strip()

    def _handle_gemini_error(self, error):
        """Handle and map Gemini API errors to custom exceptions.

        Parameters
        ----------
        error : Exception
            Original Gemini API error

        Raises
        ------
        Various LLM exceptions based on error type
        """
        error_message = str(error).lower()

        if self._is_auth_error(error_message):
            raise LLMAuthenticationError(
                f"Gemini authentication failed: {error}",
                provider=self.provider_name,
                original_error=error,
            )
        elif self._is_rate_limit_error(error_message):
            raise LLMRateLimitError(
                f"Gemini rate limit exceeded: {error}",
                provider=self.provider_name,
                original_error=error,
            )
        elif self._is_network_error(error_message):
            raise LLMNetworkError(
                f"Gemini network error: {error}",
                provider=self.provider_name,
                original_error=error,
            )
        elif self._is_safety_error(error_message):
            raise LLMResponseError(
                f"Gemini content blocked due to safety filters: {error}",
                provider=self.provider_name,
                original_error=error,
            )
        else:
            raise LLMResponseError(
                f"Gemini API error: {error}",
                provider=self.provider_name,
                original_error=error,
            )

    def _is_auth_error(self, error_message):
        """Check if error is authentication related."""
        return "api_key" in error_message or "authentication" in error_message

    def _is_rate_limit_error(self, error_message):
        """Check if error is rate limit related."""
        return "quota" in error_message or "rate limit" in error_message

    def _is_network_error(self, error_message):
        """Check if error is network related."""
        return "timeout" in error_message or "connection" in error_message

    def _is_safety_error(self, error_message):
        """Check if error is safety filter related."""
        return "blocked" in error_message or "safety" in error_message

    def validate_response(self, response):
        """Validate Gemini response.

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
        """Get list of available Gemini models.

        Returns
        -------
        list
            List of available Gemini model identifiers
        """
        return [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-1.0-pro",
        ]

    def get_provider_info(self):
        """Get detailed Gemini provider information.

        Returns
        -------
        dict
            Provider information with Gemini-specific details
        """
        info = super().get_provider_info()
        info.update(
            {
                "library_available": True,  # Since we import directly now
                "default_model": self.default_model_name,
                "available_models": self.get_available_models(),
            }
        )
        return info
