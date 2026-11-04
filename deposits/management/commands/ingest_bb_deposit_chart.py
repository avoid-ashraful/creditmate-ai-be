"""Ingest one edition of the Bangladesh Bank deposit-rate charts.

Fetches both charts (conventional + Islamic window), snapshots each
edition, and upserts the generic per-bank FDR products and their rate
bands. Deterministic and idempotent — safe to run nightly; a re-run on
an unchanged edition writes nothing.

Usage:
    python manage.py ingest_bb_deposit_chart
    python manage.py ingest_bb_deposit_chart --file conv.html --source conventional
"""

import json

from django.core.management.base import BaseCommand, CommandError

from deposits.constants import BB_DEPOSIT_CHART_URLS, ChartSource
from deposits.ingestion.bb_chart import fetch_chart_html, ingest_chart


class Command(BaseCommand):
    help = "Parse and ingest the Bangladesh Bank announced deposit-rate charts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            help="Parse a saved chart HTML file instead of fetching live.",
        )
        parser.add_argument(
            "--source",
            choices=[c.value for c in ChartSource],
            help="With --file: which chart the file contains.",
        )
        parser.add_argument(
            "--only",
            choices=[c.value for c in ChartSource],
            help="Fetch only this chart (live mode).",
        )

    def handle(self, *args, **options):
        if options["file"]:
            if not options["source"]:
                raise CommandError("--source is required with --file")
            source = ChartSource(options["source"])
            with open(options["file"], encoding="utf-8") as fh:
                html = fh.read()
            report = ingest_chart(html, source, BB_DEPOSIT_CHART_URLS[source])
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        sources = [ChartSource(options["only"])] if options["only"] else list(ChartSource)
        for source in sources:
            url = BB_DEPOSIT_CHART_URLS[source]
            self.stdout.write(f"Fetching {source} chart: {url}")
            html = fetch_chart_html(url)
            report = ingest_chart(html, source, url)
            self.stdout.write(json.dumps(report, indent=2, default=str))
