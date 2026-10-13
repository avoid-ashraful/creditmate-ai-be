"""Query helpers for the data-quality dashboard.

Aggregates crawled-content and credit-card data into a small, JSON-ready
snapshot for operations staff. The snapshot is served by the staff-only view
at ``/admin/data-quality/`` (see :mod:`banks.views`) and reported in
``docs/operations/data-quality-dashboard.md``.

Rate-style measures are reported as ``None`` instead of ``0.0`` whenever the
denominator does not exist, so callers can always tell "no data yet" apart
from "0%", and no divide-by-zero can ever happen:

* ``success_rate`` is ``completed / (completed + failed)`` and is ``None``
  when no content reached a terminal state;
* ``average_confidence_7d`` / ``average_confidence_30d`` are the mean of
  non-null ``extraction_confidence`` over content crawled inside the window
  and are ``None`` when no scored content exists in the window;
* method ``completion_rate`` is ``completed / total`` and is ``None`` when a
  bucket is empty.

Missing critical values are counted twice on purpose:

* ``content_missing_*`` - completed ``CrawledContent`` rows whose
  ``missing_critical_fields`` list names the field (the LLM reported it);
* ``cards_null_*`` - ``CreditCard`` rows for the bank whose numeric column is
  NULL (the joined record was created without a usable value).

Alert rules (see :data:`CONFIDENCE_ALERT_THRESHOLD` and
:data:`SUCCESS_RATE_ALERT_THRESHOLD`):

* ``low_confidence`` - most recent confidence average (7-day window, falling
  back to the 30-day window) below 0.5;
* ``low_success_rate`` - ``success_rate`` below 0.7.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from banks.enums import ProcessingStatus
from banks.models import Bank, BankDataSource, CrawledContent
from credit_cards.models import CreditCard

# Thresholds used by the alert builder.
CONFIDENCE_ALERT_THRESHOLD = 0.5
SUCCESS_RATE_ALERT_THRESHOLD = 0.7

# Confidence windows, in days, reported next to their averages.
CONFIDENCE_WINDOWS_DAYS = (7, 30)

# Extraction-method buckets used by the OCR-vs-text comparison. Anything not
# listed here (including the empty default) falls into the "unknown" bucket.
_METHOD_BUCKETS = {
    "ocr": ("ocr", "image_ocr"),
    "text": ("pdf_text", "webpage", "csv"),
}


def success_rate(completed, failed):
    """Compute the share of terminalised content that completed.

    Parameters
    ----------
    completed : int
        Count of ``completed`` CrawledContent rows.
    failed : int
        Count of ``failed`` CrawledContent rows.

    Returns
    -------
    float or None
        ``completed / (completed + failed)`` rounded to 4 decimals, or
        ``None`` when the denominator is zero (nothing completed or failed).
    """
    denominator = completed + failed
    if denominator <= 0:
        return None
    return round(completed / denominator, 4)


def _round_or_none(value):
    """Round a float to 4 decimals, passing ``None`` through unchanged."""
    if value is None:
        return None
    return round(value, 4)


def _status_counts(queryset):
    """Count CrawledContent rows by processing status in one query.

    Parameters
    ----------
    queryset : QuerySet
        Base CrawledContent queryset to aggregate.

    Returns
    -------
    dict
        Keys ``total``, ``completed``, ``failed``, ``pending``, ``processing``.
    """
    return queryset.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(processing_status=ProcessingStatus.COMPLETED)),
        failed=Count("id", filter=Q(processing_status=ProcessingStatus.FAILED)),
        pending=Count("id", filter=Q(processing_status=ProcessingStatus.PENDING)),
        processing=Count("id", filter=Q(processing_status=ProcessingStatus.PROCESSING)),
    )


def _confidence_windows(queryset):
    """Build the 7- and 30-day confidence block for a queryset.

    Parameters
    ----------
    queryset : QuerySet
        Base CrawledContent queryset to aggregate.

    Returns
    -------
    dict
        Keys ``average_confidence_7d``, ``average_confidence_30d``,
        ``scored_7d``, ``scored_30d``.
    """
    now = timezone.now()
    windows = {}
    for days in CONFIDENCE_WINDOWS_DAYS:
        since = now - timedelta(days=days)
        scored = queryset.filter(
            crawled_at__gte=since,
            extraction_confidence__isnull=False,
        ).aggregate(
            average=Avg("extraction_confidence"),
            count=Count("id"),
        )
        label = f"average_confidence_{days}d"
        windows[label] = _round_or_none(scored["average"])
        windows[f"scored_{days}d"] = scored["count"]
    return {
        "average_confidence_7d": windows["average_confidence_7d"],
        "average_confidence_30d": windows["average_confidence_30d"],
        "scored_7d": windows["scored_7d"],
        "scored_30d": windows["scored_30d"],
    }


def _content_missing_counts(queryset):
    """Count completed rows whose missing_critical_fields names each field.

    Parameters
    ----------
    queryset : QuerySet
        Base CrawledContent queryset (per bank or global).

    Returns
    -------
    dict
        Keys ``content_missing_annual_fee`` and ``content_missing_apr``.
    """
    completed = queryset.filter(processing_status=ProcessingStatus.COMPLETED)
    return {
        "content_missing_annual_fee": completed.filter(
            missing_critical_fields__contains=["annual_fee"]
        ).count(),
        "content_missing_apr": completed.filter(
            missing_critical_fields__contains=["interest_rate_apr"]
        ).count(),
    }


def _null_card_counts(cards_queryset):
    """Count CreditCard rows holding NULL critical numeric columns.

    Parameters
    ----------
    cards_queryset : QuerySet
        CreditCard queryset restricted to a bank (or all cards).
        These are the rows the ``CrawledContent.credit_card`` relation points
        at, i.e. the "join" side for null critical numeric values.

    Returns
    -------
    dict
        Keys ``cards_null_annual_fee`` and ``cards_null_apr``.
    """
    return {
        "cards_null_annual_fee": cards_queryset.filter(annual_fee__isnull=True).count(),
        "cards_null_apr": cards_queryset.filter(interest_rate_apr__isnull=True).count(),
    }


def _metric_block(contents_queryset, cards_queryset):
    """Assemble the shared per-bank / totals metric block.

    Parameters
    ----------
    contents_queryset : QuerySet
        CrawledContent queryset scoped to the subject.
    cards_queryset : QuerySet
        CreditCard queryset scoped to the same subject.

    Returns
    -------
    dict
        Status counts, success rate, confidence windows, missing-field counts
        and null-card counts for the subject.
    """
    counts = _status_counts(contents_queryset)
    block = {"total_contents": counts["total"]}
    for key in ("completed", "failed", "pending", "processing"):
        block[key] = counts[key]
    block["success_rate"] = success_rate(counts["completed"], counts["failed"])
    block.update(_confidence_windows(contents_queryset))
    block.update(_content_missing_counts(contents_queryset))
    block.update(_null_card_counts(cards_queryset))
    return block


def bank_summary(bank):
    """Build the dashboard block for one bank.

    Parameters
    ----------
    bank : Bank
        The bank to summarise.

    Returns
    -------
    dict
        Identity fields plus every metric in :func:`_metric_block`, scoped to
        the bank via ``CrawledContent.data_source.bank`` and
        ``CreditCard.bank``.
    """
    contents = CrawledContent.objects.filter(data_source__bank=bank)
    cards = CreditCard.objects.filter(bank=bank)
    block = _metric_block(contents, cards)
    block["bank_id"] = bank.pk
    block["bank_name"] = bank.name
    block["data_sources"] = BankDataSource.objects.filter(bank=bank).count()
    return block


def totals_summary():
    """Build the whole-system totals block.

    Returns
    -------
    dict
        Global counts (banks/data sources) plus every metric in
        :func:`_metric_block` over all content and cards.
    """
    block = _metric_block(CrawledContent.objects.all(), CreditCard.objects.all())
    block["banks"] = Bank.objects.count()
    block["data_sources"] = BankDataSource.objects.count()
    return block


def _method_summary(queryset):
    """Summarise completion and success rates for one method bucket.

    Parameters
    ----------
    queryset : QuerySet
        CrawledContent queryset already filtered to one method bucket.

    Returns
    -------
    dict
        Status counts plus ``completion_rate`` (completed / total) and
        ``success_rate`` (completed / [completed + failed]); both ``None``
        when the denominator is empty.
    """
    counts = _status_counts(queryset)
    summary = {"total_contents": counts["total"]}
    for key in ("completed", "failed", "pending", "processing"):
        summary[key] = counts[key]
    if counts["total"]:
        summary["completion_rate"] = round(counts["completed"] / counts["total"], 4)
    else:
        summary["completion_rate"] = None
    summary["success_rate"] = success_rate(counts["completed"], counts["failed"])
    return summary


def method_comparison():
    """Compare OCR-based vs text-based extraction pipelines.

    OCR buckets merge ``ocr`` and ``image_ocr``; text buckets merge
    ``pdf_text``, ``webpage`` and ``csv``; every other value (blank, unknown
    or future methods) lands in ``unknown``.

    Returns
    -------
    dict
        Mapping of bucket name to :func:`_method_summary` output.
    """
    comparison = {}
    known = [method for bucket in _METHOD_BUCKETS.values() for method in bucket]
    for label, methods in _METHOD_BUCKETS.items():
        comparison[label] = _method_summary(
            CrawledContent.objects.filter(extraction_method__in=methods)
        )
    comparison["unknown"] = _method_summary(
        CrawledContent.objects.exclude(extraction_method__in=known)
    )
    return comparison


def _latest_confidence_average(block):
    """Return the most recent confidence average available in a metric block.

    Parameters
    ----------
    block : dict
        Metric block containing ``average_confidence_7d`` and
        ``average_confidence_30d``.

    Returns
    -------
    float or None
        The 7-day average when present, otherwise the 30-day average.
    """
    return block["average_confidence_7d"] or block["average_confidence_30d"]


def build_alerts(totals, bank_blocks):
    """Build alert entries from totals and per-bank metric blocks.

    No alert is emitted for a bank (or overall) when the required value is
    ``None`` - an empty denominator never triggers a false alarm.

    Parameters
    ----------
    totals : dict
        :func:`totals_summary` output.
    bank_blocks : list of dict
        :func:`bank_summary` output for every bank.

    Returns
    -------
    list of dict
        Canonical alert entries with ``scope``, ``kind``, ``value``,
        ``message`` and, for bank alerts, ``bank_id``/``bank_name``.
    """
    alerts = []

    overall_confidence = _latest_confidence_average(totals)
    if overall_confidence is not None and overall_confidence < CONFIDENCE_ALERT_THRESHOLD:
        alerts.append(
            {
                "scope": "overall",
                "bank_id": None,
                "bank_name": None,
                "kind": "low_confidence",
                "value": overall_confidence,
                "message": (
                    f"Overall average extraction confidence "
                    f"({overall_confidence}) is below "
                    f"{CONFIDENCE_ALERT_THRESHOLD}."
                ),
            }
        )
    if (
        totals["success_rate"] is not None
        and totals["success_rate"] < SUCCESS_RATE_ALERT_THRESHOLD
    ):
        alerts.append(
            {
                "scope": "overall",
                "bank_id": None,
                "bank_name": None,
                "kind": "low_success_rate",
                "value": totals["success_rate"],
                "message": (
                    f"Overall extraction success rate "
                    f"({totals['success_rate']}) is below "
                    f"{int(SUCCESS_RATE_ALERT_THRESHOLD * 100)}%."
                ),
            }
        )

    for bank in bank_blocks:
        confidence = _latest_confidence_average(bank)
        if confidence is not None and confidence < CONFIDENCE_ALERT_THRESHOLD:
            alerts.append(
                {
                    "scope": "bank",
                    "bank_id": bank["bank_id"],
                    "bank_name": bank["bank_name"],
                    "kind": "low_confidence",
                    "value": confidence,
                    "message": (
                        f"{bank['bank_name']} average extraction confidence "
                        f"({confidence}) is below "
                        f"{CONFIDENCE_ALERT_THRESHOLD}."
                    ),
                }
            )
        if (
            bank["success_rate"] is not None
            and bank["success_rate"] < SUCCESS_RATE_ALERT_THRESHOLD
        ):
            alerts.append(
                {
                    "scope": "bank",
                    "bank_id": bank["bank_id"],
                    "bank_name": bank["bank_name"],
                    "kind": "low_success_rate",
                    "value": bank["success_rate"],
                    "message": (
                        f"{bank['bank_name']} extraction success rate "
                        f"({bank['success_rate']}) is below "
                        f"{int(SUCCESS_RATE_ALERT_THRESHOLD * 100)}%."
                    ),
                }
            )
    return alerts


def build_dashboard():
    """Assemble the complete data-quality dashboard snapshot.

    Returns
    -------
    dict
        JSON-ready snapshot with ``generated_at``, ``totals``, ``banks``
        (per bank, ordered by name), ``methods`` (OCR-vs-text comparison) and
        ``alerts``.
    """
    totals = totals_summary()
    banks = [bank_summary(bank) for bank in Bank.objects.all()]
    return {
        "generated_at": timezone.now().isoformat(),
        "totals": totals,
        "banks": banks,
        "methods": method_comparison(),
        "alerts": build_alerts(totals, banks),
    }


__all__ = [
    "CONFIDENCE_ALERT_THRESHOLD",
    "CONFIDENCE_WINDOWS_DAYS",
    "SUCCESS_RATE_ALERT_THRESHOLD",
    "bank_summary",
    "build_alerts",
    "build_dashboard",
    "method_comparison",
    "success_rate",
    "totals_summary",
]
