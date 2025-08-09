"""
LLM content parsing service for extracting structured data.
"""

import json
import logging
import os
from typing import Any, Dict

from django.conf import settings

from ..exceptions import AIParsingError, ConfigurationError
from ..validators import CreditCardDataValidator

# Optional import for OpenAI (OpenRouter)
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

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

    def parse_comprehensive_data(
        self, content: str, bank_name: str
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Parse both structured credit card data and comprehensive raw data.

        Args:
            content (str): Extracted content to parse
            bank_name (str): Name of the bank for context

        Returns:
            tuple: (structured_data, raw_comprehensive_data)

        Raises:
            ConfigurationError: If Gemini AI is not properly configured
            AIParsingError: If parsing fails
        """
        self._validate_configuration()

        try:
            # Get structured credit card data
            structured_data = self.parse_credit_card_data(content, bank_name)

            # Get comprehensive raw data
            raw_response = self._generate_comprehensive_ai_response(content, bank_name)
            raw_data = self._parse_json_response(raw_response, bank_name)

            return structured_data, raw_data

        except (ConfigurationError, AIParsingError):
            raise
        except Exception as e:
            raise AIParsingError(
                "Unexpected error during comprehensive AI parsing",
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
        Generate AI response for the given content using OpenRouter.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Raw AI response

        Raises:
            AIParsingError: If AI generation fails
        """
        # Check if OpenRouter API key is available
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key or not OPENAI_AVAILABLE:
            # Fallback to Gemini
            return self._generate_gemini_response(content, bank_name)

        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_api_key,
            )

            prompt = self._build_parsing_prompt(content, bank_name)

            response = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://creditmate.ai",
                    "X-Title": "Credit Mate AI",
                },
                model="deepseek/deepseek-chat-v3-0324:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=12000,
            )

            if not response.choices or not response.choices[0].message.content:
                raise AIParsingError(
                    "Empty response from OpenRouter/Gemini 2.5", {"bank_name": bank_name}
                )

            return response.choices[0].message.content.strip()

        except Exception as e:
            if isinstance(e, AIParsingError):
                raise
            # Try fallback to Gemini if OpenRouter fails
            logger.warning(
                f"OpenRouter failed for {bank_name}, trying Gemini fallback: {str(e)}"
            )
            return self._generate_gemini_response(content, bank_name)

    def _generate_gemini_response(self, content: str, bank_name: str) -> str:
        """
        Fallback method to generate response using direct Gemini API.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Raw AI response

        Raises:
            AIParsingError: If generation fails
        """
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = self._build_parsing_prompt(content, bank_name)

            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=4000,
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

    def _generate_comprehensive_ai_response(self, content: str, bank_name: str) -> str:
        """
        Generate AI response for comprehensive data extraction using OpenRouter.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Raw AI response with comprehensive data

        Raises:
            AIParsingError: If AI generation fails
        """
        # Check if OpenRouter API key is available
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key or not OPENAI_AVAILABLE:
            # Fallback to Gemini
            return self._generate_comprehensive_gemini_response(content, bank_name)

        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_api_key,
            )

            prompt = self._build_comprehensive_parsing_prompt(content, bank_name)

            response = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://creditmate.ai",
                    "X-Title": "Credit Mate AI",
                },
                model="deepseek/deepseek-chat-v3-0324:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=16000,
            )

            if not response.choices or not response.choices[0].message.content:
                raise AIParsingError(
                    "Empty response from OpenRouter/Gemini 2.5 for comprehensive parsing",
                    {"bank_name": bank_name},
                )

            return response.choices[0].message.content.strip()

        except Exception as e:
            if isinstance(e, AIParsingError):
                raise
            # Try fallback to Gemini if OpenRouter fails
            logger.warning(
                f"OpenRouter comprehensive parsing failed for {bank_name}, trying Gemini fallback: {str(e)}"
            )
            return self._generate_comprehensive_gemini_response(content, bank_name)

    def _generate_comprehensive_gemini_response(
        self, content: str, bank_name: str
    ) -> str:
        """
        Fallback method for comprehensive data extraction using direct Gemini API.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Raw AI response with comprehensive data

        Raises:
            AIParsingError: If generation fails
        """
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = self._build_comprehensive_parsing_prompt(content, bank_name)

            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=12000,
                ),
            )

            if not response or not response.text:
                raise AIParsingError(
                    "Empty response from Gemini API for comprehensive parsing",
                    {"bank_name": bank_name},
                )

            return response.text.strip()

        except Exception as e:
            if isinstance(e, AIParsingError):
                raise
            raise AIParsingError(
                f"Error generating comprehensive AI response: {str(e)}",
                {"bank_name": bank_name},
            ) from e

    def _parse_json_response(self, raw_response: str, bank_name: str) -> Any:
        """
        Parse JSON response from AI.

        Args:
            raw_response (str): Raw response from AI
            bank_name (str): Bank name for error context

        Returns:
            Any: Parsed JSON data

        Raises:
            AIParsingError: If JSON parsing fails
        """
        # Clean the response - remove markdown code blocks
        cleaned_response = raw_response.strip()

        # Remove markdown JSON code blocks
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]  # Remove ```json
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]  # Remove ```
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]  # Remove trailing ```

        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            logger.error(
                f"JSON parsing failed for {bank_name}. Raw response: {raw_response}"
            )
            raise AIParsingError(
                "Invalid JSON response from AI. Please check the prompt configuration.",
                {
                    "bank_name": bank_name,
                    "raw_response": raw_response[:500],
                    "json_error": str(e),
                },
            ) from e

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
You are a data extraction AI. Extract credit card information from the following content for {bank_name}.

