"""Ingest the Bangladesh Bank lending-rate chart (housing + consumer bands).

Usage:
    python manage.py ingest_bb_lending_chart [--file chart.html]

Fetches the live chart (browser headers — BB rejects bare clients),
snapshots the edition, and upserts per-bank fallback bands. Idempotent:
re-running an unchanged edition writes nothing.
"""

from django.core.management.base import BaseCommand

from loans.ingestion.bb_lending_chart import fetch_chart_html, ingest_lending_chart


class Command(BaseCommand):
    help = "Fetch and ingest the BB lending chart into LoanChartBand rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            dest="file",
            default="",
            help="Read chart HTML from a local file instead of fetching live.",
        )

    def handle(self, *args, **options):
        if options["file"]:
            with open(options["file"], encoding="utf-8") as fh:
                html = fh.read()
            self.stdout.write(f"Read chart HTML from {options['file']}")
        else:
            html = fetch_chart_html()
            self.stdout.write("Fetched live BB lending chart")
        stats = ingest_lending_chart(html)
        self.stdout.write(
            "Edition {edition}: {banks_seen} banks, {bands_written} bands "
            "({bands_created} created, {bands_updated} updated), "
            "snapshot_created={snapshot_created}".format(**stats)
        )
        for anomaly in stats["anomalies"]:
            self.stdout.write(self.style.WARNING(f"anomaly: {anomaly}"))
