"""
LLM content parsing service for extracting structured data.
"""

import json
import logging
from typing import Any, Dict

from django.conf import settings

from ..exceptions import AIParsingError, ConfigurationError
from ..validators import CreditCardDataValidator

# Optional import for Gemini AI
try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)


class LLMContentParser:
    """Service for parsing extracted content using LLM."""

    def __init__(self):
        """Initialize the LLM parser."""
        self._configure_genai()

    def parse_credit_card_data(self, content: str, bank_name: str) -> Dict[str, Any]:
        """
        Parse credit card information from extracted content using LLM.

        Args:
            content (str): Extracted content to parse
            bank_name (str): Name of the bank for context

        Returns:
            Dict[str, Any]: Parsed and validated credit card data

        Raises:
            ConfigurationError: If Gemini AI is not properly configured
            AIParsingError: If parsing fails
        """
        self._validate_configuration()

        try:
            raw_data = self._generate_ai_response(content, bank_name)
            parsed_data = self._parse_json_response(raw_data, bank_name)
            validated_data = self._validate_and_sanitize_data(parsed_data, bank_name)

            return validated_data

        except (ConfigurationError, AIParsingError):
            raise
        except Exception as e:
            raise AIParsingError(
                "Unexpected error during AI parsing",
                {"bank_name": bank_name, "error_type": type(e).__name__},
            ) from e

    def _configure_genai(self) -> None:
        """Configure Gemini AI if available."""
        if genai is not None and hasattr(settings, "GEMINI_API_KEY"):
            genai.configure(api_key=settings.GEMINI_API_KEY)

    def _validate_configuration(self) -> None:
        """
        Validate that required dependencies and configuration are available.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if genai is None:
            raise ConfigurationError("Google Generative AI library not installed")

        if not hasattr(settings, "GEMINI_API_KEY") or not settings.GEMINI_API_KEY:
            raise ConfigurationError("Gemini API key not configured")

    def _generate_ai_response(self, content: str, bank_name: str) -> str:
        """
        Generate AI response for the given content.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Raw AI response

        Raises:
            AIParsingError: If AI generation fails
        """
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = self._build_parsing_prompt(content, bank_name)

            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )

            if not response or not response.text:
                raise AIParsingError(
                    "Empty response from Gemini API", {"bank_name": bank_name}
                )

            return response.text.strip()

        except Exception as e:
            if isinstance(e, AIParsingError):
                raise
            raise AIParsingError(
                f"Error generating AI response: {str(e)}", {"bank_name": bank_name}
            ) from e

    def _parse_json_response(self, raw_response: str, bank_name: str) -> Any:
        """
        Parse JSON response from AI, cleaning up markdown if needed.

        Args:
            raw_response (str): Raw response from AI
            bank_name (str): Bank name for error context

        Returns:
            Any: Parsed JSON data

        Raises:
            AIParsingError: If JSON parsing fails
        """
        # Clean up markdown code blocks if present
        cleaned_response = self._clean_markdown_response(raw_response)

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            raise AIParsingError(
                "Invalid JSON response from Gemini API",
                {
                    "bank_name": bank_name,
                    "raw_response": raw_response[:500],
                    "json_error": str(e),
                },
            ) from e

    def _clean_markdown_response(self, response: str) -> str:
        """
        Clean markdown code blocks from AI response.

        Args:
            response (str): Raw response to clean

        Returns:
            str: Cleaned response
        """
        if response.startswith("```json"):
            return response.replace("```json", "").replace("```", "").strip()
        elif response.startswith("```"):
            return response.replace("```", "").strip()
        return response

    def _validate_and_sanitize_data(
        self, parsed_data: Any, bank_name: str
    ) -> Dict[str, Any]:
        """
        Validate and sanitize parsed data.

        Args:
            parsed_data (Any): Data to validate
            bank_name (str): Bank name for context

        Returns:
            Dict[str, Any]: Validated and sanitized data
        """
        # Validate the parsed data
        is_valid, validation_errors = CreditCardDataValidator.validate_credit_card_data(
            parsed_data
        )

        if not is_valid:
            logger.warning(f"Data validation failed for {bank_name}: {validation_errors}")
            # Still return the data but with validation errors noted
            return {"validation_errors": validation_errors, "data": parsed_data}

        # Sanitize the data
        sanitized_data = CreditCardDataValidator.sanitize_credit_card_data(parsed_data)
        return sanitized_data

    def _build_parsing_prompt(self, content: str, bank_name: str) -> str:
        """
        Build the prompt for LLM parsing.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Formatted prompt
        """
        return f"""
Extract credit card information from the following content for {bank_name}.

Please extract the following information for each credit card and return as JSON:
- name: Credit card name
- annual_fee: Annual fee (numeric value, 0 if free)
- interest_rate_apr: Interest rate APR (percentage)
- lounge_access_international: Number of international lounge visits
- lounge_access_domestic: Number of domestic lounge visits
- cash_advance_fee: Cash advance fee description
- late_payment_fee: Late payment fee description
- annual_fee_waiver_policy: Annual fee waiver conditions (JSON object)
- reward_points_policy: Reward points policy description
- additional_features: List of additional features

Return the data as a JSON array of credit card objects. If no credit card data is found, return an empty array.

Content to analyze:
{content[:4000]}  # Limit content length for API
"""
