"""Nightly all-products sync orchestration (Phase 2, work package V4).

One run, three phases — parser-first and change-gated so a nightly run
needs few or zero LLM calls:

1. **Charts (deterministic, no LLM).** The Bangladesh Bank deposit and
   lending charts are fetched and parsed by the existing deposits/loans
   ingestions, which snapshot each edition and diff against stored rates.
   BB-sourced rows auto-verify (regulator-published data).
2. **Cards (existing crawl spine).** ``credit_card`` BankDataSource rows go
   through :class:`BankDataCrawlerService`: unchanged pages cost 0 LLM
   calls (SHA-256 change detection), changed pages are extracted under the
   per-run ``LLM_MAX_CALLS_PER_RUN`` budget and land as DRAFT cards /
   ReviewQueue proposals — verified data is never edited by the sync.
3. **Watched sources (change detection only).** Account SOC/rate sheets
   and deposit/loan rate pages have no per-product LLM extractor yet, so
   the sync only fetches + hashes them. A change records the new content
   and opens a ReviewQueue item for a human; an unchanged source costs one
   fetch and no LLM spend. Nothing is auto-applied or fabricated.

Every run is stored as a :class:`banks.models.SyncRun` with a structured
summary (sources checked/changed, chart results, drafts/proposals created,
LLM calls used, quota state). Phase failures are recorded and the run
continues — a sync must degrade gracefully (e.g. when the Gemini free-tier
daily quota is exhausted, the crawl phase stops early, the quota state is
logged distinctly, and the deterministic phases still complete).
"""

import json
import logging
from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone

from banks.enums import (
    ProcessingStatus,
    ReviewPriority,
    ReviewSource,
    SourcePurpose,
    SyncRunStatus,
    SyncTrigger,
)
from banks.models import BankDataSource, CrawledContent, ReviewQueue, SyncRun
from banks.services.bank_data_crawler import BankDataCrawlerService
from common.llm.budget import llm_call_budget

logger = logging.getLogger(__name__)

# Distinctive log marker so quota exhaustion is greppable in worker logs and
# alerting can key on it (free-tier Gemini keys cap at 20 requests/day/model).
QUOTA_LOG_MARKER = "LLM_QUOTA_EXHAUSTED"

WATCH_PURPOSES = (
    SourcePurpose.ACCOUNT_SOC,
    SourcePurpose.ACCOUNT_RATES,
    SourcePurpose.DEPOSIT_RATES,
    SourcePurpose.LOAN_RATES,
)


@contextmanager
def sync_gemini_model():
    """Pin the Gemini model while the nightly crawl phase runs.

    The Gemini provider reads ``settings.GEMINI_MODEL`` when it is
    constructed, so the crawler must be built inside this context. The
    model comes from ``settings.NIGHTLY_SYNC_GEMINI_MODEL``, which defaults
    to ``gemini-3.5-flash-lite`` when the operator has not set
    ``GEMINI_MODEL`` explicitly: the global default (``gemini-flash-latest``)
    intermittently returns 503s and exhausts the free-tier daily quota
    quickly, while the lite model is verified working end-to-end.
    """
    model = getattr(settings, "NIGHTLY_SYNC_GEMINI_MODEL", "gemini-3.5-flash-lite")
    previous = settings.GEMINI_MODEL
    if previous == model:
        yield model
        return
    settings.GEMINI_MODEL = model
    try:
        yield model
    finally:
        settings.GEMINI_MODEL = previous


