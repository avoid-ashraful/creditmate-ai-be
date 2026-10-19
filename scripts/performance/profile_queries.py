"""Measure cold/warm API query budgets and EXPLAIN captured read queries."""

import argparse
import json
import os
import time
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.performance.local_settings")
django.setup()

from django.core.cache import cache  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from credit_cards.models import CreditCard  # noqa: E402


def main():
    """Profile fixed populated queries with only Redis DB 6 cleared."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    args = parser.parse_args()
    from django.conf import settings

    assert settings.REDIS_CACHE_URL == "redis://127.0.0.1:6379/6"
    cards = list(CreditCard.objects.public().values_list("id", flat=True)[:3])
    client = Client(HTTP_HOST="127.0.0.1:8020")
    endpoints = {
        "list": "/api/v1/credit-cards/?annual_fee_max=5000&ordering=annual_fee",
        "detail": f"/api/v1/credit-cards/{cards[0]}/",
        "advanced-search": "/api/v1/credit-cards/advanced-search/?annual_fee_max=5000",
        "typeahead": "/api/v1/credit-cards/typeahead/?q=visa",
        "banks": "/api/v1/banks/",
        "compare": "/api/v1/credit-cards/?ids=" + ",".join(map(str, cards)),
    }
    results = {}
    for name, url in endpoints.items():
        cache.clear()
        rounds = []
        for temperature in ("cold", "warm"):
            start = time.perf_counter()
            with CaptureQueriesContext(connection) as captured:
                response = client.get(url)
            assert response.status_code == 200, (url, response.status_code)
            elapsed_ms = (time.perf_counter() - start) * 1000
            queries = list(captured.captured_queries)
            plans = []
            if temperature == "cold":
                for query in sorted(
                    queries, key=lambda q: float(q["time"]), reverse=True
                )[:3]:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query["sql"]
                        )
                        plans.append({"sql": query["sql"], "plan": cursor.fetchone()[0]})
            rounds.append(
                {
                    "cache": temperature,
                    "queries": len(queries),
                    "elapsed_ms": round(elapsed_ms, 3),
                    "sql_ms": round(sum(float(q["time"]) for q in queries) * 1000, 3),
                    "query_sql": [q["sql"] for q in queries],
                    "plans": plans,
                }
            )
        results[name] = rounds
    output = Path("docs/development/performance-results") / f"{args.label}-queries.json"
    output.write_text(json.dumps(results, indent=2))
    for name, rounds in results.items():
        print(name, [(r["cache"], r["queries"], r["sql_ms"]) for r in rounds])


if __name__ == "__main__":
    main()
