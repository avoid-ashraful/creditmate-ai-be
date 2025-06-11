from django.core.management.base import BaseCommand, CommandError

from banks.models import Bank, BankDataSource
from banks.services import BankDataCrawlerService


class Command(BaseCommand):
    """Management command to manually trigger bank data crawling."""

    help = "Crawl bank credit card data from configured sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bank-id",
            type=int,
            help="ID of specific bank to crawl (crawls all if not specified)",
        )
        parser.add_argument(
            "--source-id",
            type=int,
            help="ID of specific data source to crawl",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be crawled without actually crawling",
        )

    def handle(self, *args, **options):  # noqa: C901
        bank_id = options.get("bank_id")
        source_id = options.get("source_id")
        dry_run = options.get("dry_run")

        crawler = BankDataCrawlerService()

        if source_id:
            # Crawl specific data source
            try:
                data_source = BankDataSource.objects.get(id=source_id)
                if dry_run:
                    self.stdout.write(
                        f"Would crawl data source: {data_source.bank.name} - {data_source.url}"
                    )
                    return

                self.stdout.write(
                    f"Crawling data source: {data_source.bank.name} - {data_source.url}"
                )
                success = crawler.crawl_bank_data_source(source_id)

                if success:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully crawled data source {source_id}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"Failed to crawl data source {source_id}")
                    )

            except BankDataSource.DoesNotExist:
                raise CommandError(f"Data source with ID {source_id} does not exist")

        elif bank_id:
            # Crawl specific bank
            try:
                bank = Bank.objects.get(id=bank_id)
                data_sources = BankDataSource.objects.filter(bank=bank, is_active=True)

                if dry_run:
                    self.stdout.write(
                        f"Would crawl {data_sources.count()} data sources for {bank.name}"
                    )
                    for source in data_sources:
                        self.stdout.write(f"  - {source.url} ({source.content_type})")
                    return

                self.stdout.write(
                    f"Crawling {data_sources.count()} data sources for {bank.name}"
                )

                successful = 0
                failed = 0

                for data_source in data_sources:
                    self.stdout.write(f"  Crawling: {data_source.url}")
                    if crawler.crawl_bank_data_source(data_source.id):
                        successful += 1
                        self.stdout.write("    ✓ Success")
                    else:
                        failed += 1
                        self.stdout.write("    ✗ Failed")

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed crawling for {bank.name}: {successful} successful, {failed} failed"
                    )
                )

            except Bank.DoesNotExist:
                raise CommandError(f"Bank with ID {bank_id} does not exist")

        else:
            # Crawl all active data sources
            active_sources = BankDataSource.objects.filter(is_active=True)

            if dry_run:
                self.stdout.write(
                    f"Would crawl {active_sources.count()} active data sources: "
                )
                for source in active_sources:
                    self.stdout.write(
                        f"  - {source.bank.name}: {source.url} ({source.content_type})"
                    )
                return

            self.stdout.write(f"Crawling {active_sources.count()} active data sources")

            results = crawler.crawl_all_active_sources()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Completed crawling: {results['successful']} successful, "
                    f"{results['failed']} failed out of {results['total']} total"
                )
            )

        # Show summary of current data sources
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("Current Data Sources Summary:")
        self.stdout.write("=" * 50)

        for bank in Bank.objects.filter(is_active=True):
            sources = bank.data_sources.all()
            active_count = sources.filter(is_active=True).count()
            failing_count = sources.filter(failed_attempt_count__gte=5).count()

            self.stdout.write(f"\n{bank.name}: ")
            self.stdout.write(f"  Total sources: {sources.count()}")
            self.stdout.write(f"  Active sources: {active_count}")
            if failing_count > 0:
                self.stdout.write(f"  Failing sources: {failing_count}")

            for source in sources:
                status = "✓" if source.is_active else "✗"
                failure_info = (
                    f" (failed: {source.failed_attempt_count})"
                    if source.failed_attempt_count > 0
                    else ""
                )
                self.stdout.write(f"    {status} {source.url}{failure_info}")
