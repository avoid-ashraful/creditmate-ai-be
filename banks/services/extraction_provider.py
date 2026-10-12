"""Provider interfaces for the multi-pass LLM extraction pipeline.

Phase 2.1 of ``docs/improvements.md`` moves extraction from one monolithic
prompt to a sequence of passes. To keep those passes unit-testable without
spending money on real LLM calls (or crawling live documents), the extractor
depends on this narrow provider interface instead of on a concrete vendor
client.

Any object implementing :class:`ExtractionProvider` can be injected:

* :class:`OrchestratorExtractionProvider` wraps the existing
  ``common.llm`` orchestrator (OpenRouter / Gemini) for production use.
* Test doubles (fakes) return canned JSON responses and record the prompts they
  received, which is how the extraction test suite runs offline.
"""

from typing import Any, Dict, Protocol, runtime_checkable

from common.llm import LLMOrchestrator


@runtime_checkable
class ExtractionProvider(Protocol):
    """Interface used by the multi-pass extractor to reach an LLM.

    Implementations must be safe to call multiple times; the extractor calls
    :meth:`generate_response` once per extraction pass.
    """

    def generate_response(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        """Generate a raw LLM response for a prompt.

        Parameters
        ----------
        prompt : str
            The prompt to send to the model.
        **kwargs : Any
            Provider tuning parameters (``max_retries``, ``temperature``,
            ``max_tokens``, ...).

        Returns
        -------
        dict
            Mapping with at least ``response`` (raw model text) and ``provider``
            (name of the provider that produced it).
        """
        ...

    def is_available(self) -> bool:
        """Return True when the provider can serve requests."""
        ...


class OrchestratorExtractionProvider:
    """Adapter exposing the existing LLM orchestrator as an ExtractionProvider."""

    def __init__(self, orchestrator=None):
        """Initialize the adapter.

        Parameters
        ----------
        orchestrator : LLMOrchestrator, optional
            Orchestrator to wrap. A default orchestrator (OpenRouter + Gemini)
            is created when omitted.
        """
        self.orchestrator = orchestrator or LLMOrchestrator()

    def is_available(self):
        """Return True when at least one underlying provider is configured.

        Returns
        -------
        bool
            True when a provider is available.
        """
        return bool(self.orchestrator.is_any_provider_available())

    def generate_response(self, prompt, **kwargs):
        """Generate a response through the orchestrator.

        Parameters
        ----------
        prompt : str
            The prompt to send.
        **kwargs : Any
            Passed straight to the orchestrator.

        Returns
        -------
        dict
            Orchestrator result containing ``response`` and ``provider``.
        """
        return self.orchestrator.generate_response(prompt=prompt, **kwargs)
