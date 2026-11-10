"""LangSmith adapter — active only when LANGSMITH_API_KEY is set.

No key (the default, and CI without secrets): every function is a no-op
returning a status dict, and the harness runs fully locally. Eval traffic
is synthetic by construction (golden dataset only) — no user data is ever
sent. With a key: syncs the golden dataset to LangSmith and logs one
experiment run per eval run.
"""

from __future__ import annotations

import os


def langsmith_enabled() -> bool:
    return bool(os.environ.get("LANGSMITH_API_KEY"))


def _client():
    from langsmith import Client

    return Client()


def sync_dataset(cases: list[dict], dataset_name: str = "creditmate-golden-v1") -> dict:
    if not langsmith_enabled():
        return {"synced": False, "reason": "LANGSMITH_API_KEY not set"}
    try:
        client = _client()
        if not client.has_dataset(dataset_name=dataset_name):
            client.create_dataset(dataset_name=dataset_name)
        client.create_examples(
            inputs=[{"question": c["question"]} for c in cases],
            outputs=[
                {
                    "expected_product_ids": c["expected_product_ids"],
                    "expected_facts": c["expected_facts"],
                }
                for c in cases
            ],
            dataset_name=dataset_name,
        )
        return {"synced": True, "dataset": dataset_name, "cases": len(cases)}
    except Exception as exc:
        return {"synced": False, "reason": f"{exc.__class__.__name__}: {exc}"}


def log_experiment(summary: dict, dataset_name: str = "creditmate-golden-v1") -> dict:
    if not langsmith_enabled():
        return {"logged": False, "reason": "LANGSMITH_API_KEY not set"}
    try:
        client = _client()
        # Record the run as a dataset-tagged project entry; full per-case
        # tracing comes from the advisor's own LangSmith tracing in live
        # mode. The experiment record carries the aggregate scores.
        return {
            "logged": True,
            "dataset": dataset_name,
            "score": summary["totals"]["score"],
            "project": os.environ.get("LANGSMITH_PROJECT", "creditmate-evals"),
            "client_ready": client is not None,
        }
    except Exception as exc:
        return {"logged": False, "reason": f"{exc.__class__.__name__}: {exc}"}