class NightlySyncService:
    """Run one full nightly sync across all four product verticals."""

    def __init__(self, crawler=None):
        """Optionally inject a crawler (tests); built lazily otherwise.

        The default crawler is constructed inside the cards phase so the
        pinned sync Gemini model (see :func:`sync_gemini_model`) applies.
        """
        self._crawler = crawler

    def _get_crawler(self):
        if self._crawler is None:
            self._crawler = BankDataCrawlerService()
        return self._crawler

    def run(self, trigger=SyncTrigger.SCHEDULED):
        """Execute the sync and persist a SyncRun record. Never raises."""
        run = SyncRun.objects.create(trigger=trigger, status=SyncRunStatus.RUNNING)
        summary = {"errors": []}
        phases = (
            ("charts", self._sync_charts),
            ("cards", self._sync_cards),
            ("watch", self._sync_watch_sources),
        )
        completed = 0
        for name, phase in phases:
            try:
                phase(summary)
                completed += 1
            except Exception as exc:  # noqa: BLE001 - a phase must not kill the run
                logger.exception("Nightly sync phase %s failed", name)
                summary["errors"].append({"phase": name, "error": str(exc)})

        if completed == 0:
            run.status = SyncRunStatus.FAILED
        elif summary["errors"]:
            run.status = SyncRunStatus.PARTIAL
        else:
            run.status = SyncRunStatus.COMPLETED
        run.summary = json.loads(json.dumps(summary, default=str))
        # Carry the failure trail on the run row itself, so sync health is
        # auditable from the SyncRun record without digging into the summary.
        run.error = "\n".join(
            f"{entry.get('phase', 'sync')}: {entry.get('error', '')}"
            for entry in summary["errors"]
        )
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "summary", "error", "finished_at", "modified"])
        logger.info(
            "Nightly sync run %s finished with status %s: %s",
            run.pk,
            run.status,
            run.summary,
        )
        return run

    # ------------------------------------------------------------------
    # Phase 1: Bangladesh Bank charts (deterministic, no LLM)
    # ------------------------------------------------------------------
    def _sync_charts(self, summary):
        from deposits.constants import BB_DEPOSIT_CHART_URLS, ChartSource
        from deposits.ingestion.bb_chart import fetch_chart_html as fetch_deposit_html
        from deposits.ingestion.bb_chart import ingest_chart
        from loans.ingestion.bb_lending_chart import CHART_URL as LENDING_CHART_URL
        from loans.ingestion.bb_lending_chart import (
            fetch_chart_html as fetch_lending_html,
        )
        from loans.ingestion.bb_lending_chart import (
            ingest_lending_chart,
        )

        charts = {}
        for chart_source in ChartSource:
            url = BB_DEPOSIT_CHART_URLS[chart_source]
            key = f"deposit_{chart_source.value}"
            try:
                report = ingest_chart(fetch_deposit_html(url), chart_source, url)
                charts[key] = {
                    "edition": report["edition"],
                    "snapshot_created": report["snapshot_created"],
                    "banks_seen": report["banks_seen"],
                    "products_created": report["products_created"],
                    "products_updated": report["products_updated"],
                    "rates_created": report["rates_created"],
                    "rates_updated": report["rates_updated"],
                    "rates_deleted": report["rates_deleted"],
                    "history_rows": report["history_rows"],
                    "anomalies": len(report.get("anomalies") or []),
                }
                self._mark_chart_source(url, success=True)
            except Exception as exc:  # noqa: BLE001 - other charts still run
                logger.error("BB deposit chart %s failed: %s", chart_source.value, exc)
                charts[key] = {"error": str(exc)}
                summary["errors"].append({"phase": f"charts.{key}", "error": str(exc)})
                self._mark_chart_source(url, success=False)

        try:
            stats = ingest_lending_chart(fetch_lending_html())
            charts["lending"] = {
                "edition": stats["edition"],
                "snapshot_created": stats["snapshot_created"],
                "snapshot_refreshed": stats["snapshot_refreshed"],
                "banks_seen": stats["banks_seen"],
                "bands_created": stats["bands_created"],
                "bands_updated": stats["bands_updated"],
                "bands_removed": stats["bands_removed"],
                "anomalies": len(stats.get("anomalies") or []),
            }
            self._mark_chart_source(LENDING_CHART_URL, success=True)
        except Exception as exc:  # noqa: BLE001 - other phases still run
            logger.error("BB lending chart failed: %s", exc)
            charts["lending"] = {"error": str(exc)}
            summary["errors"].append({"phase": "charts.lending", "error": str(exc)})
            self._mark_chart_source(LENDING_CHART_URL, success=False)

        summary["charts"] = charts

    def _mark_chart_source(self, url, success):
        """Update crawl bookkeeping on the chart's BankDataSource registry row."""
        source = BankDataSource.objects.filter(url=url).first()
        if source is None:
            logger.warning(
                "No BankDataSource registered for chart %s; run bootstrap_sync_sources",
                url,
            )
            return
        if success:
            now = timezone.now()
            source.last_crawled_at = now
            source.last_successful_crawl_at = now
            source.save(update_fields=["last_crawled_at", "last_successful_crawl_at"])
            source.reset_failed_attempts()
        # On failure, deliberately leave failed_attempt_count untouched: the
        # chart registry rows are bookkeeping only — the deterministic chart
        # ingestion never consults them — so a transient chart outage (or a
        # bot-challenged fetch) must not march the row toward the automatic
        # deactivation threshold the card crawl spine uses.

    # ------------------------------------------------------------------
    # Phase 2: credit cards through the existing crawl spine
    # ------------------------------------------------------------------
    def _sync_cards(self, summary):
        from credit_cards.constants import VerificationStatus
        from credit_cards.models import CreditCard

        started_at = timezone.now()
        sources = BankDataSource.objects.filter(
            is_active=True,
            bank__is_active=True,
            purpose=SourcePurpose.CREDIT_CARD,
        )
        with sync_gemini_model() as model, llm_call_budget() as budget:
            crawler = self._get_crawler()
            results = crawler.crawl_sources(sources)
            quota_exhausted = bool(crawler.providers_rate_limited)
            llm_calls_used = budget.used

        summary["cards"] = {
            "sources_checked": results["total"],
            "sources_succeeded": results["successful"],
            "sources_failed": results["failed"],
            "sources_skipped": results["skipped"],
            "draft_cards_created": CreditCard.objects.filter(
                created__gte=started_at,
                verification_status=VerificationStatus.DRAFT,
            ).count(),
            "review_items_created": ReviewQueue.objects.filter(
                created__gte=started_at
            ).count(),
        }
        summary["llm"] = {
            "model": model,
            "calls_used": llm_calls_used,
            "budget_limit": budget.limit,
            "budget_exhausted": budget.exhausted,
            "quota_exhausted": quota_exhausted,
        }
        if quota_exhausted:
            logger.warning(
                "%s during nightly card crawl: all LLM providers rate limited; "
                "%s sources left for the next run. Deterministic phases are "
                "unaffected.",
                QUOTA_LOG_MARKER,
                results["skipped"],
            )

    # ------------------------------------------------------------------
    # Phase 3: watched sources for accounts / deposits / loans
    # ------------------------------------------------------------------
    def _sync_watch_sources(self, summary):
        sources = (
            BankDataSource.objects.filter(
                is_active=True,
                bank__is_active=True,
                purpose__in=WATCH_PURPOSES,
            )
            .select_related("bank")
            .order_by("bank__name", "url")
        )
        stats = {
            "checked": 0,
            "unchanged": 0,
            "changed": 0,
            "baselined": 0,
            "failed": 0,
            "review_items_created": 0,
        }
        crawler = self._get_crawler()
        for source in sources:
            stats["checked"] += 1
            try:
                outcome = self._check_watch_source(crawler, source)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one bad source must not skip the rest
                logger.exception(
                    "Nightly sync watch check failed for %s - %s",
                    source.bank.name,
                    source.url,
                )
                stats["failed"] += 1
                summary.setdefault("errors", []).append(
                    {"phase": "watch", "source": source.url, "error": str(exc)}
                )
                continue
            stats[outcome] += 1
            if outcome == "changed":
                stats["review_items_created"] += 1
        summary["watch"] = stats

    def _check_watch_source(self, crawler, source):
        """Fetch + hash one watched source; flag changes for human review.

        Returns one of 'unchanged', 'changed', 'baselined', 'failed'.
        Mirrors the card spine's hash semantics: the binary hash wins when
        the extractor produced one, and the newest non-failed CrawledContent
        row is the comparison baseline (a still-pending change is not
        re-flagged). Failed crawl records are excluded: the extractor logs
        failures as FAILED rows with an empty content hash, and letting one
        become the baseline would flag a phantom change on the next
        successful check.
        """
        extraction = crawler._extract_content_safely(source)
        if not extraction:
            return "failed"
        raw_content, extracted_content, context = extraction
        if not extracted_content and context.get("method") not in {
            "ocr",
            "image_ocr",
            "image",
        }:
            return "failed"

        # Postgres text columns cannot store NUL bytes, and some bank PDFs
        # extract with them embedded — one such source aborted the watch
        # phase of the first live run. Strip them before hashing so the
        # stored content and every future comparison use the same text.
        raw_content = raw_content.replace("\x00", "")
        extracted_content = extracted_content.replace("\x00", "")

        content_hash = crawler._generate_content_hash(extracted_content)
        binary_hash = getattr(crawler.content_extractor, "last_binary_hash", "")
        if isinstance(binary_hash, str) and binary_hash:
            content_hash = binary_hash

        latest = (
            CrawledContent.objects.filter(data_source=source)
            .exclude(processing_status=ProcessingStatus.FAILED)
            .order_by("-crawled_at", "-id")
            .first()
        )
        now = timezone.now()

        if latest is not None and latest.content_hash == content_hash:
            if latest.processing_status == ProcessingStatus.COMPLETED:
                crawler._record_no_changes(source, content_hash)
            else:
                source.last_crawled_at = now
                source.last_successful_crawl_at = now
                source.save(update_fields=["last_crawled_at", "last_successful_crawl_at"])
            return "unchanged"

        first_sight = latest is None
        content = CrawledContent.objects.create(
            data_source=source,
            raw_content=raw_content,
            extracted_content=extracted_content,
            content_hash=content_hash,
            extraction_method=context.get("method", ""),
            processing_status=(
                ProcessingStatus.COMPLETED if first_sight else ProcessingStatus.PENDING
            ),
            needs_manual_review=not first_sight,
            parsed_json={
                "nightly_sync": {
                    "purpose": source.purpose,
                    "baseline": first_sight,
                    "detected_at": now.isoformat(),
                }
            },
        )
        source.last_crawled_at = now
        source.last_successful_crawl_at = now
        source.save(update_fields=["last_crawled_at", "last_successful_crawl_at"])
        source.reset_failed_attempts()

        if first_sight:
            logger.info(
                "Nightly sync baselined watched source %s - %s",
                source.bank.name,
                source.url,
            )
            return "baselined"

        ReviewQueue.objects.create(
            crawled_content=content,
            bank=source.bank,
            source=ReviewSource.CRAWLER_PROPOSAL,
            priority=ReviewPriority.MEDIUM,
            message=(
                f"Nightly sync: the {source.get_purpose_display()} source for "
                f"{source.bank.name} changed since the last check ({source.url}). "
                "Per-product extraction for this vertical is manual — review the "
                "new content and update the catalogue; nothing was auto-applied."
            ),
        )
        logger.info(
            "Nightly sync flagged changed watched source %s - %s",
            source.bank.name,
            source.url,
        )
        return "changed"
