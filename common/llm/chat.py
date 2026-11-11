"""Minimal chat / tool-calling interface for the advisor (plan §7.2).

The extraction pipeline uses :class:`~common.llm.base.BaseLLMProvider`
(``generate_response``). The advisor needs something slightly different: a
*chat* call that takes a system prompt plus the JSON-serialised tool
results so far and returns either text or a request to call one tool.

This module defines that contract as plain dataclasses — deliberately NOT
tied to any vendor SDK or to LangChain message types, so the graph in
``advisor.graph`` can be driven by any implementation:

- :class:`FakeChatProvider` — deterministic, offline; used by every test
  and by local development without a key. It never invents catalogue
  figures: with no script it asks for ``search_cards`` once and then
  composes an answer purely from the tool results it was given.
- :class:`OrchestratorChatProvider` — adapts the existing
  :class:`~common.llm.services.LLMOrchestrator`. The underlying providers
  are text-only today, so this adapter prompts for a strict JSON envelope
  (``{"tool": name, "args": {...}}`` or ``{"answer": "..."}``) and parses
  it. Invalid JSON degrades to a plain-text answer (never an exception
  leaking to the user).

Every call consumes from the per-run call budget in
:mod:`common.llm.budget` when one is open — the same accounting the
crawler already uses, so advisor runs are capped exactly like crawl runs.
"""

import json
from dataclasses import dataclass, field

from common.llm.budget import current_budget
from common.llm.exceptions import LLMBudgetExhaustedError


@dataclass
class ToolCallRequest:
    """The model asks to run one registered tool."""

    name: str
    args: dict = field(default_factory=dict)


@dataclass
class ChatTurn:
    """One chat-model response: either a tool request or final text."""

    text: str = ""
    tool_call: ToolCallRequest | None = None


class BaseChatProvider:
    """Interface every advisor chat provider implements."""

    name = "base"

    def chat(self, *, system_prompt, user_text, tool_results, available_tools):
        """Return a :class:`ChatTurn`.

        Parameters
        ----------
        system_prompt : str
        user_text : str
            The user's message for this turn.
        tool_results : list of dict
            ``[{"tool": name, "result": {...}}, ...]`` accumulated so far
            in this run. This is the ONLY source of catalogue figures the
            model may quote.
        available_tools : list of str
            Names of the read-only tools the model may request.
        """
        raise NotImplementedError


class FakeChatProvider(BaseChatProvider):
    """Deterministic offline provider for tests and keyless local dev.

    Behaviour, in order:

    1. If ``script`` was given, return its turns one by one (tests use
       this to drive specific tool loops, budget stops and failures —
       a script entry may also be an exception instance to raise).
    2. Otherwise, if no tool has run yet, request the first available of
       ``search_cards`` / ``retrieve_grounding`` with the user's text.
    3. Otherwise compose a grounded answer listing what the tools
       returned, or the honest "no published data" sentence when the
       tools returned nothing.
    """

    name = "fake"

    def __init__(self, script=None):
        self._script = list(script) if script is not None else None
        self.calls = 0

    # C901: test fake — branches emulate provider scenarios
    # (tool calls, errors, fallbacks).
    def chat(  # noqa: C901
        self, *, system_prompt, user_text, tool_results, available_tools
    ):
        self.calls += 1
        budget = current_budget()
        if budget is not None and not budget.consume():
            raise LLMBudgetExhaustedError("LLM call budget exhausted")
        if self._script is not None:
            if not self._script:
                return ChatTurn(text="I don't have published data for that.")
            turn = self._script.pop(0)
            if isinstance(turn, Exception):
                raise turn
            return turn
        has_catalogue_result = any(
            (entry.get("result") or {}).get("cards")
            or (entry.get("result") or {}).get("products")
            or (entry.get("result") or {}).get("results")
            for entry in tool_results
        )
        already_searched = any(
            entry.get("tool") == "search_cards" for entry in tool_results
        )
        if not has_catalogue_result and not already_searched:
            for preferred in ("search_cards", "retrieve_grounding"):
                if preferred in available_tools:
                    return ChatTurn(
                        tool_call=ToolCallRequest(
                            name=preferred, args={"query": user_text}
                        )
                    )
            return ChatTurn(text="I don't have published data for that.")
        names = []
        for entry in tool_results:
            result = entry.get("result") or {}
            for card in result.get("cards") or result.get("results") or []:
                label = card.get("name") or ""
                bank = card.get("bank_name") or ""
                if label:
                    names.append(f"{bank} {label}".strip())
            for product in result.get("products") or []:
                label = product.get("name") or ""
                if label:
                    names.append(label)
        if names:
            listing = "; ".join(names[:5])
            return ChatTurn(
                text=(
                    "Based on CreditMate's published catalogue data, these "
                    f"options came up: {listing}. Figures shown in the "
                    "citations below are the published figures for each "
                    "product."
                )
            )
        return ChatTurn(text="I don't have published data for that.")


class OrchestratorChatProvider(BaseChatProvider):
    """Adapt the text-only :class:`LLMOrchestrator` to the chat contract."""

    name = "orchestrator"

    _ENVELOPE_INSTRUCTION = (
        "Respond with ONE JSON object and nothing else: either "
        '{"tool": "<tool name>", "args": {...}} to request a tool, or '
        '{"answer": "<final answer in markdown>"} when you can answer '
        "from the tool results provided. Never state a fee, APR, income "
        "requirement or rate that is not present in the tool results."
    )

    def chat(self, *, system_prompt, user_text, tool_results, available_tools):
        from common.llm.services import LLMOrchestrator

        prompt = (
            f"User: {user_text}\n\n"
            f"Available tools: {', '.join(available_tools)}\n\n"
            f"Tool results so far (the only source of figures you may "
            f"quote):\n{json.dumps(tool_results, default=str)[:12000]}\n\n"
            f"{self._ENVELOPE_INSTRUCTION}"
        )
        raw = LLMOrchestrator().generate_response(prompt, system_prompt=system_prompt)
        return parse_chat_envelope(raw)


def parse_chat_envelope(raw):
    """Parse an orchestrator reply into a :class:`ChatTurn`.

    Non-JSON replies degrade to a plain-text turn — the graph's output
    validation and honesty checks remain the safety net.
    """
    if not raw:
        return ChatTurn(text="")
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            if data.get("tool"):
                args = data.get("args") or {}
                return ChatTurn(
                    tool_call=ToolCallRequest(
                        name=str(data["tool"]),
                        args=args if isinstance(args, dict) else {},
                    )
                )
            if data.get("answer"):
                return ChatTurn(text=str(data["answer"]))
    return ChatTurn(text=text)


def get_chat_provider():
    """Return the configured advisor chat provider.

    ``settings.ADVISOR_CHAT_PROVIDER``: ``"fake"`` (default — offline and
    safe) or ``"orchestrator"`` (real providers via the existing
    orchestrator, subject to keys and the free-tier budget).
    """
    from django.conf import settings

    if getattr(settings, "ADVISOR_CHAT_PROVIDER", "fake") == "orchestrator":
        return OrchestratorChatProvider()
    return FakeChatProvider()
