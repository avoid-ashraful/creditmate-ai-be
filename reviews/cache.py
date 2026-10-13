from django.core.cache import cache


def invalidate_card_summary(card_id):
    cache.delete(f"reviews:summary:card:{card_id}")
