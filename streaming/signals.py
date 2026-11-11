"""product.changed on verified CreditCard save (flag checked in apps.ready)."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from credit_cards.models import CreditCard


@receiver(post_save, sender=CreditCard, dispatch_uid="streaming_product_changed")
def _product_changed(sender, instance, created, **kw):
    try:
        from credit_cards.constants import VerificationStatus

        verified = instance.verification_status == VerificationStatus.VERIFIED
    except Exception:
        verified = str(getattr(instance, "verification_status", "")) == "verified"
    if not verified:
        return
    from streaming.outbox import emit

    payload = {
        "product_type": "credit_card",
        "product_id": instance.pk,
        "change_type": "created" if created else "updated",
        "changed_fields": [],
        "version": 1,
    }
    transaction.on_commit(
        lambda: emit(
            "creditmate.product.changed.v1",
            f"credit_card:{instance.pk}",
            payload,
            event_type="product.changed",
        )
    )
