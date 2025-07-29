"""
Service for managing credit card data in the database.
"""

import logging
from typing import Any, Dict, Union

from credit_cards.models import CreditCard

logger = logging.getLogger(__name__)


class CreditCardDataService:
    """Service for updating credit card data in the database."""

    def update_credit_card_data(
        self, bank_id: int, parsed_data: Union[Dict[str, Any], list]
    ) -> int:
        """
        Update credit card data in the database.

        Args:
            bank_id (int): ID of the bank
            parsed_data (Union[Dict[str, Any], list]): Parsed credit card data

        Returns:
            int: Number of cards updated/created
        """
        normalized_data = self._normalize_parsed_data(parsed_data)
        updated_count = 0

        for card_data in normalized_data:
            try:
                updated_count += self._update_single_card(bank_id, card_data)
            except Exception as e:
                logger.error(f"Error updating credit card data: {str(e)}")
                continue

        return updated_count

    def _normalize_parsed_data(self, parsed_data: Union[Dict[str, Any], list]) -> list:
        """
        Normalize parsed data to a list format.

        Args:
            parsed_data (Union[Dict[str, Any], list]): Data to normalize

        Returns:
            list: Normalized data as list
        """
        if isinstance(parsed_data, list):
            return parsed_data
        elif isinstance(parsed_data, dict) and "credit_cards" in parsed_data:
            return parsed_data["credit_cards"]
        else:
            logger.warning("Parsed data is not in expected format")
            return []

    def _update_single_card(self, bank_id: int, card_data: Dict[str, Any]) -> int:
        """
        Update or create a single credit card record.

        Args:
            bank_id (int): ID of the bank
            card_data (Dict[str, Any]): Credit card data

        Returns:
            int: 1 if card was updated/created, 0 otherwise
        """
        card_name = card_data.get("name", "")
        if not card_name:
            logger.warning("Credit card name is missing, using empty string")
            card_name = ""

        card, created = CreditCard.objects.update_or_create(
            bank_id=bank_id,
            name=card_name,
            defaults=self._prepare_card_defaults(card_data),
        )

        logger.info(f"{'Created' if created else 'Updated'} credit card: {card.name}")
        return 1

    def _prepare_card_defaults(self, card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare default values for credit card creation/update.

        Args:
            card_data (Dict[str, Any]): Raw card data

        Returns:
            Dict[str, Any]: Prepared defaults for database
        """
        return {
            "annual_fee": self._parse_decimal(card_data.get("annual_fee", 0)),
            "interest_rate_apr": self._parse_decimal(
                card_data.get("interest_rate_apr", 0)
            ),
            "lounge_access_international": card_data.get(
                "lounge_access_international", 0
            ),
            "lounge_access_domestic": card_data.get("lounge_access_domestic", 0),
            "cash_advance_fee": card_data.get("cash_advance_fee", ""),
            "late_payment_fee": card_data.get("late_payment_fee", ""),
            "annual_fee_waiver_policy": card_data.get("annual_fee_waiver_policy"),
            "reward_points_policy": card_data.get("reward_points_policy", ""),
            "additional_features": card_data.get("additional_features", []),
            "is_active": True,
        }

    def _parse_decimal(self, value: Union[str, int, float]) -> float:
        """
        Parse decimal value from various formats.

        Args:
            value (Union[str, int, float]): Value to parse

        Returns:
            float: Parsed decimal value
        """
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # Remove currency symbols and percentage signs
            cleaned = value.replace("$", "").replace("%", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0

        return 0.0
