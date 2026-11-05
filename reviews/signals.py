from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_card_summary, invalidate_review_summary
from .models import AccountReview, CardReview, DepositReview, LoanReview


@receiver([post_save, post_delete], sender=CardReview)
def clear_review_summary_cache(sender, instance, **kwargs):
    invalidate_card_summary(instance.card_id)


@receiver([post_save, post_delete], sender=DepositReview)
def clear_deposit_summary_cache(sender, instance, **kwargs):
    invalidate_review_summary("deposit", instance.product_id)


@receiver([post_save, post_delete], sender=LoanReview)
def clear_loan_summary_cache(sender, instance, **kwargs):
    invalidate_review_summary("loan", instance.product_id)


@receiver([post_save, post_delete], sender=AccountReview)
def clear_account_summary_cache(sender, instance, **kwargs):
    invalidate_review_summary("account", instance.product_id)
