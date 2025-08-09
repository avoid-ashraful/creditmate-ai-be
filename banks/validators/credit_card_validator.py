"""Data validation layer for credit card data."""

import logging
from typing import Any, Dict, List, Tuple, Union

logger = logging.getLogger(__name__)


class CreditCardDataValidator:
    """Validate parsed credit card data before saving to database."""

    @staticmethod
    def validate_credit_card_data(
        data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> Tuple[bool, List[str]]:
        """
        Validate credit card data structure and values.

        Args:
            data (Union[Dict[str, Any], List[Dict[str, Any]]]): Single card dict or list of card dicts

        Returns:
            Tuple[bool, List[str]]: Tuple of (is_valid, list_of_errors)
        """
        errors = []
        cards_data = CreditCardDataValidator._normalize_data_for_validation(data, errors)

        if not cards_data or errors:
            return False, errors

        # Validate each card
        for i, card_data in enumerate(cards_data):
            card_errors = CreditCardDataValidator._validate_single_card(card_data, i)
            errors.extend(card_errors)

        return len(errors) == 0, errors

    @staticmethod
    def _normalize_data_for_validation(
        data: Union[Dict[str, Any], List[Dict[str, Any]]], errors: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Normalize data format for validation.

        Args:
            data (Union[Dict[str, Any], List[Dict[str, Any]]]): Data to normalize
            errors (List[str]): Error list to append to

        Returns:
            List[Dict[str, Any]]: Normalized card data list
        """
        # Handle both single dict and list formats
        if isinstance(data, dict):
            if "credit_cards" in data:
                cards_data = data["credit_cards"]
            elif "raw_parsed_content" in data:
                errors.append(
                    "Data contains raw content, not structured credit card data"
                )
                return []
            else:
                cards_data = [data]  # Single card
        elif isinstance(data, list):
            cards_data = data
        else:
            errors.append("Invalid data format: expected dict or list")
            return []

        if not cards_data:
            errors.append("No credit card data found")
            return []

        return cards_data

    @staticmethod
    def _validate_single_card(card_data: Dict[str, Any], index: int) -> List[str]:
        """
        Validate a single credit card data dict.

        Args:
            card_data (Dict[str, Any]): Single card data to validate
            index (int): Index of card for error reporting

        Returns:
            List[str]: List of validation errors
        """
        errors = []
        prefix = f"Card {index + 1}: "

        if not isinstance(card_data, dict):
            errors.append(f"{prefix}Invalid card data format")
            return errors

        # Validate required and string fields
        errors.extend(CreditCardDataValidator._validate_string_fields(card_data, prefix))

        # Validate numeric fields
        errors.extend(CreditCardDataValidator._validate_numeric_fields(card_data, prefix))

        # Validate JSON fields
        errors.extend(CreditCardDataValidator._validate_json_fields(card_data, prefix))

        return errors

    @staticmethod
    def _validate_string_fields(card_data: Dict[str, Any], prefix: str) -> List[str]:
        """
        Validate string fields.

        Args:
            card_data (Dict[str, Any]): Card data
            prefix (str): Error message prefix

        Returns:
            List[str]: Validation errors
        """
        errors = []

        # Required name field
        name = card_data.get("name", "").strip()
        if not name:
            errors.append(f"{prefix}Credit card name is required")
        elif len(name) > 255:
            errors.append(f"{prefix}Credit card name too long (max 255 characters)")

        # Text fields length validation
        text_fields = ["cash_advance_fee", "late_payment_fee", "reward_points_policy"]
        for field in text_fields:
            value = card_data.get(field, "")
            if isinstance(value, str) and len(value) > 1000:
                errors.append(f"{prefix}{field} is too long (max 1000 characters)")

        return errors

    @staticmethod
    def _validate_numeric_fields(card_data: Dict[str, Any], prefix: str) -> List[str]:
        """
        Validate numeric fields.

        Args:
            card_data (Dict[str, Any]): Card data
            prefix (str): Error message prefix

        Returns:
            List[str]: Validation errors
        """
        errors = []

        # Annual fee validation
        annual_fee = card_data.get("annual_fee")
        if annual_fee is not None:
            fee_errors = CreditCardDataValidator._validate_annual_fee(annual_fee, prefix)
            errors.extend(fee_errors)

        # Interest rate validation
        interest_rate = card_data.get("interest_rate_apr")
        if interest_rate is not None:
            rate_errors = CreditCardDataValidator._validate_interest_rate(
                interest_rate, prefix
            )
            errors.extend(rate_errors)

        # Lounge access string validation
        lounge_fields = ["lounge_access_international", "lounge_access_domestic"]
        for field in lounge_fields:
            value = card_data.get(field)
            if value is not None and not isinstance(value, str) and value != "":
                errors.append(f"{prefix}Invalid {field} format: {value}")
            elif isinstance(value, str) and len(value) > 255:
                errors.append(f"{prefix}{field} is too long (max 255 characters)")

        return errors

    @staticmethod
    def _validate_annual_fee(annual_fee: Any, prefix: str) -> List[str]:
        """
        Validate annual fee value.

        Args:
            annual_fee (Any): Fee value to validate
            prefix (str): Error message prefix

        Returns:
            List[str]: Validation errors
        """
        errors = []
        try:
            fee_value = float(annual_fee)
            if fee_value < 0:
                errors.append(f"{prefix}Annual fee cannot be negative")
            elif fee_value > 100000:  # Reasonable upper limit
                errors.append(f"{prefix}Annual fee seems unusually high: ${fee_value}")
        except (ValueError, TypeError):
            errors.append(f"{prefix}Invalid annual fee format: {annual_fee}")
        return errors

    @staticmethod
    def _validate_interest_rate(interest_rate: Any, prefix: str) -> List[str]:
        """
        Validate interest rate value.

        Args:
            interest_rate (Any): Rate value to validate
            prefix (str): Error message prefix

        Returns:
            List[str]: validation errors
        """
        errors = []
        try:
            rate_value = float(interest_rate)
            if rate_value < 0:
                errors.append(f"{prefix}Interest rate cannot be negative")
            elif rate_value > 100:
                errors.append(
                    f"{prefix}Interest rate seems unusually high: {rate_value}%"
                )
        except (ValueError, TypeError):
            errors.append(f"{prefix}Invalid interest rate format: {interest_rate}")
        return errors

    @staticmethod
    def _validate_json_fields(card_data: Dict[str, Any], prefix: str) -> List[str]:
        """
        Validate JSON fields.

        Args:
            card_data (Dict[str, Any]): Card data
            prefix (str): Error message prefix

        Returns:
            List[str]: Validation errors
        """
        errors = []

        # Additional features should be a list (but accept null)
        additional_features = card_data.get("additional_features")
        if additional_features is not None and not isinstance(additional_features, list):
            # Allow conversion of non-list to list
            logger.warning(
                f"{prefix}additional_features is not a list, will be converted during sanitization"
            )

        # Annual fee waiver policy should be a dict or string or null
        waiver_policy = card_data.get("annual_fee_waiver_policy")
        if waiver_policy is not None and not isinstance(waiver_policy, (dict, str)):
            errors.append(
                f"{prefix}annual_fee_waiver_policy should be a dictionary, string, or null"
            )

        return errors

    @staticmethod
    def sanitize_credit_card_data(
        data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Sanitize and normalize credit card data.

        Args:
            data (Union[Dict[str, Any], List[Dict[str, Any]]]): Credit card data to sanitize

        Returns:
            Union[Dict[str, Any], List[Dict[str, Any]]]: Sanitized data
        """
        # Handle both single dict and list formats
        if isinstance(data, dict):
            if "credit_cards" in data:
                cards_data = data["credit_cards"]
                data["credit_cards"] = [
                    CreditCardDataValidator._sanitize_single_card(card)
                    for card in cards_data
                ]
                return data
            else:
                return CreditCardDataValidator._sanitize_single_card(data)
        elif isinstance(data, list):
            return [CreditCardDataValidator._sanitize_single_card(card) for card in data]

        return data

    @staticmethod
    def _sanitize_single_card(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize a single credit card data dict.

        Args:
            card_data (Dict[str, Any]): Card data to sanitize

        Returns:
            Dict[str, Any]: Sanitized card data
        """
        sanitized = {}

        # Clean string fields
        sanitized.update(CreditCardDataValidator._sanitize_string_fields(card_data))

        # Clean numeric fields
        sanitized.update(CreditCardDataValidator._sanitize_numeric_fields(card_data))

        # Clean JSON fields
        sanitized.update(CreditCardDataValidator._sanitize_json_fields(card_data))

        return sanitized

    @staticmethod
    def _sanitize_string_fields(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize string fields.

        Args:
            card_data (Dict[str, Any]): Card data

        Returns:
            Dict[str, Any]: Sanitized string fields
        """
        sanitized = {}
        string_fields = [
            "name",
            "cash_advance_fee",
            "late_payment_fee",
            "reward_points_policy",
            "lounge_access_international",
            "lounge_access_domestic",
        ]

        for field in string_fields:
            value = card_data.get(field, "")
            if isinstance(value, str):
                sanitized[field] = value.strip()[:1000]  # Trim and limit length
            else:
                sanitized[field] = str(value).strip()[:1000] if value is not None else ""

        return sanitized

    @staticmethod
    def _sanitize_numeric_fields(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize numeric fields.

        Args:
            card_data (Dict[str, Any]): Card data

        Returns:
            Dict[str, Any]: Sanitized numeric fields
        """
        sanitized = {}
        numeric_fields = [
            "annual_fee",
            "interest_rate_apr",
        ]

        for field in numeric_fields:
            value = card_data.get(field)
            if value is not None:
                try:
                    sanitized[field] = max(0, float(value))
                except (ValueError, TypeError):
                    sanitized[field] = 0
            else:
                sanitized[field] = 0

        return sanitized

    @staticmethod
    def _sanitize_json_fields(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize JSON fields.

        Args:
            card_data (Dict[str, Any]): Card data

        Returns:
            Dict[str, Any]: Sanitized JSON fields
        """
        sanitized = {}

        # Annual fee waiver policy
        annual_fee_waiver = card_data.get("annual_fee_waiver_policy")
        if isinstance(annual_fee_waiver, dict):
            sanitized["annual_fee_waiver_policy"] = annual_fee_waiver
        elif isinstance(annual_fee_waiver, str) and annual_fee_waiver.strip():
            sanitized["annual_fee_waiver_policy"] = {
                "description": annual_fee_waiver.strip()
            }
        else:
            sanitized["annual_fee_waiver_policy"] = None

        # Additional features
        additional_features = card_data.get("additional_features")
        if isinstance(additional_features, list):
            sanitized["additional_features"] = [
                str(feature).strip() for feature in additional_features if feature
            ]
        else:
            sanitized["additional_features"] = []

        return sanitized
