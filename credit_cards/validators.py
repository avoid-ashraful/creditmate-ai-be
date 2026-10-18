"""Validators for the structured reward data stored on credit cards."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

#: Reward categories the reward calculator understands.
REWARD_CATEGORIES = (
    "all",
    "dining",
    "travel",
    "groceries",
    "fuel",
    "online",
    "international",
    "other",
)


def _positive_number(value, label):
    """Return ``value`` as a positive Decimal or raise ``ValidationError``.

    Parameters
    ----------
    value : any
        Raw number from the stored JSON rule.
    label : str
        Field name used in the validation message.

    Returns
    -------
    decimal.Decimal
        The parsed value, which is greater than zero.
    """
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a number greater than 0.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"{label} must be a number greater than 0.") from None
    if not number.is_finite() or number <= 0:
        raise ValidationError(f"{label} must be a number greater than 0.")
    return number


def _validate_rule_list(value, number_field, label):
    """Validate a list of reward rules and their shared structure.

    Parameters
    ----------
    value : any
        Stored JSON value for an earn or cashback rule list.
    number_field : str
        Rule key holding the positive number to validate.
    label : str
        Human readable name of the rule list.

    Returns
    -------
    None
        Raises ``ValidationError`` when the list or a rule is invalid.
    """
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list of rule objects.")
    for index, rule in enumerate(value):
        prefix = f"{label}[{index}]"
        if not isinstance(rule, dict):
            raise ValidationError(f"{prefix} must be an object.")
        category = rule.get("category")
        if category not in REWARD_CATEGORIES:
            raise ValidationError(
                f"{prefix} category must be one of "
                f"{', '.join(REWARD_CATEGORIES)}; got {category!r}."
            )
        if number_field not in rule:
            raise ValidationError(f"{prefix} needs {number_field}.")
        _positive_number(rule.get(number_field), f"{prefix} {number_field}")
        text = rule.get("text")
        if text is not None and not isinstance(text, str):
            raise ValidationError(f"{prefix} text must be a string.")


def validate_earn_rules(value):
    """Validate the structured earn-rule list.

    Parameters
    ----------
    value : list of dict
        Each rule needs a valid ``category``, a positive ``points_per_unit``
        and a positive ``spend_unit_bdt``. Extra keys are kept unchanged.

    Returns
    -------
    None
        Raises ``ValidationError`` when the structure is invalid.
    """
    _validate_rule_list(value, "points_per_unit", "reward_earn_rules")
    for index, rule in enumerate(value):
        if "spend_unit_bdt" not in rule:
            raise ValidationError(f"reward_earn_rules[{index}] needs spend_unit_bdt.")
        _positive_number(
            rule.get("spend_unit_bdt"),
            f"reward_earn_rules[{index}] spend_unit_bdt",
        )


def validate_cashback_rules(value):
    """Validate the structured cashback-rule list.

    Parameters
    ----------
    value : list of dict
        Each rule needs a valid ``category`` and a positive ``percent``.
        Extra keys are kept unchanged.

    Returns
    -------
    None
        Raises ``ValidationError`` when the structure is invalid.
    """
    _validate_rule_list(value, "percent", "cashback_rules")
