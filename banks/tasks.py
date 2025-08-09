import logging

from django.db import models
from django.utils import timezone

# Optional import for Celery
try:
    from celery import shared_task
except ImportError:
    # Fallback for when Celery is not installed
    def shared_task(bind=False, max_retries=3, default_retry_delay=300):
        def decorator(func):
            func.request = None  # Mock request object
            return func

        return decorator


from banks.enums import ContentType
from banks.models import Bank, BankDataSource
from banks.services import BankDataCrawlerService, ScheduleChargeURLFinder

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def crawl_bank_data_source(self, data_source_id):
    """Celery task to crawl a single bank data source.

    Parameters
    ----------
    self : celery.Task
        Celery task instance for retry functionality
    data_source_id : int
        ID of the BankDataSource to crawl

    Returns
    -------
    dict
        Dictionary containing task result information with keys:
        - status: 'success', 'failed', or 'error'
        - data_source_id: ID of the processed data source
        - timestamp: ISO formatted timestamp
        - error: Error message if applicable
    """
    try:
        crawler = BankDataCrawlerService()
        success = crawler.crawl_bank_data_source(data_source_id)

        if success:
            logger.info(f"Successfully crawled data source {data_source_id}")
            return {
                "status": "success",
                "data_source_id": data_source_id,
                "timestamp": timezone.now().isoformat(),
            }
        else:
            logger.error(f"Failed to crawl data source {data_source_id}")
            return {
                "status": "failed",
                "data_source_id": data_source_id,
                "timestamp": timezone.now().isoformat(),
                "error": "Crawling failed",
            }

    except Exception as exc:
        logger.error(f"Error in crawl_bank_data_source task: {str(exc)}")

        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info(
                f"Retrying crawl_bank_data_source task for data source {data_source_id}"
            )
            raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))

        return {
            "status": "error",
            "data_source_id": data_source_id,
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task
def crawl_all_bank_data():
    """Celery task to crawl all active bank data sources.

    This task is scheduled to run weekly and processes all active
    bank data sources in the system.

    Parameters
    ----------
    None

    Returns
    -------
    dict
        Dictionary containing overall crawling results with keys:
        - status: 'completed' or 'error'
        - timestamp: ISO formatted timestamp
        - results: Summary of crawling results
        - error: Error message if applicable
    """
    try:
        logger.info("Starting weekly crawl of all bank data sources")

        crawler = BankDataCrawlerService()
        results = crawler.crawl_all_active_sources()

        logger.info(f"Weekly crawl completed: {results}")

        return {
            "status": "completed",
            "timestamp": timezone.now().isoformat(),
            "results": results,
        }

    except Exception as exc:
        logger.error(f"Error in crawl_all_bank_data task: {str(exc)}")
        return {
            "status": "error",
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task
def crawl_bank_data_sources_by_bank(bank_id):
    """Celery task to crawl all data sources for a specific bank.

    Parameters
    ----------
    bank_id : int
        ID of the Bank whose data sources should be crawled

    Returns
    -------
    dict
        Dictionary containing crawling results for the bank with keys:
        - status: 'completed', 'skipped', or 'error'
        - bank_id: ID of the processed bank
        - timestamp: ISO formatted timestamp
        - results: Summary of crawling results
        - error: Error message if applicable
    """
    try:
        data_sources = BankDataSource.objects.filter(bank_id=bank_id, is_active=True)

        if not data_sources.exists():
            logger.warning(f"No active data sources found for bank {bank_id}")
            return {
                "status": "completed",
                "bank_id": bank_id,
                "timestamp": timezone.now().isoformat(),
                "results": {"total": 0, "successful": 0, "failed": 0},
            }

        logger.info(
            f"Starting crawl for bank {bank_id} with {data_sources.count()} data sources"
        )

        results = {"total": data_sources.count(), "successful": 0, "failed": 0}

        crawler = BankDataCrawlerService()

        for data_source in data_sources:
            if crawler.crawl_bank_data_source(data_source.id):
                results["successful"] += 1
            else:
                results["failed"] += 1

        logger.info(f"Bank {bank_id} crawl completed: {results}")

        return {
            "status": "completed",
            "bank_id": bank_id,
            "timestamp": timezone.now().isoformat(),
            "results": results,
        }

    except Exception as exc:
        logger.error(f"Error in crawl_bank_data_sources_by_bank task: {str(exc)}")
        return {
            "status": "error",
            "bank_id": bank_id,
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task
def cleanup_old_crawled_content(days_to_keep=30):
    """Celery task to clean up old crawled content records.

    Keeps only the most recent records for each data source by removing
    records older than the specified number of days.

    Parameters
    ----------
    days_to_keep : int, optional
        Number of days worth of records to keep, by default 30

    Returns
    -------
    dict
        Dictionary containing cleanup results with keys:
        - status: 'completed' or 'error'
        - timestamp: ISO formatted timestamp
        - deleted_count: Number of records deleted
        - cutoff_date: Date threshold for deletion
        - error: Error message if applicable
    """
    try:
        from datetime import timedelta

        from django.utils import timezone

        from banks.models import CrawledContent

        cutoff_date = timezone.now() - timedelta(days=days_to_keep)

        old_records = CrawledContent.objects.filter(crawled_at__lt=cutoff_date)

        deleted_count = old_records.count()
        old_records.delete()

        logger.info(f"Cleaned up {deleted_count} old crawled content records")

        return {
            "status": "completed",
            "timestamp": timezone.now().isoformat(),
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
        }

    except Exception as exc:
        logger.error(f"Error in cleanup_old_crawled_content task: {str(exc)}")
        return {
            "status": "error",
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def find_and_update_schedule_charge_urls(self):
    """Celery task to find schedule charge URLs for all banks and update BankDataSource.

    This task performs the following operations:
    1. Goes through all banks with schedule_charge_url configured
    2. Uses AI to find the exact URL for charges document/page
    3. Checks if URL exists in BankDataSource, updates last_verified_at if exists
    4. Creates new BankDataSource entry if URL doesn't exist

    Parameters
    ----------
    self : celery.Task
        Celery task instance for retry functionality

    Returns
    -------
    dict
        Dictionary containing task results with keys:
        - status: 'completed' or 'error'
        - timestamp: ISO formatted timestamp
        - results: Summary of processing results
        - error: Error message if applicable
    """
    try:
        logger.info("Starting schedule charge URL discovery for all banks")

        banks = _get_banks_with_schedule_urls()
        if not banks.exists():
            return _create_empty_result()

        finder = ScheduleChargeURLFinder()
        results = _initialize_task_results(banks.count())

        for bank in banks:
            _process_bank_schedule_url(bank, finder, results)

        logger.info(f"Schedule charge URL discovery completed: {results}")
        return _create_success_result(results)

    except Exception as exc:
        return _handle_task_exception(self, exc)


def _get_banks_with_schedule_urls():
    """Get all active banks with schedule_charge_url configured.

    Parameters
    ----------
    None

    Returns
    -------
    QuerySet
        Django QuerySet of Bank instances that are active and have
        schedule_charge_url configured
    """
    return Bank.objects.filter(is_active=True, schedule_charge_url__isnull=False).exclude(
        schedule_charge_url=""
    )


def _create_empty_result():
    """Create result for when no banks are found.

    Parameters
    ----------
    None

    Returns
    -------
    dict
        Empty result dictionary with zero counts for all metrics
    """
    logger.warning("No banks found with schedule_charge_url configured")
    return {
        "status": "completed",
        "timestamp": timezone.now().isoformat(),
        "results": {
            "total": 0,
            "processed": 0,
            "found": 0,
            "updated": 0,
            "created": 0,
            "errors": 0,
        },
    }


def _initialize_task_results(total_count):
    """Initialize the task results tracking dictionary.

    Parameters
    ----------
    total_count : int
        Total number of banks to process

    Returns
    -------
    dict
        Initialized results dictionary with tracking counters
    """
    return {
        "total": total_count,
        "processed": 0,
        "found": 0,
        "updated": 0,
        "created": 0,
        "errors": 0,
    }


def _process_bank_schedule_url(bank, finder, results):
    """Process a single bank's schedule URL discovery.

    Parameters
    ----------
    bank : Bank
        Bank instance to process
    finder : ScheduleChargeURLFinder
        URL finder service instance
    results : dict
        Results dictionary to update with processing outcomes

    Returns
    -------
    None
    """
    try:
        logger.info(f"Processing bank: {bank.name} - {bank.schedule_charge_url}")
        results["processed"] += 1

        find_result = finder.find_schedule_charge_url(bank.schedule_charge_url)

        if find_result["found"]:
            _handle_found_url(bank, find_result, results)
        else:
            _handle_url_not_found(bank, find_result)

    except Exception as e:
        logger.error(f"Error processing bank {bank.name}: {str(e)}")
        results["errors"] += 1


def _handle_found_url(bank, find_result, results):
    """Handle the case when a schedule URL is found."""
    results["found"] += 1
    exact_url = find_result["url"]
    content_type = find_result.get("content_type", "PDF")

    logger.info(f"Found schedule charge URL for {bank.name}: {exact_url}")

    enum_content_type = _map_content_type(content_type)
    existing_source = BankDataSource.objects.filter(bank=bank, url=exact_url).first()

    if existing_source:
        _update_existing_source(existing_source, exact_url, results)
    else:
        _create_new_source(bank, exact_url, enum_content_type, results)


def _handle_url_not_found(bank, find_result):
    """Handle the case when no schedule URL is found."""
    logger.warning(
        f"No schedule charge URL found for {bank.name}: {find_result.get('error', 'Unknown error')}"
    )


def _map_content_type(content_type):
    """Map content type string to enum value."""
    return ContentType.PDF if content_type == "PDF" else ContentType.WEBPAGE


def _update_existing_source(existing_source, exact_url, results):
    """Update existing BankDataSource with verification timestamp."""
    existing_source.last_verified_at = timezone.now()
    existing_source.save(update_fields=["last_verified_at"])
    results["updated"] += 1
    logger.info(f"Updated last_verified_at for existing data source: {exact_url}")


def _create_new_source(bank, exact_url, enum_content_type, results):
    """Create new BankDataSource entry."""
    BankDataSource.objects.create(
        bank=bank,
        url=exact_url,
        content_type=enum_content_type,
        description="Schedule of charges document (auto-discovered)",
        is_active=True,
        last_verified_at=timezone.now(),
    )
    results["created"] += 1
    logger.info(f"Created new data source for {bank.name}: {exact_url}")


def _create_success_result(results):
    """Create successful task result."""
    return {
        "status": "completed",
        "timestamp": timezone.now().isoformat(),
        "results": results,
    }


def _handle_task_exception(task_self, exc):
    """Handle task-level exceptions with retry logic."""
    logger.error(f"Error in find_and_update_schedule_charge_urls task: {str(exc)}")

    # Retry the task if we haven't exceeded max retries
    if task_self.request.retries < task_self.max_retries:
        logger.info("Retrying find_and_update_schedule_charge_urls task")
        raise task_self.retry(exc=exc, countdown=60 * (2**task_self.request.retries))

    return {
        "status": "error",
        "timestamp": timezone.now().isoformat(),
        "error": str(exc),
    }


@shared_task
def find_schedule_charge_url_for_bank(bank_id):
    """Celery task to find schedule charge URL for a specific bank.

    Parameters
    ----------
    bank_id : int
        ID of the bank to process for URL discovery

    Returns
    -------
    dict
        Dictionary containing task results for the specific bank with keys:
        - status: 'success', 'not_found', 'skipped', or 'error'
        - bank_id: ID of the processed bank
        - bank_name: Name of the bank
        - timestamp: ISO formatted timestamp
        - found_url: URL if found
        - error: Error message if applicable
    """
    try:
        bank = Bank.objects.get(id=bank_id, is_active=True)

        if not bank.schedule_charge_url:
            logger.warning(f"Bank {bank.name} has no schedule_charge_url configured")
            return {
                "status": "skipped",
                "bank_id": bank_id,
                "bank_name": bank.name,
                "timestamp": timezone.now().isoformat(),
                "reason": "No schedule_charge_url configured",
            }

        logger.info(f"Finding schedule charge URL for bank: {bank.name}")

        finder = ScheduleChargeURLFinder()
        find_result = finder.find_schedule_charge_url(bank.schedule_charge_url)

        if find_result["found"]:
            exact_url = find_result["url"]
            content_type = find_result.get("content_type", "PDF")

            # Map content_type to enum value
            if content_type == "PDF":
                enum_content_type = ContentType.PDF
            else:
                enum_content_type = ContentType.WEBPAGE

            # Check if this URL already exists in BankDataSource
            existing_source = BankDataSource.objects.filter(
                bank=bank, url=exact_url
            ).first()

            if existing_source:
                # Update last_verified_at
                existing_source.last_verified_at = timezone.now()
                existing_source.save(update_fields=["last_verified_at"])
                action = "updated"
            else:
                # Create new BankDataSource entry
                BankDataSource.objects.create(
                    bank=bank,
                    url=exact_url,
                    content_type=enum_content_type,
                    description="Schedule of charges document (auto-discovered)",
                    is_active=True,
                    last_verified_at=timezone.now(),
                )
                action = "created"

            logger.info(f"Successfully {action} data source for {bank.name}: {exact_url}")

            return {
                "status": "success",
                "bank_id": bank_id,
                "bank_name": bank.name,
                "timestamp": timezone.now().isoformat(),
                "found_url": exact_url,
                "content_type": content_type,
                "action": action,
            }
        else:
            logger.warning(
                f"No schedule charge URL found for {bank.name}: {find_result.get('error', 'Unknown error')}"
            )
            return {
                "status": "not_found",
                "bank_id": bank_id,
                "bank_name": bank.name,
                "timestamp": timezone.now().isoformat(),
                "error": find_result.get("error", "Unknown error"),
            }

    except Bank.DoesNotExist:
        logger.error(f"Bank with ID {bank_id} not found")
        return {
            "status": "error",
            "bank_id": bank_id,
            "timestamp": timezone.now().isoformat(),
            "error": "Bank not found",
        }
    except Exception as exc:
        logger.error(f"Error finding schedule charge URL for bank {bank_id}: {str(exc)}")
        return {
            "status": "error",
            "bank_id": bank_id,
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def monthly_data_quality_check(self):
    """
    Monthly task to perform comprehensive data quality checks.
    Runs on the 1st day of each month.

    Returns:
        Dict containing task results
    """
    try:
        logger.info("Starting monthly data quality check")

        results = _initialize_quality_check_results()

        # Perform all quality checks
        _check_banks_without_sources(results)
        _check_stale_data_sources(results)
        _check_failed_data_sources(results)
        _check_banks_without_cards(results)
        _check_system_health(results)
        _check_duplicate_content_hashes(results)

        logger.info(f"Monthly data quality check completed: {results}")
        return {"status": "completed", "results": results}

    except Exception as exc:
        return _handle_quality_check_exception(self, exc)


def _initialize_quality_check_results():
    """Initialize the quality check results structure."""
    return {
        "timestamp": timezone.now().isoformat(),
        "checks": {},
        "issues_found": [],
        "recommendations": [],
    }


def _check_banks_without_sources(results):
    """Check for banks without data sources."""
    from banks.models import Bank

    banks_without_sources = Bank.objects.filter(
        is_active=True, data_sources__isnull=True
    ).distinct()

    results["checks"]["banks_without_sources"] = banks_without_sources.count()
    if banks_without_sources.exists():
        bank_names = list(banks_without_sources.values_list("name", flat=True))
        results["issues_found"].append(
            {
                "type": "missing_data_sources",
                "count": len(bank_names),
                "banks": bank_names,
            }
        )
        results["recommendations"].append("Configure data sources for banks without any")


def _check_stale_data_sources(results):
    """Check for data sources that haven't been crawled in 30 days."""
    from datetime import timedelta

    from banks.models import BankDataSource

    cutoff_date = timezone.now() - timedelta(days=30)
    stale_sources = BankDataSource.objects.filter(
        is_active=True, last_successful_crawl_at__lt=cutoff_date
    )

    results["checks"]["stale_data_sources"] = stale_sources.count()
    if stale_sources.exists():
        stale_info = _build_stale_sources_info(stale_sources)
        results["issues_found"].append(
            {
                "type": "stale_data_sources",
                "count": stale_sources.count(),
                "sources": stale_info,
            }
        )
        results["recommendations"].append(
            "Review and fix data sources that haven't been crawled recently"
        )


def _build_stale_sources_info(stale_sources):
    """Build information list for stale data sources."""
    stale_info = []
    for source in stale_sources[:10]:  # Limit to first 10
        stale_info.append(
            {
                "bank": source.bank.name,
                "url": source.url,
                "last_crawl": (
                    source.last_successful_crawl_at.isoformat()
                    if source.last_successful_crawl_at
                    else None
                ),
            }
        )
    return stale_info


def _check_failed_data_sources(results):
    """Check for failed data sources with 5+ failures."""
    from banks.models import BankDataSource

    failed_sources = BankDataSource.objects.filter(
        failed_attempt_count__gte=5, is_active=False
    )

    results["checks"]["failed_data_sources"] = failed_sources.count()
    if failed_sources.exists():
        failed_info = _build_failed_sources_info(failed_sources)
        results["issues_found"].append(
            {
                "type": "failed_data_sources",
                "count": failed_sources.count(),
                "sources": failed_info,
            }
        )
        results["recommendations"].append(
            "Review and fix permanently failed data sources"
        )


def _build_failed_sources_info(failed_sources):
    """Build information list for failed data sources."""
    failed_info = []
    for source in failed_sources:
        failed_info.append(
            {
                "bank": source.bank.name,
                "url": source.url,
                "failed_attempts": source.failed_attempt_count,
            }
        )
    return failed_info


def _check_banks_without_cards(results):
    """Check for banks without credit cards."""
    from banks.models import Bank

    banks_without_cards = Bank.objects.filter(
        is_active=True, credit_cards__isnull=True
    ).distinct()

    results["checks"]["banks_without_cards"] = banks_without_cards.count()
    if banks_without_cards.exists():
        bank_names = list(banks_without_cards.values_list("name", flat=True))
        results["issues_found"].append(
            {
                "type": "banks_without_cards",
                "count": len(bank_names),
                "banks": bank_names,
            }
        )
        results["recommendations"].append(
            "Investigate why some banks have no credit card data"
        )


def _check_system_health(results):
    """Check overall system health metrics."""
    from datetime import timedelta

    from banks.models import Bank, BankDataSource, CrawledContent
    from credit_cards.models import CreditCard

    total_banks = Bank.objects.filter(is_active=True).count()
    total_sources = BankDataSource.objects.filter(is_active=True).count()
    total_cards = CreditCard.objects.filter(is_active=True).count()
    recent_crawls = CrawledContent.objects.filter(
        crawled_at__gte=timezone.now() - timedelta(days=7)
    ).count()

    results["checks"]["system_health"] = {
        "active_banks": total_banks,
        "active_data_sources": total_sources,
        "active_credit_cards": total_cards,
        "recent_crawls": recent_crawls,
        "health_score": min(100, (recent_crawls / max(total_sources, 1)) * 100),
    }


def _check_duplicate_content_hashes(results):
    """Check for duplicate content hashes."""
    from banks.models import CrawledContent

    duplicate_hashes = (
        CrawledContent.objects.values("content_hash")
        .annotate(count=models.Count("content_hash"))
        .filter(count__gt=1, content_hash__isnull=False)
        .exclude(content_hash="")
    )

    results["checks"]["duplicate_content_hashes"] = duplicate_hashes.count()
    if duplicate_hashes.exists():
        results["recommendations"].append(
            "Consider cleaning up duplicate content records"
        )


def _handle_quality_check_exception(task_self, exc):
    """Handle exceptions in quality check task with retry logic."""
    logger.error(f"Error in monthly_data_quality_check task: {str(exc)}")

    # Retry the task if we haven't exceeded max retries
    if task_self.request.retries < task_self.max_retries:
        logger.info("Retrying monthly_data_quality_check task")
        raise task_self.retry(exc=exc, countdown=60 * (2**task_self.request.retries))

    return {
        "status": "error",
        "timestamp": timezone.now().isoformat(),
        "error": str(exc),
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def monthly_schedule_charge_url_discovery(self):
    """
    Monthly task to discover and update schedule charge URLs for all banks.
    Runs on the 1st day of each month.

    Returns:
        Dict containing task results
    """
    try:
        logger.info("Starting monthly schedule charge URL discovery")

        # Use the existing function but make it async
        from banks.tasks import find_and_update_schedule_charge_urls

        # Call the existing task function directly (not as Celery task)
        # to avoid nested task calls
        dummy_request = type("Request", (), {"retries": 0, "max_retries": 3})()

        # Create a temporary instance with request mock
        task_instance = type("Task", (), {"request": dummy_request, "max_retries": 3})()

        result = find_and_update_schedule_charge_urls(task_instance)

        logger.info("Monthly schedule charge URL discovery completed")

        return {
            "status": "completed",
            "timestamp": timezone.now().isoformat(),
            "task_type": "monthly_schedule_charge_discovery",
            "results": result.get("results", {}),
        }

    except Exception as exc:
        logger.error(f"Error in monthly_schedule_charge_url_discovery task: {str(exc)}")

        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info("Retrying monthly_schedule_charge_url_discovery task")
            raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))

        return {
            "status": "error",
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }


@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def monthly_comprehensive_crawl(self):
    """
    Monthly comprehensive crawl of all bank data sources.
    Runs on the 1st day of each month.

    Returns:
        Dict containing task results
    """
    try:
        logger.info("Starting monthly comprehensive crawl")

        from banks.services import BankDataCrawlerService

        crawler = BankDataCrawlerService()
        results = crawler.crawl_all_active_sources()

        logger.info(f"Monthly comprehensive crawl completed: {results}")

        return {
            "status": "completed",
            "timestamp": timezone.now().isoformat(),
            "task_type": "monthly_comprehensive_crawl",
            "results": results,
        }

    except Exception as exc:
        logger.error(f"Error in monthly_comprehensive_crawl task: {str(exc)}")

        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info("Retrying monthly_comprehensive_crawl task")
            raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))

        return {
            "status": "error",
            "timestamp": timezone.now().isoformat(),
            "error": str(exc),
        }
