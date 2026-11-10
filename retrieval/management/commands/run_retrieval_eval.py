"""Run the golden-set retrieval evaluation (cosine vs hybrid).

Requires a populated pgvector index (see backfill_embeddings). Prints a
JSON summary; used for the tuning sweep in the consolidated test pass.
"""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Evaluate retrieval quality (Recall@5/@10, MRR) for cosine vs hybrid."

    def handle(self, *args, **options):
        from retrieval.evaluation import compare_modes

        results = compare_modes()
        self.stdout.write(json.dumps(results, indent=2, default=str))
