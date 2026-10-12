"""Signal wiring: model writes are captured into the outbox queue."""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from banks.models import Bank
from credit_cards.models import CreditCard
from search.queue import SearchIndexUpdate, dispatch, enqueue

logger = logging.getLogger(__name__)


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
    if _sync_mode() == "off":
        # ``SEARCH_SYNC_MODE=off`` disables synchronisation entirely.
        return
    enqueue(index_name, instance.pk, action)
    if _sync_mode() == "sync":
        # ``SEARCH_SYNC_MODE=sync`` drains right after the row is written.
        transaction.on_commit(lambda: dispatch())


def _sync_mode():
    """Return the configured synchronisation mode.

    Returns
    -------
    str
        ``queue``, ``sync`` or ``off``.
    """
    return getattr(settings, "SEARCH_SYNC_MODE", "queue")


@receiver(post_save, sender=Bank, dispatch_uid="search_bank_post_save")
def bank_saved(sender, instance, created, update_fields, **kwargs):
    """Queue a bank for (re)indexing after a successful commit.

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


@receiver(post_delete, sender=Bank, dispatch_uid="search_bank_post_delete")
def bank_deleted(sender, instance, **kwargs):
    """Queue a bank document for deletion after commit.

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


@receiver(post_save, sender=CreditCard, dispatch_uid="search_card_post_save")
def card_saved(sender, instance, created, update_fields, **kwargs):
    """Queue a credit card for (re)indexing after a successful commit.

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


@receiver(post_delete, sender=CreditCard, dispatch_uid="search_card_post_delete")
def card_deleted(sender, instance, **kwargs):
    """Queue a credit card document for deletion after commit.

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


def disconnect_all():
    """Disconnect every search signal handler.

    Returns
    -------
    None
    """
    receivers = [
        (post_save, bank_saved, Bank),
        (post_delete, bank_deleted, Bank),
        (post_save, card_saved, CreditCard),
        (post_delete, card_deleted, CreditCard),
    ]
    for signal, receiver_function, sender in receivers:
        signal.disconnect(receiver=receiver_function, sender=sender)
    logger.debug("Search signal handlers disconnected")
