"""
Base classes and interfaces for LLM providers.

This module defines the abstract base class that all LLM providers must implement,
ensuring consistent interface across different provider implementations.
"""

from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    This class defines the interface that all LLM providers must implement,
    ensuring consistent behavior across different providers like OpenRouter,
    Gemini, etc.
    """

    supports_images = False

    def __init__(self, provider_name):
        """Initialize the LLM provider.

        Parameters
        ----------
        provider_name : str
            Name identifier for this provider (e.g., "openrouter", "gemini")

        Returns
        -------
        None
        """
        self.provider_name = provider_name
        self._is_configured = False
        # Stream F: tokens from the most recent provider response, if the
        # provider API returned them (else stays None — never estimated).
        self.last_usage = None

    def _emit_usage(
        self,
        *,
        model="",
        latency_ms=None,
        status="success",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        purpose="extraction",
        run_id="",
        session_id="",
        routing_reason="",
    ):
        """Record one call in the LLMUsage ledger + metrics; never raises."""
        import logging

        try:
            from common.llm.usage import record_usage

            return record_usage(
                provider=self.provider_name,
                model=model,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                run_id=run_id,
                session_id=session_id,
                routing_reason=routing_reason,
                status=status,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to record LLM usage for %s", self.provider_name
            )
            return None

    @staticmethod
    def _pop_tracking_kwargs(kwargs):
        """Pop Stream F tracking kwargs so they never leak to provider APIs."""
        return {
            "purpose": kwargs.pop("purpose", "extraction"),
            "run_id": kwargs.pop("run_id", ""),
            "session_id": kwargs.pop("session_id", ""),
            "routing_reason": kwargs.pop("routing_reason", ""),
        }

    @property
    def name(self):
        """Get the provider name.

        Returns
        -------
        str
            Provider name identifier
        """
        return self.provider_name

    @property
    def is_configured(self):
        """Check if provider is properly configured.

        Returns
        -------
        bool
            True if provider is configured, False otherwise
        """
        return self._is_configured

    @abstractmethod
    def configure(self):
        """Configure the provider with necessary credentials and settings.

        Returns
        -------
        bool
            True if configuration successful, False otherwise
        """
        pass

    @abstractmethod
    def is_available(self):
        """Check if the provider is available for use.

        Returns
        -------
        bool
            True if provider is available and configured
        """
        pass

    @abstractmethod
    def generate_response(self, prompt, system_prompt=None, **kwargs):
        """Generate response from the LLM provider.

        Parameters
        ----------
        prompt : str
            The main prompt to send to the LLM
        system_prompt : str, optional
            System prompt to set context/behavior
        **kwargs : dict
            Additional provider-specific parameters

        Returns
        -------
        str
            Generated response from the LLM

        Raises
        ------
        LLMError
            For various provider-specific errors
        """
        pass

    @abstractmethod
    def validate_response(self, response):
        """Validate that the response meets basic requirements.

        Parameters
        ----------
        response : str
            Response to validate

        Returns
        -------
        bool
            True if response is valid
        """
        pass

    def get_provider_info(self):
        """Get information about this provider.

        Returns
        -------
        dict
            Provider information including name, configuration status, etc.
        """
        return {
            "name": self.provider_name,
            "is_configured": self.is_configured,
            "is_available": self.is_available(),
            "supports_images": self.supports_images,
        }
