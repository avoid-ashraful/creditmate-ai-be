from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from banks.models import Bank, BankDataSource
from banks.services import BankDataCrawlerService
from common.llm.budget import llm_call_budget


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
            "--bank-names",
            help=(
                "Comma-separated bank names to crawl (case-insensitive contains "
                "match, e.g. 'brac,city')"
            ),
        )
        parser.add_argument(
            "--max-llm-calls",
            type=int,
            help=(
                "Stop extracting once this many LLM calls were made in this run "
                "(default: LLM_MAX_CALLS_PER_RUN, 0 = unlimited)"
            ),
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

    def handle(self, *args, **options):
        with llm_call_budget(options.get("max_llm_calls")) as budget:
            self._crawl(budget, **options)
        self.stdout.write(f"LLM calls used: {budget.used}")

    def _crawl_banks_by_name(self, names, dry_run):
        """Crawl the active sources of every bank matching one of ``names``."""
        wanted = [name.strip() for name in names.split(",") if name.strip()]
        if not wanted:
            raise CommandError("--bank-names needs at least one name")
        match = Q()
        for name in wanted:
            match |= Q(name__icontains=name)
        banks = list(Bank.objects.filter(match).order_by("name"))
        if not banks:
            raise CommandError(f"No bank matches {', '.join(wanted)}")

        sources = list(
            BankDataSource.objects.filter(bank__in=banks, is_active=True).order_by(
                "bank__name", "id"
            )
        )
        self.stdout.write(
            f"Matched {len(banks)} banks ({', '.join(b.name for b in banks)}) "
            f"with {len(sources)} active data sources"
        )
        if dry_run:
            for source in sources:
                self.stdout.write(f"  - {source.bank.name}: {source.url}")
            return

        results = BankDataCrawlerService().crawl_sources(sources)
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed crawling: {results['successful']} successful, "
                f"{results['failed']} failed, {results['skipped']} left for the "
                f"next run out of {results['total']} total"
            )
        )

    def _crawl(self, budget, **options):  # noqa: C901
        bank_id = options.get("bank_id")
        source_id = options.get("source_id")
        dry_run = options.get("dry_run")

        crawler = BankDataCrawlerService()

        if options.get("bank_names"):
            self._crawl_banks_by_name(options["bank_names"], dry_run)

        elif source_id:
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
                    if budget.exhausted:
                        self.stdout.write(
                            self.style.WARNING(
                                "  LLM call budget exhausted; remaining sources "
                                "are left for the next run"
                            )
                        )
                        break
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
                    f"{results['failed']} failed, {results['skipped']} left for the "
                    f"next run out of {results['total']} total"
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
