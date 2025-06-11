import logging
from typing import Any, Dict

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


from .models import BankDataSource
from .services import BankDataCrawlerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def crawl_bank_data_source(self, data_source_id: int) -> Dict[str, Any]:
    """
    Celery task to crawl a single bank data source.

    Args:
        data_source_id: ID of the BankDataSource to crawl

    Returns:
        Dict containing task result information
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
def crawl_all_bank_data() -> Dict[str, Any]:
    """
    Celery task to crawl all active bank data sources.
    This task is scheduled to run weekly.

    Returns:
        Dict containing overall crawling results
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
def crawl_bank_data_sources_by_bank(bank_id: int) -> Dict[str, Any]:
    """
    Celery task to crawl all data sources for a specific bank.

    Args:
        bank_id: ID of the Bank whose data sources should be crawled

    Returns:
        Dict containing crawling results for the bank
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
def cleanup_old_crawled_content(days_to_keep: int = 30) -> Dict[str, Any]:
    """
    Celery task to clean up old crawled content records.
    Keeps only the most recent records for each data source.

    Args:
        days_to_keep: Number of days worth of records to keep

    Returns:
        Dict containing cleanup results
    """
    try:
        from datetime import timedelta

        from django.utils import timezone

        from .models import CrawledContent

        cutoff_date = timezone.now() - timedelta(days=days_to_keep)

        old_records = CrawledContent.objects.filter(crawl_date__lt=cutoff_date)

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
