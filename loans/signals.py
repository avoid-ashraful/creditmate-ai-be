"""Field-history signals for loan products (mirrors deposits.signals)."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import TRACKED_FIELDS, LoanFieldHistory, LoanProduct

_SNAPSHOT_ATTR = "_pre_save_snapshot"


@receiver(pre_save, sender=LoanProduct)
def snapshot_loan_product(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = LoanProduct.objects.get(pk=instance.pk)
        except LoanProduct.DoesNotExist:
            return
        setattr(
            instance,
            _SNAPSHOT_ATTR,
            {field: getattr(old, field) for field in TRACKED_FIELDS},
        )


@receiver(post_save, sender=LoanProduct)
def record_loan_field_history(sender, instance, created, **kwargs):
    snapshot = getattr(instance, _SNAPSHOT_ATTR, None)
    if created or not snapshot:
        return
    rows = []
    for field in TRACKED_FIELDS:
        old_value = snapshot.get(field)
        new_value = getattr(instance, field)
        if str(old_value) != str(new_value):
            rows.append(
                LoanFieldHistory(
                    product=instance,
                    field_name=field,
                    old_value="" if old_value is None else str(old_value),
                    new_value="" if new_value is None else str(new_value),
                    source="signal",
                )
            )
    if rows:
        LoanFieldHistory.objects.bulk_create(rows)
