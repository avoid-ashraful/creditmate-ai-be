from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from credit_cards.models import CreditCard, CreditCardFieldHistory


TRACKED_FIELDS = {
    "annual_fee",
    "annual_fee_waiver_policy",
    "interest_rate_apr",
    "lounge_access_international",
    "lounge_access_domestic",
    "lounge_access_condition",
    "cash_advance_fee",
    "late_payment_fee",
    "reward_points_policy",
    "additional_features",
    "is_active",
}


def serialize_value(value):
    """Convert a field value to a JSON-safe representation.

    Parameters
    ----------
    value : any
        The field value to serialize

    Returns
    -------
    any
        A JSON-safe representation (handles Decimal as string to preserve precision)
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


@receiver(pre_save, sender=CreditCard)
def track_creditcard_changes(sender, instance, **kwargs):
    """Track changes to CreditCard fields before save.

    Captures the current database state before an update to detect meaningful
    field changes. Stores this in the instance for post_save processing.
    """
    if instance.pk:
        try:
            previous = CreditCard.objects.get(pk=instance.pk)
            instance._previous = previous
        except CreditCard.DoesNotExist:
            instance._previous = None
    else:
        instance._previous = None


@receiver(post_save, sender=CreditCard)
def create_creditcard_history(sender, instance, created, **kwargs):
    """Create history entries for meaningful CreditCard field changes.

    Records old/new values (JSON-safe format) with timestamp for any tracked
    field that changed. Skips creation events and no-op updates (unchanged
    tracked fields). Respects update_fields if specified during save.
    """
    if created:
        return

    previous = getattr(instance, "_previous", None)
    if not previous:
        return

    update_fields_arg = kwargs.get("update_fields")
    should_track_all = not update_fields_arg
    update_fields = set(update_fields_arg or [])

    for field_name in TRACKED_FIELDS:
        if not should_track_all and field_name not in update_fields:
            continue

        old_value = getattr(previous, field_name)
        new_value = getattr(instance, field_name)

        if old_value != new_value:
            CreditCardFieldHistory.objects.create(
                card=instance,
                field_name=field_name,
                old_value=serialize_value(old_value),
                new_value=serialize_value(new_value),
            )
