"""
LLM-specific exceptions.

This module contains all exceptions related to Large Language Model operations,
providing detailed error information for different failure scenarios.
"""


class LLMError(Exception):
    """Base exception for all LLM-related errors."""

    def __init__(self, message, provider=None, original_error=None):
        """Initialize LLM error.

        Parameters
        ----------
        message : str
            Human-readable error message
        provider : str, optional
            Name of the LLM provider that failed
        original_error : Exception, optional
            Original exception that caused this error
        """
        super().__init__(message)
        self.provider = provider
        self.original_error = original_error


class LLMConfigurationError(LLMError):
    """Raised when LLM provider configuration is invalid or missing."""

    pass


class LLMAuthenticationError(LLMError):
    """Raised when LLM provider authentication fails."""

    pass


class LLMRateLimitError(LLMError):
    """Raised when LLM provider rate limit is exceeded."""

    pass


class LLMNetworkError(LLMError):
    """Raised when network communication with LLM provider fails."""

    pass


class LLMResponseError(LLMError):
    """Raised when LLM provider returns invalid or empty response."""

    pass


class LLMParsingError(LLMError):
    """Raised when LLM response cannot be parsed or is malformed."""

    pass


class LLMContentError(LLMError):
    """Raised when input content is invalid for LLM processing."""

    pass


class AllLLMProvidersFailedError(LLMError):
    """Raised when all configured LLM providers have failed."""

    def __init__(self, message="All LLM providers failed", failures=None):
        """Initialize with provider failure details.

        Parameters
        ----------
        message : str
            Error message
        failures : dict, optional
            Dictionary mapping provider names to their respective errors
        """
        super().__init__(message)
        self.failures = failures or {}
