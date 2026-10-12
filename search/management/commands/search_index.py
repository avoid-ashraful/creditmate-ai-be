"""Index lifecycle command: create, rebuild, sync and status.

Examples
--------
    python manage.py search_index --create
    python manage.py search_index --rebuild
    python manage.py search_index --sync
    python manage.py search_index --status
    python manage.py search_index --rebuild --no-drop
"""

from django.core.management.base import BaseCommand, CommandError

from search import queue as queue_module
from search.documents import BANK_FILTERABLE_FIELDS, CREDIT_CARD_FILTERABLE_FIELDS
from search.queries import index_name
from search.service import SearchService


class Command(BaseCommand):
    """Manage the Elasticsearch indexes used by the search service."""

    help = "Create, rebuild, synchronise and inspect the search indexes"

    def add_arguments(self, parser):
        """Register the command options.

        Parameters
        ----------
        parser : argparse.ArgumentParser
            Argument parser provided by Django.

        Returns
        -------
        None
        """
        parser.add_argument(
            "--create", action="store_true", help="Create missing indexes"
        )
        parser.add_argument("--drop", action="store_true", help="Delete both indexes")
        parser.add_argument(
            "--rebuild", action="store_true", help="Rebuild from the database"
        )
        parser.add_argument(
            "--no-drop",
            action="store_true",
            help="Rebuild into the existing index instead of recreating it",
        )
        parser.add_argument("--sync", action="store_true", help="Drain the outbox queue")
        parser.add_argument(
            "--status", action="store_true", help="Print engine/index/queue status"
        )
        parser.add_argument(
            "--apply-synonyms",
            action="store_true",
            help="Re-apply the synonym configuration on existing indexes",
        )
        parser.add_argument("--batch-size", type=int, default=500, help="Bulk batch size")

    def handle(self, *args, **options):
        """Run the requested actions.

        Parameters
        ----------
        options : dict
            Parsed command options.

        Returns
        -------
        str
            Human readable summary written to stdout.
        """
        service = SearchService()
        if not service.available:
            raise CommandError(
                "Search service unavailable. Start the engine with "
                "`docker compose -f docker-compose.search.yml up -d` and "
                "check SEARCH_URL."
            )
        ran_action = False

        if options["drop"]:
            ran_action = True
            result = service.drop_indexes()
            self.stdout.write(f"dropped indexes: {result}")

        if options["rebuild"] or options["no_drop"]:
            ran_action = True
            summary = service.rebuild(
                drop=not options["no_drop"], batch_size=options["batch_size"]
            )
            for name, stats in summary.items():
                self.stdout.write(
                    f"rebuilt {name}: {stats['documents']} documents, "
                    f"{len(stats['errors'])} errors"
                )
                for error in stats["errors"][:5]:
                    self.stdout.write(f"  error: {error}")
        elif options["create"]:
            ran_action = True
            created = service.ensure_indexes()
            self.stdout.write(f"indexes: {created}")
            self.stdout.write(f"filterable fields (banks): {BANK_FILTERABLE_FIELDS}")
            self.stdout.write(
                f"filterable fields (cards): {CREDIT_CARD_FILTERABLE_FIELDS}"
            )

        if options["apply_synonyms"]:
            ran_action = True
            result = service.apply_synonyms()
            self.stdout.write(f"synonyms applied: {result}")

        if options["sync"]:
            ran_action = True
            summary = queue_module.drain(batch_size=options["batch_size"])
            self.stdout.write(f"queue drained: {summary}")

        if options["status"] or not ran_action:
            self.print_status(service)
        return ""

    def print_status(self, service):
        """Print engine, index and queue status.

        Parameters
        ----------
        service : SearchService
            Service instance to query.

        Returns
        -------
        None
        """
        status = service.status()
        engine = status.get("engine", {})
        engine_version = engine.get("number", status.get("engine_error", "unknown"))
        self.stdout.write(f"enabled: {status['enabled']} url={status['url']}")
        self.stdout.write(f"engine: Elasticsearch {engine_version}")
        for kind in ("banks", "cards"):
            name = index_name(kind)
            info = status["indexes"].get(name, {})
            self.stdout.write(
                f"index {name}: exists={info.get('exists')} "
                f"count={info.get('count')} health={info.get('health')}"
            )
        self.stdout.write(f"queue depth: {queue_module.queue_depth()}")
        self.stdout.write(f"synonyms: {status['synonyms']}")
