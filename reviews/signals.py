from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_card_summary
from .models import CardReview


@receiver([post_save, post_delete], sender=CardReview)
def clear_review_summary_cache(sender, instance, **kwargs):
    invalidate_card_summary(instance.card_id)
