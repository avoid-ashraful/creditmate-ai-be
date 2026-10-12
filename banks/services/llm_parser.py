"""
LLM parser using the orchestrator architecture.

This module provides LLM parsing service that uses the LLM orchestrator
with automatic fallback and comprehensive error handling.
"""

import json
import logging
import re

from banks.exceptions import AIParsingError, ConfigurationError
from banks.services.extraction_provider import OrchestratorExtractionProvider
from banks.services.multi_pass_extractor import MultiPassLLMExtractor
from banks.services.prompt_templates import BankSpecificPrompts
from banks.validators import CreditCardDataValidator
from common.llm import LLMOrchestrator
from common.llm.exceptions import AllLLMProvidersFailedError

logger = logging.getLogger(__name__)


class LLMContentParser:
    """Enhanced LLM parser with orchestrator-based architecture.

    This service provides improved parsing capabilities with automatic
    provider fallback, better error handling, and comprehensive validation.

    It also exposes the Phase 2 multi-pass extraction pipeline
    (:meth:`parse_with_multi_pass`) which runs a bank-specific standard pass,
    a focused critical-field pass when needed, and a validation pass that
    produces a bounded confidence score.
    """

    def __init__(self, multi_pass_extractor=None, prompt_templates=None):
        """Initialize the LLM parser.

        Parameters
        ----------
        multi_pass_extractor : MultiPassLLMExtractor, optional
            Extractor used by :meth:`parse_with_multi_pass`. A default
            orchestrator-backed extractor is created when omitted.
        prompt_templates : BankSpecificPrompts, optional
            Bank-specific prompt template registry.
        """
        self.orchestrator = LLMOrchestrator()
        self.validator = CreditCardDataValidator()
        self.prompt_templates = prompt_templates or BankSpecificPrompts()
        self.multi_pass_extractor = multi_pass_extractor or MultiPassLLMExtractor(
            provider=OrchestratorExtractionProvider(self.orchestrator),
            prompt_templates=self.prompt_templates,
        )

    def parse_with_multi_pass(self, content, bank_name, method="unknown"):
        """Extract credit card data using the multi-pass pipeline.

        Parameters
        ----------
        content : str
            Extracted text content to parse.
        bank_name : str
            Bank name used to select the bank-specific prompt template.
        method : str, optional
            Extraction method that produced ``content``.

        Returns
        -------
        MultiPassExtractionResult
            Merged cards, bounded confidence, missing critical fields and
            per-pass provenance.

        Raises
        ------
        ConfigurationError
            If no LLM providers are configured.
        AIParsingError
            If every extraction pass failed.
        """
        # The extractor owns the provider it will call, so it is the source of
        # truth for availability (and it works with injected test doubles).
        if not self.multi_pass_extractor.is_provider_available():
            raise ConfigurationError(
                "No LLM providers are available for multi-pass parsing"
            )

        try:
            result = self.multi_pass_extractor.extract(content, bank_name, method=method)
        except AIParsingError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in multi-pass extraction: {e}")
            raise AIParsingError(
                f"Unexpected error during multi-pass extraction: {str(e)}"
            ) from e

        return self._apply_validation_stage(result)

    def _apply_validation_stage(self, result):
        """Run the real validation stage on a multi-pass result.

        Every card is sanitized with :class:`CreditCardDataValidator` (which
        keeps genuine ``0`` fees, stores missing/invalid values as ``None``) and
        then validated; any validation error is appended to the result issues
        so it reaches the quality score and the manual-review flag.

        Parameters
        ----------
        result : MultiPassExtractionResult
            Result returned by the extractor.

        Returns
        -------
        MultiPassExtractionResult
            The same result with sanitized cards and validation issues.
        """
        validated_cards = []
        validation_issues = []

        for card in result.credit_cards:
            if not isinstance(card, dict):
                continue
            sanitized = self.validator.sanitize_credit_card_data(card)
            # Keep any extra document columns (provenance) that the schema
            # validator does not know about, while overriding the normalized
            # values for the schema fields.
            sanitized = {**card, **sanitized}
            is_valid, errors = self.validator.validate_credit_card_data(sanitized)
            validated_cards.append(sanitized)
            if not is_valid:
                validation_issues.extend(f"validation_error: {e}" for e in errors)

        result.credit_cards = validated_cards
        if validation_issues:
            logger.warning(
                "Multi-pass validation issues for %s: %s",
                result.provider_used,
                validation_issues,
            )
            result.issues = sorted(set(list(result.issues) + validation_issues))
        return result

    def parse_credit_card_data(self, content, bank_name):
        """Parse credit card information from extracted content using LLM orchestrator.

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
        AIParsingError
            If all LLM providers fail or return invalid data
        ConfigurationError
            If no LLM providers are configured
        """
        self._validate_orchestrator_availability()

        try:
            llm_result = self._generate_llm_response(content, bank_name)
            parsed_data = self._clean_and_parse_response(llm_result["response"])

            return self._process_parsed_data(parsed_data, llm_result["provider"])

        except AllLLMProvidersFailedError as e:
            self._handle_provider_failures(e)
        except Exception as e:
            logger.error(f"Unexpected error in credit card parsing: {e}")
            raise AIParsingError(f"Unexpected error during parsing: {str(e)}") from e

    def parse_comprehensive_data(self, content, bank_name):
        """Parse comprehensive data from content using enhanced extraction.

        Parameters
        ----------
        content : str
            Text content to analyze comprehensively
        bank_name : str
            Bank name for prompt contextualization

        Returns
        -------
        tuple of (dict, dict)
            First element is comprehensive parsed data with all available information,
            second element contains metadata including provider used

        Raises
        ------
        AIParsingError
            If parsing fails or returns insufficient data
        """
        if not self.orchestrator.is_any_provider_available():
            raise ConfigurationError(
                "No LLM providers are available for comprehensive parsing"
            )

        try:
            result = self.orchestrator.generate_response(
                prompt=self._build_comprehensive_parsing_prompt(content, bank_name),
                max_retries=1,
                temperature=0.1,
                max_tokens=8000,  # Higher token limit for comprehensive parsing
            )

            raw_response = result["response"]
            used_provider = result["provider"]

            # Clean and parse the comprehensive response
            parsed_data = self._clean_and_parse_response(raw_response)

            logger.info(f"Comprehensive parsing completed using {used_provider}")
            return parsed_data, {"provider_used": used_provider}

        except AllLLMProvidersFailedError as e:
            logger.error(f"All LLM providers failed for comprehensive parsing: {e}")
            raise AIParsingError(
                "Failed to parse comprehensive data - all providers failed"
            ) from e

        except Exception as e:
            logger.error(f"Unexpected error in comprehensive parsing: {e}")
            raise AIParsingError(
                f"Unexpected error during comprehensive parsing: {str(e)}"
            ) from e

    def _clean_and_parse_response(self, raw_response):
        """Clean and parse the raw LLM response.

        Parameters
        ----------
        raw_response : str
            Raw response from LLM

        Returns
        -------
        list or dict
            Parsed JSON data

        Raises
        ------
        AIParsingError
            If response cannot be parsed as valid JSON
        """
        try:
            # Clean markdown formatting if present
            cleaned_response = re.sub(r"```json\s*|\s*```", "", raw_response.strip())
            cleaned_response = cleaned_response.strip()

            # Ensure it starts with [ or { for JSON
            if not (cleaned_response.startswith("[") or cleaned_response.startswith("{")):
                # Try to find JSON in the response
                json_match = re.search(r"([\[\{].*[\]\}])", cleaned_response, re.DOTALL)
                if json_match:
                    cleaned_response = json_match.group(1)
                else:
                    raise AIParsingError("No valid JSON found in LLM response")

            return json.loads(cleaned_response)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            raise AIParsingError(f"Invalid JSON response from LLM: {str(e)}") from e

    def _build_parsing_prompt(self, content, bank_name):
        """Build the prompt for LLM parsing.

        Uses the bank-specific template registry
        (:class:`banks.services.prompt_templates.BankSpecificPrompts`) so the
        model is told where to look for this bank's fee table, combined with
        the shared output contract (JSON array, zero vs missing rules).

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
        return self.prompt_templates.get_prompt_for_bank(bank_name, content)

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
        bank_prompt = self.prompt_templates.get_prompt_for_bank(bank_name, content)
        return f"""
{bank_prompt}

