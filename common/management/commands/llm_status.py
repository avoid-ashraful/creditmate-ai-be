import time

from django.core.management.base import BaseCommand

from common.llm.services import LLMOrchestrator


class Command(BaseCommand):
    help = "Show LLM providers, their availability and the fallback order"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ping",
            action="store_true",
            help="Make one tiny call to every available provider (uses quota)",
        )

    def handle(self, *args, **options):
        orchestrator = LLMOrchestrator()
        self.stdout.write(f"Provider order: {', '.join(orchestrator.provider_order)}")

        for name, provider in orchestrator.providers.items():
            available = provider.is_available()
            self.stdout.write(f"{name}: {'available' if available else 'unavailable'}")
            if available and options["ping"]:
                self.stdout.write(f"  ping: {self._ping(provider)}")

    def _ping(self, provider):
        """Make one tiny call and describe the outcome (never prints keys)."""
        started = time.monotonic()
        try:
            response = provider.generate_response("Respond with exactly: OK")
        except Exception as e:
            return f"error ({time.monotonic() - started:.1f}s): {type(e).__name__}: {e}"
        return f"ok ({time.monotonic() - started:.1f}s): {response[:40]!r}"
