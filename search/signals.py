"""Signal wiring: model writes are captured into the outbox queue.

Only model writes that actually change an indexed value are queued, including
the denormalised values that live in the *other* index:

* a card document stores ``bank_name``, so renaming a bank must refresh every
  card document of that bank;
* a bank document stores ``credit_card_count`` (active cards), so creating,
  deleting, activating or moving a card must refresh the affected banks.

Previous values are read in ``pre_save`` (before the UPDATE lands) and used in
``post_save``/``post_delete``.  Every row still goes through
``transaction.on_commit``, so a rolled back transaction queues nothing and
rows keep their transaction order.

Receiving a row is *not* the same as writing it to the engine.  With the
default ``SEARCH_SYNC_MODE=queue`` a save only appends the row: the periodic
Celery beat entry ``search-index-queue-drain`` (``credit_mate_ai/celery.py``)
publishes ``search.process_index_queue`` on a worker every
``SEARCH_QUEUE_DRAIN_INTERVAL`` seconds, and that drain turns the row into an
index update.  No broker call and no engine call ever happens inside a model
save by default.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from banks.models import Bank
from credit_cards.models import CreditCard
from search.queue import SearchIndexUpdate, dispatch, enqueue

logger = logging.getLogger(__name__)

#: Bank columns copied into credit card documents.
BANK_FIELDS_IN_CARD_DOCUMENT = ("name",)

#: Card columns that change the active card count stored on bank documents.
CARD_FIELDS_IN_BANK_DOCUMENT = ("bank_id", "is_active")


def _enqueue_after_commit(index_name, instance, action):
    """Queue an outbox row once the surrounding transaction commits.

    Parameters
    ----------
    index_name : str
        Target index name.
    instance : Model
        Instance being saved or deleted.
    action : str
        ``index`` or ``delete``.

    Returns
    -------
    None
    """
    _queue_after_commit(index_name, instance.pk, action)


def _queue_after_commit(index_name, object_id, action):
    """Queue an outbox row for ``object_id`` once the transaction commits.

    Parameters
    ----------
    index_name : str
        Target index name.
    object_id : int
        Primary key of the document to update.
    action : str
        ``index`` or ``delete``.

    Returns
    -------
    None
    """
    mode = _sync_mode()
    if mode == "off":
        # ``SEARCH_SYNC_MODE=off`` disables synchronisation entirely.
        return
    enqueue(index_name, object_id, action)
    if mode == "sync":
        # ``SEARCH_SYNC_MODE=sync`` drains right after the row is written
        # (blocking engine call — only used when explicitly selected).
        transaction.on_commit(lambda: dispatch())
    elif getattr(settings, "SEARCH_QUEUE_VIA_CELERY", False):
        # Default ``queue`` mode needs no per-save work at all: Celery beat
        # drains the outbox periodically.  With ``SEARCH_QUEUE_VIA_CELERY``
        # enabled we *additionally* publish a drain task after the commit for
        # lower latency; if the broker is down the row simply stays pending
        # and the beat drain handles it.
        transaction.on_commit(_dispatch_drain_after_commit)


def _dispatch_drain_after_commit():
    """Publish the opt-in Celery drain task (never drains inline)."""
    from search.tasks import dispatch_queue_drain

    dispatch_queue_drain()


def _sync_mode():
    """Return the configured synchronisation mode.

    Returns
    -------
    str
        ``queue``, ``sync`` or ``off``.
    """
    return getattr(settings, "SEARCH_SYNC_MODE", "queue")


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------


@receiver(pre_save, sender=Bank, dispatch_uid="search_bank_pre_save")
def bank_about_to_save(sender, instance, **kwargs):
    """Remember the stored bank name so a rename can be detected afterwards.

    Parameters
    ----------
    sender : type
        Model class.
    instance : Bank
        Bank about to be saved.

    Returns
    -------
    None
    """
    if _sync_mode() == "off" or instance._state.adding or instance.pk is None:
        instance._search_previous_name = None
        return
    instance._search_previous_name = (
        Bank.objects.filter(pk=instance.pk).values_list("name", flat=True).first()
    )


@receiver(post_save, sender=Bank, dispatch_uid="search_bank_post_save")
def bank_saved(sender, instance, created, update_fields, **kwargs):
    """Queue a bank, and its cards when a denormalised field changed.

    Parameters
    ----------
    sender : type
        Model class.
    instance : Bank
        Saved bank.
    created : bool
        True when the row was inserted.
    update_fields : list | None
        Fields passed to ``save(update_fields=...)``.

    Returns
    -------
    None
    """
    logger.debug("Bank %s saved, queuing index row", instance.pk)
    _enqueue_after_commit(
        SearchIndexUpdate.INDEX_BANKS, instance, SearchIndexUpdate.ACTION_INDEX
    )
    previous_name = getattr(instance, "_search_previous_name", None)
    if created or previous_name is None or previous_name == instance.name:
        # Nothing that the card documents copy has changed.
        return
    _queue_related_cards(instance)


def _queue_related_cards(bank):
    """Queue every card document that denormalises this bank's metadata.

    Parameters
    ----------
    bank : Bank
        Bank whose name changed.

    Returns
    -------
    None
    """
    card_ids = list(CreditCard.objects.filter(bank=bank).values_list("pk", flat=True))
    for card_id in card_ids:
        _queue_after_commit(
            SearchIndexUpdate.INDEX_CREDIT_CARDS, card_id, SearchIndexUpdate.ACTION_INDEX
        )
    if card_ids:
        logger.debug("Bank %s rename queued %s card documents", bank.pk, len(card_ids))


@receiver(post_delete, sender=Bank, dispatch_uid="search_bank_post_delete")
def bank_deleted(sender, instance, **kwargs):
    """Queue a bank document for deletion after commit.

    Card documents are covered by the cascading ``CreditCard`` delete
    receivers, which also queue this bank because its card count changed.

    Parameters
    ----------
    sender : type
        Model class.
    instance : Bank
        Deleted bank.

    Returns
    -------
    None
    """
    logger.debug("Bank %s deleted, queuing delete row", instance.pk)
    _enqueue_after_commit(
        SearchIndexUpdate.INDEX_BANKS, instance, SearchIndexUpdate.ACTION_DELETE
    )


# ---------------------------------------------------------------------------
# Credit card
# ---------------------------------------------------------------------------


@receiver(pre_save, sender=CreditCard, dispatch_uid="search_card_pre_save")
def card_about_to_save(sender, instance, **kwargs):
    """Remember the stored bank and activation state of a card.

    Parameters
    ----------
    sender : type
        Model class.
    instance : CreditCard
        Card about to be saved.

    Returns
    -------
    None
    """
    if _sync_mode() == "off" or instance._state.adding or instance.pk is None:
        instance._search_previous = None
        return
    instance._search_previous = (
        CreditCard.objects.filter(pk=instance.pk)
        .values(*CARD_FIELDS_IN_BANK_DOCUMENT)
        .first()
    )


def _banks_affected_by_card(instance):
    """Return the bank ids whose card count may have changed.

    Parameters
    ----------
    instance : CreditCard
        Saved or deleted card.

    Returns
    -------
    set of int
        Bank primary keys to reindex.
    """
    previous = getattr(instance, "_search_previous", None)
    if previous is None:
        # New card: the current bank gains a card.
        return {instance.bank_id} if instance.bank_id else set()
    affected = set()
    if previous["bank_id"] != instance.bank_id:
        # Card moved: both the old and the new bank change.
        affected.update({previous["bank_id"], instance.bank_id})
    if previous["is_active"] != instance.is_active:
        affected.add(instance.bank_id)
    return {bank_id for bank_id in affected if bank_id}


def _queue_related_banks(instance, action=SearchIndexUpdate.ACTION_INDEX):
    """Queue every bank document affected by a card write.

    Parameters
    ----------
    instance : CreditCard
        Saved or deleted card.
    action : str
        ``index`` or ``delete``.

    Returns
    -------
    None
    """
    for bank_id in _banks_affected_by_card(instance):
        _queue_after_commit(SearchIndexUpdate.INDEX_BANKS, bank_id, action)


@receiver(post_save, sender=CreditCard, dispatch_uid="search_card_post_save")
def card_saved(sender, instance, created, update_fields, **kwargs):
    """Queue a card, plus the banks whose stored card count changed.

    Parameters
    ----------
    sender : type
        Model class.
    instance : CreditCard
        Saved card.
    created : bool
        True when the row was inserted.
    update_fields : list | None
        Fields passed to ``save(update_fields=...)``.

    Returns
    -------
    None
    """
    logger.debug("Credit card %s saved, queuing index row", instance.pk)
    _enqueue_after_commit(
        SearchIndexUpdate.INDEX_CREDIT_CARDS, instance, SearchIndexUpdate.ACTION_INDEX
    )
    _queue_related_banks(instance)


@receiver(post_delete, sender=CreditCard, dispatch_uid="search_card_post_delete")
def card_deleted(sender, instance, **kwargs):
    """Queue a card deletion, and its bank because the card count changed.

    Parameters
    ----------
    sender : type
        Model class.
    instance : CreditCard
        Deleted card.

    Returns
    -------
    None
    """
    logger.debug("Credit card %s deleted, queuing delete row", instance.pk)
    _enqueue_after_commit(
        SearchIndexUpdate.INDEX_CREDIT_CARDS, instance, SearchIndexUpdate.ACTION_DELETE
    )
    # The card is gone, so its bank loses a card.  ``post_delete`` runs before
    # the pk is cleared, so ``bank_id`` is still valid here.  When the bank
    # itself is being deleted (cascade), the bank delete row below supersedes
    # this index row.
    if instance.bank_id:
        _queue_after_commit(
            SearchIndexUpdate.INDEX_BANKS,
            instance.bank_id,
            SearchIndexUpdate.ACTION_INDEX,
        )


def disconnect_all():
    """Disconnect every search signal handler.

    Returns
    -------
    None
    """
    receivers = [
        (pre_save, bank_about_to_save, Bank),
        (post_save, bank_saved, Bank),
        (post_delete, bank_deleted, Bank),
        (pre_save, card_about_to_save, CreditCard),
        (post_save, card_saved, CreditCard),
        (post_delete, card_deleted, CreditCard),
    ]
    for signal, receiver_function, sender in receivers:
        signal.disconnect(receiver=receiver_function, sender=sender)
    logger.debug("Search signal handlers disconnected")
