"""
Service for managing credit card data in the database.
"""

import logging

from credit_cards.models import CreditCard

logger = logging.getLogger(__name__)


class CreditCardDataService:
    """Service for updating credit card data in the database.

    This service handles the conversion of parsed credit card data from
    various sources into database records, including data normalization,
    validation, and creation/update operations.
    """

    def update_credit_card_data(self, bank_id, parsed_data):
        """Update credit card data in the database.

        Parameters
        ----------
        bank_id : int
            ID of the bank to associate credit cards with
        parsed_data : dict or list
            Parsed credit card data from LLM processing, can be single
            card dict or list of card dicts

        Returns
        -------
        int
            Number of credit cards successfully updated or created
        """
        logger.info(f"Raw parsed data received for bank {bank_id}: {parsed_data}")
        normalized_data = self._normalize_parsed_data(parsed_data)
        logger.info(f"Normalized data: {normalized_data}")
        updated_count = 0

        logger.info(f"Processing {len(normalized_data)} credit cards for bank {bank_id}")
        for i, card_data in enumerate(normalized_data):
            try:
                logger.info(f"Processing card {i+1}: {card_data}")
                updated_count += self._update_single_card(bank_id, card_data)
            except Exception as e:
                logger.error(f"Error updating credit card data: {str(e)}")
                continue

        logger.info(f"Total cards processed: {updated_count}")
        return updated_count

    def _normalize_parsed_data(self, parsed_data):
        """Normalize parsed data to a list format.

        Parameters
        ----------
        parsed_data : dict or list
            Raw parsed data that may be in various formats

        Returns
        -------
        list
            Normalized list of credit card data dictionaries
        """
        if isinstance(parsed_data, list):
            return parsed_data
        elif isinstance(parsed_data, dict):
            # Handle validation error structure: {"validation_errors": [...], "data": [...]}
            if "data" in parsed_data:
                logger.info("Processing data despite validation warnings")
                data_to_process = parsed_data["data"]
                if isinstance(data_to_process, list):
                    return data_to_process
                else:
                    return self._normalize_parsed_data(data_to_process)
            # Handle standard structure: {"credit_cards": [...]}
            elif "credit_cards" in parsed_data:
                return parsed_data["credit_cards"]
            else:
                logger.warning("Parsed data dict does not contain expected keys")
                return []
        else:
            logger.warning("Parsed data is not in expected format")
            return []

    def _update_single_card(self, bank_id, card_data):
        """Update or create a single credit card record.

        Parameters
        ----------
        bank_id : int
            ID of the bank to associate the card with
        card_data : dict
            Dictionary containing credit card information and attributes

        Returns
        -------
        int
            1 if card was successfully updated or created, 0 otherwise
        """
        card_name = card_data.get("name", "").strip()
        if not card_name:
            # Create fallback name from annual fee
            annual_fee = card_data.get("annual_fee", 0)
            card_name = f"Credit Card (Annual Fee: {annual_fee})"
            logger.warning(f"Credit card name is missing, using fallback: {card_name}")
        # Clean up card name if it's just the annual fee
        elif (
            card_name.startswith("TK.")
            or card_name.startswith("US$")
            or card_name.replace(",", "").replace(".", "").isdigit()
        ):
            annual_fee = card_data.get("annual_fee", 0)
            card_name = f"Credit Card (Annual Fee: {annual_fee})"
            logger.info(f"Cleaned up card name from fee to: {card_name}")

        try:
            defaults = self._prepare_card_defaults(card_data)
            logger.info(
                f"Creating/updating card '{card_name}' for bank {bank_id} with defaults: {defaults}"
            )

            card, created = CreditCard.objects.update_or_create(
                bank_id=bank_id,
                name=card_name,
                defaults=defaults,
            )

            logger.info(
                f"{'Created' if created else 'Updated'} credit card: {card.name} (ID: {card.id})"
            )
            return 1
        except Exception as e:
            logger.error(f"Failed to create/update credit card '{card_name}': {str(e)}")
            raise

    def _prepare_card_defaults(self, card_data):
        """Prepare default values for credit card creation/update.

        Parameters
        ----------
        card_data : dict
            Raw credit card data from parsing

        Returns
        -------
        dict
            Prepared defaults dictionary for database operations
        """
        return {
            "annual_fee": self._parse_decimal(card_data.get("annual_fee", 0)),
            "interest_rate_apr": self._parse_decimal(
                card_data.get("interest_rate_apr", 0)
            ),
            "lounge_access_international": card_data.get(
                "lounge_access_international", ""
            ),
            "lounge_access_domestic": card_data.get("lounge_access_domestic", ""),
            "cash_advance_fee": card_data.get("cash_advance_fee", ""),
            "late_payment_fee": card_data.get("late_payment_fee", ""),
            "annual_fee_waiver_policy": card_data.get("annual_fee_waiver_policy"),
            "reward_points_policy": card_data.get("reward_points_policy", ""),
            "additional_features": card_data.get("additional_features", []),
            "is_active": True,
        }

    def _parse_decimal(self, value):
        """Parse decimal value from various formats.

        Parameters
        ----------
        value : str, int, or float
            Value to parse, may contain currency symbols or percentages

        Returns
        -------
        float
            Parsed decimal value, defaults to 0.0 for invalid inputs
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
