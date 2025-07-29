"""
Custom exceptions for banks app to provide better error categorization.
"""


class CrawlingError(Exception):
    """Base class for all crawling-related errors."""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class RetryableError(CrawlingError):
    """Errors that should be retried (temporary failures)."""

    pass


class PermanentError(CrawlingError):
    """Errors that should not be retried (permanent failures)."""

    pass


class ContentExtractionError(RetryableError):
    """Content extraction failed - usually network or file format issues."""

    pass


class AIParsingError(RetryableError):
    """AI parsing failed - could be API issues or rate limiting."""

    pass


class DataValidationError(PermanentError):
    """Data validation failed - malformed or invalid data."""

    pass


class ConfigurationError(PermanentError):
    """Configuration issues - missing API keys, invalid URLs, etc."""

    pass


class NetworkError(RetryableError):
    """Network-related errors - timeouts, connection issues."""

    pass


class FileFormatError(PermanentError):
    """File format is not supported or corrupted."""

    pass
