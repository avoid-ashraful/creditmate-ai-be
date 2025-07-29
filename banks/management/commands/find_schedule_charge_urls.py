from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from banks.models import Bank
from banks.services import ScheduleChargeURLFinder


class Command(BaseCommand):
    help = "Find schedule of charges URLs for banks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bank-id",
            type=int,
            help="Process only the specified bank ID",
        )
        parser.add_argument(
            "--bank-name",
            type=str,
            help="Process only the specified bank name (case-insensitive)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update schedule_charge_url even if it already exists",
        )

    def handle(self, *args, **options):
        """Main command handler."""
        self.style = self.style  # Enable colored output

        finder = ScheduleChargeURLFinder()
        banks_to_process = self._get_banks_to_process(options)

        if not banks_to_process:
            self.stdout.write(self.style.WARNING("No banks found matching the criteria."))
            return

        self._print_processing_header(len(banks_to_process))
        results = self._initialize_results()

        for bank in banks_to_process:
            self._process_single_bank(bank, finder, options, results)

        self._print_summary(results, options)

    def _initialize_results(self):
        """Initialize results tracking dictionary."""
        return {"total": 0, "found": 0, "not_found": 0, "updated": 0, "errors": 0}

    def _print_processing_header(self, bank_count):
        """Print the processing header message."""
        self.stdout.write(
            self.style.SUCCESS(
                f"Processing {bank_count} bank(s) for schedule charge URL detection..."
            )
        )

    def _process_single_bank(self, bank, finder, options, results):
        """Process a single bank for schedule charge URL detection."""
        self.stdout.write(f"\n🏦 Processing: {bank.name}")
        self.stdout.write(f"   Website: {bank.website}")
        results["total"] += 1

        # Check skip conditions
        if self._should_skip_bank(bank, options):
            return

        if not bank.website:
            self._handle_no_website(results)
            return

        try:
            result = finder.find_schedule_charge_url(bank.website)
            self._handle_finder_result(bank, result, options, results)
        except Exception as e:
            self._handle_processing_error(e, results)

    def _should_skip_bank(self, bank, options):
        """Check if bank should be skipped based on existing URL and force option."""
        if bank.schedule_charge_url and not options.get("force", False):
            self.stdout.write(
                self.style.WARNING(
                    f"   ⏭️  Skipping (schedule_charge_url already exists: {bank.schedule_charge_url})"
                )
            )
            self.stdout.write("   💡 Use --force to update existing URLs")
            return True
        return False

    def _handle_no_website(self, results):
        """Handle banks with no website configured."""
        self.stdout.write(
            self.style.WARNING("   ⚠️  Skipping (no website URL configured)")
        )
        results["not_found"] += 1

    def _handle_finder_result(self, bank, result, options, results):
        """Handle the result from the schedule charge URL finder."""
        if result["found"]:
            self._handle_successful_find(bank, result, options, results)
        else:
            self._handle_unsuccessful_find(result, results)

    def _handle_successful_find(self, bank, result, options, results):
        """Handle successful URL discovery."""
        self.stdout.write(self.style.SUCCESS(f"   ✅ Found URL: {result['url']}"))
        self.stdout.write(f"   📝 Method: {result['method']}")

        if "pattern" in result:
            self.stdout.write(f"   🔍 Pattern: {result['pattern']}")

        results["found"] += 1

        if not options.get("dry_run", False):
            self._update_bank_record(bank, result["url"], results)
        else:
            self.stdout.write(
                self.style.WARNING("   🔍 DRY RUN: Would update bank record")
            )

    def _handle_unsuccessful_find(self, result, results):
        """Handle unsuccessful URL discovery."""
        self.stdout.write(
            self.style.ERROR(f"   ❌ Not found - {result.get('error', 'Unknown error')}")
        )
        self.stdout.write(f"   📝 Method attempted: {result.get('method', 'unknown')}")
        results["not_found"] += 1

    def _update_bank_record(self, bank, url, results):
        """Update the bank record with the found URL."""
        with transaction.atomic():
            bank.schedule_charge_url = url
            bank.save(update_fields=["schedule_charge_url"])

        self.stdout.write(self.style.SUCCESS("   💾 Bank record updated successfully"))
        results["updated"] += 1

    def _handle_processing_error(self, error, results):
        """Handle processing errors."""
        self.stdout.write(self.style.ERROR(f"   💥 Error: {str(error)}"))
        results["errors"] += 1

    def _print_summary(self, results, options):
        """Print the final summary of results."""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("📊 SUMMARY:"))
        self.stdout.write(f"   Total banks processed: {results['total']}")
        self.stdout.write(f"   URLs found: {results['found']}")
        self.stdout.write(f"   URLs not found: {results['not_found']}")
        self.stdout.write(f"   Records updated: {results['updated']}")

        if results["errors"] > 0:
            self.stdout.write(
                self.style.ERROR(f"   Errors encountered: {results['errors']}")
            )

        if options.get("dry_run", False):
            self.stdout.write(
                self.style.WARNING(
                    "\n🔍 This was a DRY RUN - no changes were made to the database."
                )
            )

    def _get_banks_to_process(self, options):
        """Get the list of banks to process based on command options."""
        queryset = Bank.objects.filter(is_active=True)

        if options.get("bank_id"):
            try:
                return [queryset.get(id=options["bank_id"])]
            except Bank.DoesNotExist:
                raise CommandError(f"Bank with ID {options['bank_id']} not found")

        if options.get("bank_name"):
            banks = queryset.filter(name__icontains=options["bank_name"])
            if not banks.exists():
                raise CommandError(
                    f"No banks found matching name: {options['bank_name']}"
                )
            return list(banks)

        return list(queryset.order_by("name"))