CRITICAL INSTRUCTIONS:
1. You MUST respond with ONLY valid JSON - no markdown, no explanations, no code blocks
2. Start your response immediately with [ and end with ]
3. Do not use ```json or ``` or any other formatting
4. Ensure the JSON is complete and properly closed

Extract these fields for each credit card with EXACT formats:
- name: Credit card name/type (e.g., "Platinum Card", "Gold Card", "Classic Card", "World Card", etc.) - NOT the annual fee amount
- annual_fee: Annual fee as pure number without currency (e.g., "TK. 5,000" becomes 5000, "Free" becomes 0)
- interest_rate_apr: Interest rate as decimal number (e.g., "20%" becomes 20.0, "17%" becomes 17.0)
- lounge_access_international: Lounge access description as string (e.g., "10 complimentary visits", "Unlimited", or "" if none)
- lounge_access_domestic: Lounge access description as string (e.g., "Unlimited visits for cardholder only", or "" if none)
- cash_advance_fee: Fee description as string
- late_payment_fee: Fee description as string
- annual_fee_waiver_policy: Waiver conditions as simple string (or null if not available)
- reward_points_policy: Reward policy description as string or null
- additional_features: Array of feature strings or null

CRITICAL: Follow these number conversion rules strictly:
- Remove ALL currency symbols and text (TK., BDT, USD, $)
- Remove ALL commas and spaces from numbers
- Convert percentages to decimals (20% → 20.0, not "20%")
- Convert "Free" to 0, "Unlimited" to null for numeric fields

Return format: JSON array of objects. If no credit cards found, return []

Content to analyze:
{content}"""

    def _build_comprehensive_parsing_prompt(self, content: str, bank_name: str) -> str:
        """
        Build the prompt for comprehensive LLM parsing to extract all available data.

        Args:
            content (str): Content to analyze
            bank_name (str): Bank name for context

        Returns:
            str: Formatted comprehensive prompt
        """
        return f"""
You are a comprehensive data extraction AI. Extract ALL available information from this {bank_name} credit card document.

CRITICAL FORMATTING RULES:
1. You MUST respond with ONLY valid JSON - no markdown, no explanations, no code blocks
2. Start your response immediately with [ and end with ]
3. Do not use ```json or ``` or any other formatting
4. Ensure the JSON is complete and properly closed
5. If content is too long, prioritize completeness of objects over quantity

EXTRACTION INSTRUCTIONS:
1. For credit card model fields, use these exact field names:
   - name, annual_fee, interest_rate_apr, lounge_access_international, lounge_access_domestic
   - cash_advance_fee, late_payment_fee, annual_fee_waiver_policy, reward_points_policy, additional_features

2. For any other data found, use the column header/title as key:
   - Example: "CIB Fee" -> "CIB Fee": "BDT 100"
   - Example: "Processing Fee" -> "Processing Fee": "2%"

3. Extract data for each credit card type (World, Platinum, Gold, Classic, etc.)

4. Include ALL charges, fees, benefits, policies mentioned

5. Return as JSON array where each object represents one credit card

Content to analyze:
{content}"""
