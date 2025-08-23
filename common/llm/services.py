"""
LLM orchestrator service with fallback logic.

This module provides a unified interface to multiple LLM providers with
automatic fallback, retry logic, and comprehensive error handling.
"""

import logging

from common.llm.exceptions import (
    AllLLMProvidersFailedError,
    LLMConfigurationError,
    LLMError,
    LLMRateLimitError,
)
from common.llm.providers import GeminiProvider, OpenRouterProvider

logger = logging.getLogger(__name__)


class LLMOrchestrator:
    """Orchestrator service for managing multiple LLM providers with fallback logic.

    This service provides a unified interface to multiple LLM providers,
    automatically handling fallbacks, retries, and provider-specific errors.
    The service attempts providers in order of preference and falls back to
    the next available provider when one fails.
    """

    def __init__(self, providers=None):
        """Initialize LLM orchestrator with specified providers.

        Parameters
        ----------
        providers : list of str, optional
            List of provider names to use in order of preference.
            Defaults to ["openrouter", "gemini"]
        """
        self.provider_order = providers or ["openrouter", "gemini"]
        self.providers = {}
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all configured providers."""
        provider_classes = {
            "openrouter": OpenRouterProvider,
            "gemini": GeminiProvider,
        }

        for provider_name in self.provider_order:
            if provider_name in provider_classes:
                try:
                    provider_instance = provider_classes[provider_name]()
                    self.providers[provider_name] = provider_instance
                    logger.info(
                        f"Initialized {provider_name} provider: {'available' if provider_instance.is_available() else 'not available'}"
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize {provider_name} provider: {e}")
            else:
                logger.warning(f"Unknown provider: {provider_name}")

    def get_available_providers(self):
        """Get list of currently available providers.

        Returns
        -------
        list of str
            Names of providers that are configured and available
        """
        return [
            name for name, provider in self.providers.items() if provider.is_available()
        ]

    def get_provider_status(self):
        """Get detailed status of all providers.

        Returns
        -------
        dict
            Dictionary mapping provider names to their status information
        """
        return {
            name: provider.get_provider_info()
            for name, provider in self.providers.items()
        }

    def generate_response(
        self, prompt, system_prompt=None, preferred_provider=None, max_retries=1, **kwargs
    ):
        """Generate response using available providers with fallback logic.

        Parameters
        ----------
        prompt : str
            The main prompt to send to the LLM
        system_prompt : str, optional
            System prompt to set context/behavior
        preferred_provider : str, optional
            Specific provider to try first (still falls back to others)
        max_retries : int
            Maximum number of retries per provider (default: 1)
        **kwargs : dict
            Additional parameters to pass to the provider

        Returns
        -------
        dict
            Response information containing:
            - response: str - The generated text
            - provider: str - Name of the provider that succeeded
            - attempts: list - List of providers that were attempted
            - errors: dict - Any errors encountered during attempts

        Raises
        ------
        AllLLMProvidersFailedError
            If all configured providers fail to generate a response
        """
        provider_order = self._get_provider_order(preferred_provider)
        attempts = []
        errors = {}

        for provider_name in provider_order:
            result = self._try_provider_with_retries(
                provider_name,
                prompt,
                system_prompt,
                max_retries,
                attempts,
                errors,
                **kwargs,
            )
            if result:
                return result

        self._handle_all_providers_failed(attempts, errors)

    def _get_provider_order(self, preferred_provider):
        """Get ordered list of providers to try.

        Parameters
        ----------
        preferred_provider : str, optional
            Provider to try first

        Returns
        -------
        list
            Ordered list of provider names

        Raises
        ------
        LLMConfigurationError
            If no providers are available
        """
        available_providers = self.get_available_providers()

        if not available_providers:
            raise LLMConfigurationError("No LLM providers are available")

        provider_order = available_providers.copy()
        if preferred_provider and preferred_provider in provider_order:
            provider_order.remove(preferred_provider)
            provider_order.insert(0, preferred_provider)

        return provider_order

    def _try_provider_with_retries(
        self,
        provider_name,
        prompt,
        system_prompt,
        max_retries,
        attempts,
        errors,
        **kwargs,
    ):
        """Try a provider with retry logic.

        Parameters
        ----------
        provider_name : str
            Name of provider to try
        prompt : str
            Prompt to send
        system_prompt : str, optional
            System prompt
        max_retries : int
            Maximum retry attempts
        attempts : list
            List to track attempts
        errors : dict
            Dictionary to track errors
        **kwargs : dict
            Additional parameters

        Returns
        -------
        dict or None
            Success result or None if all attempts failed
        """
        provider = self.providers[provider_name]

        for attempt in range(max_retries + 1):
            attempt_key = f"{provider_name}_attempt_{attempt + 1}"
            attempts.append(attempt_key)

            try:
                response = provider.generate_response(
                    prompt=prompt, system_prompt=system_prompt, **kwargs
                )

                if provider.validate_response(response):
                    logger.info(
                        f"Successfully generated response using {provider_name} (attempt {attempt + 1})"
                    )
                    return {
                        "response": response,
                        "provider": provider_name,
                        "attempts": attempts,
                        "errors": errors,
                    }
                else:
                    raise LLMError(f"Invalid response from {provider_name}")

            except LLMRateLimitError as e:
                logger.warning(f"Rate limit exceeded for {provider_name}: {e}")
                errors[attempt_key] = str(e)
                break  # Don't retry rate limit errors

            except LLMError as e:
                errors[attempt_key] = str(e)
                if not self._should_retry_provider_error(
                    provider_name, attempt, max_retries, e
                ):
                    break

            except Exception as e:
                logger.error(f"Unexpected error with {provider_name}: {e}")
                errors[attempt_key] = str(e)
                break

        return None

    def _should_retry_provider_error(self, provider_name, attempt, max_retries, error):
        """Determine if a provider error should be retried.

        Parameters
        ----------
        provider_name : str
            Name of the provider
        attempt : int
            Current attempt number
        max_retries : int
            Maximum retry attempts
        error : Exception
            The error that occurred

        Returns
        -------
        bool
            True if should retry, False otherwise
        """
        logger.warning(f"{provider_name} attempt {attempt + 1} failed: {error}")

        if attempt < max_retries:
            logger.info(f"Retrying {provider_name} (attempt {attempt + 2})")
            return True
        else:
            logger.warning(f"All retries exhausted for {provider_name}")
            return False

    def _handle_all_providers_failed(self, attempts, errors):
        """Handle the case when all providers fail.

        Parameters
        ----------
        attempts : list
            List of all attempts made
        errors : dict
            Dictionary of all errors encountered

        Raises
        ------
        AllLLMProvidersFailedError
            Always raised when all providers fail
        """
        raise AllLLMProvidersFailedError(
            f"All LLM providers failed after {len(attempts)} attempts", failures=errors
        )

    def is_any_provider_available(self):
        """Check if any provider is available.

        Returns
        -------
        bool
            True if at least one provider is available
        """
        return len(self.get_available_providers()) > 0

    def validate_configuration(self):
        """Validate the configuration of all providers.

        Returns
        -------
        dict
            Configuration validation results containing:
            - is_valid: bool - True if at least one provider is configured
            - providers: dict - Status of each provider
            - available_count: int - Number of available providers
            - recommendations: list - Recommendations for improvement
        """
        provider_status = self.get_provider_status()
        available_providers = self.get_available_providers()

        recommendations = []

        if not available_providers:
            recommendations.append(
                "No LLM providers are available. Configure at least one provider."
            )
        elif len(available_providers) == 1:
            recommendations.append(
                "Only one provider is available. Configure additional providers for better reliability."
            )

        for name, status in provider_status.items():
            if not status.get("is_configured", False):
                recommendations.append(
                    f"Configure {name} provider by setting the required API key."
                )

        return {
            "is_valid": len(available_providers) > 0,
            "providers": provider_status,
            "available_count": len(available_providers),
            "total_count": len(self.providers),
            "recommendations": recommendations,
        }

    def get_provider_by_name(self, name: str):
        """Get a specific provider instance by name.

        Parameters
        ----------
        name : str
            Name of the provider to retrieve

        Returns
        -------
        BaseLLMProvider or None
            Provider instance if found, None otherwise
        """
        return self.providers.get(name)
