from django.core.cache import cache


def review_summary_key(product_type, product_id):
    """Cache key for a product-type review summary.

    Cards keep their historical key (``reviews:summary:card:<id>``) — the
    generalised types use the same scheme, so this one helper serves all.
    """
    return f"reviews:summary:{product_type}:{product_id}"


def invalidate_review_summary(product_type, product_id):
    cache.delete(review_summary_key(product_type, product_id))


def invalidate_card_summary(card_id):
    invalidate_review_summary("card", card_id)
