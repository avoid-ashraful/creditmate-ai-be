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
        }
