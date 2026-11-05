"""The bank-follow change feed (redesign Phase 3, D4).

"What changed at the banks you follow": field-history events from all
four verticals, restricted to banks the user follows, newest first. The
feed reads the same history rows the public detail-page timelines show —
nothing is recomputed or invented here, and a bank with no recorded
changes simply contributes no items (the client renders an honest
"no changes yet" state).
"""

from bank_accounts.models import AccountFieldHistory
from credit_cards.models import CreditCardFieldHistory
from deposits.models import DepositFieldHistory
from loans.models import LoanFieldHistory

# (vertical, history model, product relation name, bank relation path)
_FEED_SOURCES = (
    ("cards", CreditCardFieldHistory, "card", "card__bank"),
    ("deposits", DepositFieldHistory, "product", "product__bank"),
    ("loans", LoanFieldHistory, "product", "product__bank"),
    ("accounts", AccountFieldHistory, "product", "product__bank"),
)


def _product_key(vertical, product):
    if vertical == "cards":
        return str(product.pk)
    return product.slug


def _bank_name(vertical, product):
    if vertical == "deposits":
        return product.institution_display_name
    if vertical == "loans":
        return product.lender_display_name
    return product.bank.name


def _entry(vertical, row, product):
    bank = product.bank
    return {
        "id": f"{vertical}:{row.pk}",
        "vertical": vertical,
        "product_name": product.name,
        "product_key": _product_key(vertical, product),
        "bank_id": bank.pk if bank else None,
        "bank_name": _bank_name(vertical, product),
        "field_name": row.field_name,
        "old_value": row.old_value,
        "new_value": row.new_value,
        # Only the loans history records a free-text source; the others
        # carry none, and the feed never fabricates one.
        "source": getattr(row, "source", "") or None,
        "changed_at": row.created,
    }


def build_follow_feed(user, page=1, page_size=20):
    """Return (entries, has_more) for the user's followed banks.

    Pagination is honest offset pagination over the merged stream: each
    source is probed one row past the requested window, so ``has_more``
    is exact for the fetched window without inventing a total count.
    """
    bank_ids = list(user.bank_follows.values_list("bank_id", flat=True))
    if not bank_ids:
        return [], False

    offset = (page - 1) * page_size
    probe = offset + page_size + 1
    merged = []
    for vertical, model, relation, bank_path in _FEED_SOURCES:
        rows = (
            model.objects.filter(**{f"{bank_path}__in": bank_ids})
            .select_related(relation, f"{relation}__bank")
            .order_by("-created", "-id")[:probe]
        )
        for row in rows:
            entry = _entry(vertical, row, getattr(row, relation))
            merged.append((entry["changed_at"], row.pk, vertical, entry))
    merged.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    entries = [item[3] for item in merged]
    has_more = len(entries) > offset + page_size
    return entries[offset : offset + page_size], has_more
