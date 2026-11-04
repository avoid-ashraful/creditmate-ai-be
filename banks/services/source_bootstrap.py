"""Bootstrap the BankDataSource registry for the nightly product sync.

A fresh deployment used to crawl *nothing*: the seed data created zero
``BankDataSource`` rows, so sources only appeared through the monthly
LLM-driven discovery task or manual admin work. This module registers the
sources the four product verticals actually use, deriving the list from
provenance already stored in the codebase:

* the two Bangladesh Bank rate charts (deposit + lending) — attached to an
  inactive ``Bangladesh Bank`` registry bank, parsed deterministically by
  the deposits/loans ingestions and never fed to the LLM pipeline;
* every bank's published Schedule of Charges (``Bank.schedule_charge_url``)
  as the credit-card crawl source;
* the per-bank source URLs recorded on the seeded catalogues:
  ``AccountProduct.source_soc_url`` / ``source_rate_url`` (accounts),
  ``DepositProduct.source_url`` (deposits) and ``LoanProduct.source_url``
  (loans). Those are *watched* sources: the nightly sync change-checks them
  and flags changes for human review.

The function is idempotent — rows are keyed by ``(bank, url)`` and existing
rows keep their purpose (a URL shared by two verticals stays registered
once, under the first purpose that claimed it, and is reported as shared).
"""

import logging
from urllib.parse import urlsplit

from django.db import transaction

from banks.enums import ContentType, SourcePurpose
from banks.models import Bank, BankDataSource

logger = logging.getLogger(__name__)

BB_BANK_NAME = "Bangladesh Bank"
BB_WEBSITE = "https://www.bb.org.bd"


def _content_type_for(url):
    """Guess the BankDataSource content type from the URL suffix."""
    return (
        ContentType.PDF
        if urlsplit(url).path.lower().endswith(".pdf")
        else ContentType.WEBPAGE
    )


def _register(bank, url, purpose, description, counts):
    """Create the (bank, url) source row unless it already exists."""
    url = (url or "").strip()
    if bank is None or not url:
        return
    existing, created = BankDataSource.objects.get_or_create(
        bank=bank,
        url=url,
        defaults={
            "content_type": _content_type_for(url),
            "purpose": purpose,
            "description": description,
            "is_active": True,
        },
    )
    if created:
        counts["created"] += 1
        counts["by_purpose"][purpose.value] = (
            counts["by_purpose"].get(purpose.value, 0) + 1
        )
    else:
        counts["existing"] += 1
        if existing.purpose != purpose:
            counts["shared"] += 1


@transaction.atomic
def bootstrap_sync_sources():
    """Register every source the nightly sync needs. Returns count summary.

    Returns
    -------
    dict
        Counts with keys 'created', 'existing', 'shared' (rows already
        registered under a different purpose), 'by_purpose' (created rows
        per purpose value) and 'total_active_sources'.
    """
    counts = {"created": 0, "existing": 0, "shared": 0, "by_purpose": {}}

    _register_bb_charts(counts)
    _register_card_soc_sources(counts)
    _register_account_sources(counts)
    _register_deposit_sources(counts)
    _register_loan_sources(counts)

    counts["total_active_sources"] = BankDataSource.objects.filter(is_active=True).count()
    logger.info("Sync source bootstrap: %s", counts)
    return counts


def _register_bb_charts(counts):
    """Register the Bangladesh Bank charts under an inactive registry bank."""
    from deposits.constants import BB_DEPOSIT_CHART_URLS
    from loans.ingestion.bb_lending_chart import CHART_URL as LENDING_CHART_URL

    bb_bank, _ = Bank.objects.get_or_create(
        name=BB_BANK_NAME,
        defaults={"website": BB_WEBSITE, "is_active": False},
    )
    for url in BB_DEPOSIT_CHART_URLS.values():
        _register(
            bb_bank,
            url,
            SourcePurpose.BB_DEPOSIT_CHART,
            "Bangladesh Bank announced deposit-rate chart (deterministic nightly parse)",
            counts,
        )
    _register(
        bb_bank,
        LENDING_CHART_URL,
        SourcePurpose.BB_LENDING_CHART,
        "Bangladesh Bank announced lending-rate chart (deterministic nightly parse)",
        counts,
    )


def _register_card_soc_sources(counts):
    """Register each bank's published Schedule of Charges as its card source."""
    banks = (
        Bank.objects.filter(is_active=True)
        .exclude(schedule_charge_url__isnull=True)
        .exclude(schedule_charge_url="")
    )
    for bank in banks:
        _register(
            bank,
            bank.schedule_charge_url,
            SourcePurpose.CREDIT_CARD,
            "Schedule of charges (registered by sync source bootstrap)",
            counts,
        )


def _register_account_sources(counts):
    """Harvest the account catalogue's SOC / rate-sheet provenance URLs."""
    from bank_accounts.models import AccountProduct

    soc_pairs = (
        AccountProduct.objects.filter(bank__isnull=False)
        .exclude(source_soc_url="")
        .values_list("bank_id", "source_soc_url")
        .distinct()
    )
    for bank_id, url in soc_pairs:
        _register(
            Bank.objects.get(pk=bank_id),
            url,
            SourcePurpose.ACCOUNT_SOC,
            "Account schedule of charges (account catalogue provenance)",
            counts,
        )
    rate_pairs = (
        AccountProduct.objects.filter(bank__isnull=False)
        .exclude(source_rate_url="")
        .values_list("bank_id", "source_rate_url")
        .distinct()
    )
    for bank_id, url in rate_pairs:
        _register(
            Bank.objects.get(pk=bank_id),
            url,
            SourcePurpose.ACCOUNT_RATES,
            "Account rate sheet (account catalogue provenance)",
            counts,
        )


def _register_deposit_sources(counts):
    """Harvest the deposit catalogue's bank rate-sheet / product-page URLs."""
    from deposits.constants import SourceKind
    from deposits.models import DepositProduct

    pairs = (
        DepositProduct.objects.filter(bank__isnull=False)
        .exclude(source_url="")
        .exclude(source_kind__in=[SourceKind.BB_CHART, SourceKind.NSD])
        .values_list("bank_id", "source_url")
        .distinct()
    )
    for bank_id, url in pairs:
        _register(
            Bank.objects.get(pk=bank_id),
            url,
            SourcePurpose.DEPOSIT_RATES,
            "Deposit rate sheet / product page (deposit catalogue provenance)",
            counts,
        )


def _register_loan_sources(counts):
    """Harvest the loan catalogue's Annexure-A / product-page URLs."""
    from loans.models import LoanProduct

    pairs = (
        LoanProduct.objects.filter(bank__isnull=False)
        .exclude(source_url="")
        .exclude(source_url__contains="bb.org.bd")
        .values_list("bank_id", "source_url")
        .distinct()
    )
    for bank_id, url in pairs:
        _register(
            Bank.objects.get(pk=bank_id),
            url,
            SourcePurpose.LOAN_RATES,
            "Loan Annexure-A / product page (loan catalogue provenance)",
            counts,
        )
