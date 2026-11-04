"""Field-history tracking for AccountProduct, mirroring deposits.signals."""

from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from bank_accounts.constants import TRACKED_PRODUCT_FIELDS
from bank_accounts.models import AccountFieldHistory, AccountProduct


def serialize_value(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


@receiver(pre_save, sender=AccountProduct)
def track_account_product_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._previous = AccountProduct.objects.get(pk=instance.pk)
        except AccountProduct.DoesNotExist:
            instance._previous = None
    else:
        instance._previous = None


@receiver(post_save, sender=AccountProduct)
def create_account_product_history(sender, instance, created, **kwargs):
    if created:
        return
    previous = getattr(instance, "_previous", None)
    if not previous:
        return
    update_fields_arg = kwargs.get("update_fields")
    should_track_all = not update_fields_arg
    update_fields = set(update_fields_arg or [])
    for field_name in TRACKED_PRODUCT_FIELDS:
        if not should_track_all and field_name not in update_fields:
            continue
        old_value = getattr(previous, field_name)
        new_value = getattr(instance, field_name)
        if old_value != new_value:
            AccountFieldHistory.objects.create(
                product=instance,
                field_name=field_name,
                old_value=serialize_value(old_value),
                new_value=serialize_value(new_value),
            )