COMPREHENSIVE EXTRACTION RULES:
1. You MUST respond with ONLY valid JSON - no markdown, no explanations, no code blocks
2. Start your response immediately with [ and end with ]
3. Do not use ```json or ``` or any other formatting
4. Ensure the JSON is complete and properly closed
5. If content is too long, prioritize completeness of objects over quantity
6. For any field not listed in the contract above, use the exact column
   header/title as the key (e.g. "CIB Fee" -> "CIB Fee": "BDT 100")
7. Extract data for every credit card tier (World, Platinum, Gold, Classic, ...)
8. Include ALL charges, fees, benefits and policies mentioned
9. Never invent a value: a fee that is not stated in the document stays null
"""

    def get_orchestrator_status(self):
        """Get the current status of the LLM orchestrator.

        Returns
        -------
        dict
            Status information about available providers and configuration
        """
        return self.orchestrator.validate_configuration()

    def test_llm_connectivity(self):
        """Test connectivity to all configured LLM providers.

        Returns
        -------
        dict
            Test results for each provider
        """
        test_prompt = "Respond with exactly: OK"
        results = {}

        for provider_name in self.orchestrator.providers:
            try:
                result = self.orchestrator.generate_response(
                    prompt=test_prompt,
                    preferred_provider=provider_name,
                    max_retries=0,  # Don't retry for testing
                )
                results[provider_name] = {
                    "status": "success",
                    "response": result["response"][:50],  # First 50 chars
                }
            except Exception as e:
                results[provider_name] = {"status": "failed", "error": str(e)}

        return results

    def _validate_orchestrator_availability(self):
        """Validate that LLM orchestrator is available.

        Raises
        ------
        ConfigurationError
            If no LLM providers are configured
        """
        if not self.orchestrator.is_any_provider_available():
            raise ConfigurationError(
                "No LLM providers are available for credit card parsing"
            )

    def _generate_llm_response(self, content, bank_name):
        """Generate LLM response using orchestrator.

        Parameters
        ----------
        content : str
            Content to analyze
        bank_name : str
            Bank name for context

        Returns
        -------
        dict
            LLM response with provider information
        """
        return self.orchestrator.generate_response(
            prompt=self._build_parsing_prompt(content, bank_name),
            max_retries=1,
            temperature=0.1,
            max_tokens=4000,
        )

    def _process_parsed_data(self, parsed_data, provider):
        """Process and validate parsed credit card data.

        Parameters
        ----------
        parsed_data : list or None
            Parsed JSON data from LLM
        provider : str
            Name of provider used

        Returns
        -------
        dict
            Processed result with validation information
        """
        if not parsed_data or not isinstance(parsed_data, list):
            return self._create_empty_result(provider)

        validated_data, validation_errors = self._validate_card_data(parsed_data)
        return self._create_success_result(validated_data, provider, validation_errors)

    def _validate_card_data(self, parsed_data):
        """Validate individual credit card data entries.

        Parameters
        ----------
        parsed_data : list
            List of parsed credit card dictionaries

        Returns
        -------
        tuple
            Tuple of (validated_data, validation_errors)
        """
        validated_data = []
        validation_errors = []

        for card_data in parsed_data:
            try:
                validated_card = self.validator.sanitize_credit_card_data(card_data)
                is_valid, errors = self.validator.validate_credit_card_data(
                    validated_card
                )

                if is_valid:
                    validated_data.append(validated_card)
                else:
                    validation_errors.extend(errors)
            except Exception as e:
                validation_errors.append(f"Validation error: {str(e)}")

        return validated_data, validation_errors

    def _create_empty_result(self, provider):
        """Create result for empty or invalid parsed data.

        Parameters
        ----------
        provider : str
            Name of provider used

        Returns
        -------
        dict
            Empty result dictionary
        """
        logger.warning(f"No valid credit card data found in response from {provider}")
        return {
            "credit_cards": [],
            "provider_used": provider,
            "validation_errors": ["No valid credit card data found"],
        }

    def _create_success_result(self, validated_data, provider, validation_errors):
        """Create success result with validated data.

        Parameters
        ----------
        validated_data : list
            List of validated credit card data
        provider : str
            Name of provider used
        validation_errors : list
            List of validation error messages

        Returns
        -------
        dict
            Success result dictionary
        """
        logger.info(f"Parsed {len(validated_data)} credit cards using {provider}")
        if validation_errors:
            logger.warning(f"Validation warnings: {validation_errors}")

        return {
            "credit_cards": validated_data,
            "provider_used": provider,
            "validation_errors": validation_errors,
        }

    def _handle_provider_failures(self, error):
        """Handle all LLM provider failures.

        Parameters
        ----------
        error : AllLLMProvidersFailedError
            Error containing failure details

        Raises
        ------
        AIParsingError
            With detailed failure information
        """
        logger.error(f"All LLM providers failed: {error}")
        error_details = [
            f"{provider}: {error}" for provider, error in error.failures.items()
        ]
        raise AIParsingError(
            f"Failed to parse credit card data - all providers failed: {'; '.join(error_details)}"
        ) from error
