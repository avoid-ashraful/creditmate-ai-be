"""
LLM content parsing service for extracting structured data.
"""

import json
import logging
import os

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
    """Service for parsing extracted content using Large Language Models.

    This service handles the conversion of unstructured text content from
    various sources (PDFs, webpages, images, CSV) into structured credit card
    data using OpenAI GPT models with Gemini as fallback.
    """

    def __init__(self):
        """Initialize the LLM parser.

        Sets up the Gemini AI configuration for fallback scenarios.

        Returns
        -------
        None
        """
        self._configure_genai()

    def parse_credit_card_data(self, content, bank_name):
        """Parse credit card information from extracted content using LLM.

        Parameters
        ----------
        content : str
            Extracted text content to parse from various sources
        bank_name : str
            Name of the bank for context and specialized parsing

        Returns
        -------
        dict
            Parsed and validated credit card data containing structured
            information about credit cards found in the content

        Raises
        ------
        ConfigurationError
            If Gemini AI is not properly configured
        AIParsingError
            If parsing fails due to LLM errors or invalid content
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

    def parse_comprehensive_data(self, content, bank_name):
        """Parse both structured credit card data and comprehensive raw data.

        Parameters
        ----------
        content : str
            Extracted text content to parse
        bank_name : str
            Name of the bank for specialized parsing context

        Returns
        -------
        tuple of (dict, dict)
            First element contains structured credit card data,
            second element contains comprehensive raw data with all fields

        Raises
        ------
        ConfigurationError
            If Gemini AI is not properly configured
        AIParsingError
            If parsing fails due to LLM processing errors
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

    def _configure_genai(self):
        """Configure Gemini AI if available.

        Sets up Gemini AI client configuration using the API key from
        Django settings if available.

        Returns
        -------
        None
        """
        if genai is not None and hasattr(settings, "GEMINI_API_KEY"):
            genai.configure(api_key=settings.GEMINI_API_KEY)

    def _validate_configuration(self):
        """Validate that required dependencies and configuration are available.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        ConfigurationError
            If Google Generative AI library is not installed or
            Gemini API key is not configured in settings
        """
        if genai is None:
            raise ConfigurationError("Google Generative AI library not installed")

        if not hasattr(settings, "GEMINI_API_KEY") or not settings.GEMINI_API_KEY:
            raise ConfigurationError("Gemini API key not configured")

    def _generate_ai_response(self, content, bank_name):
        """Generate AI response for the given content using OpenRouter.

        Parameters
        ----------
        content : str
            Text content to analyze and parse
        bank_name : str
            Bank name for contextual parsing optimization

        Returns
        -------
        str
            Raw AI response containing parsed credit card information

        Raises
        ------
        AIParsingError
            If AI generation fails or returns empty response
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

    def _generate_gemini_response(self, content, bank_name):
        """Fallback method to generate response using direct Gemini API.

        Parameters
        ----------
        content : str
            Text content to analyze when OpenRouter fails
        bank_name : str
            Bank name for parsing context

        Returns
        -------
        str
            Raw AI response from Gemini API

        Raises
        ------
        AIParsingError
            If Gemini generation fails or returns empty response
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

    def _generate_comprehensive_ai_response(self, content, bank_name):
        """Generate AI response for comprehensive data extraction using OpenRouter.

        Parameters
        ----------
        content : str
            Text content to analyze for comprehensive extraction
        bank_name : str
            Bank name for contextual processing

        Returns
        -------
        str
            Raw AI response with comprehensive credit card data

        Raises
        ------
        AIParsingError
            If AI generation fails or returns insufficient data
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

    def _generate_comprehensive_gemini_response(self, content, bank_name):
        """Fallback method for comprehensive data extraction using direct Gemini API.

        Parameters
        ----------
        content : str
            Text content to analyze using Gemini fallback
        bank_name : str
            Bank name for specialized parsing context

        Returns
        -------
        str
            Raw AI response with comprehensive data from Gemini

        Raises
        ------
        AIParsingError
            If Gemini generation fails or produces invalid output
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

    def _parse_json_response(self, raw_response, bank_name):
        """Parse JSON response from AI.

        Parameters
        ----------
        raw_response : str
            Raw text response from AI model containing JSON
        bank_name : str
            Bank name for error context and logging

        Returns
        -------
        dict or list
            Parsed JSON data structure from AI response

        Raises
        ------
        AIParsingError
            If JSON parsing fails due to malformed response
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

    def _validate_and_sanitize_data(self, parsed_data, bank_name):
        """Validate and sanitize parsed data.

        Parameters
        ----------
        parsed_data : dict or list
            Raw parsed data from AI response to validate
        bank_name : str
            Bank name for validation context and error reporting

        Returns
        -------
        dict
            Validated and sanitized credit card data with error information
            if validation fails
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

    def _build_parsing_prompt(self, content, bank_name):
        """Build the prompt for LLM parsing.

        Parameters
        ----------
        content : str
            Text content to include in parsing prompt
        bank_name : str
            Bank name for contextual prompt customization

        Returns
        -------
        str
            Formatted prompt with instructions and content for LLM
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

    def _build_comprehensive_parsing_prompt(self, content, bank_name):
        """Build the prompt for comprehensive LLM parsing to extract all available data.

        Parameters
        ----------
        content : str
            Text content to analyze comprehensively
        bank_name : str
            Bank name for prompt contextualization

        Returns
        -------
        str
            Formatted comprehensive parsing prompt for maximum data extraction
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
