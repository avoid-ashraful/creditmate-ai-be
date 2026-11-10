"""LangGraph advisor graph (plan §7.2).

Shape::

    classify -> retrieve -> plan <-> tools -> budget_guard -> compose -> END
                              (loop, max ADVISOR_MAX_TOOL_STEPS steps)

Failure contract: ANY exception, timeout, budget exhaustion or invalid
structured output produces a *fallback* result — normal catalogue search
results plus a plain notice — never a 500. The fallback is built here,
not in the view, so API, SSE and tests all share it.

Checkpointer: a Postgres-backed LangGraph checkpointer would need a
separate psycopg (v3) connection pool alongside Django's psycopg2 stack.
Until that is introduced deliberately, an in-memory saver is used and
conversation continuity is owned by ``AdvisorSession`` /
``AdvisorMessage`` rows in Django's own database (which is also what the
API actually serves). TODO(checkpointer): adopt
``langgraph-checkpoint-postgres`` when the psycopg3 pool lands.

Honesty enforcement lives in ``compose``: forbidden phrases
("pre-approved", "guaranteed") reject the draft and force one repair
retry with a plain grounded template, then the honesty path.
"""

import logging
import time
from typing import TypedDict

from django.conf import settings

from advisor.tools import (
    TOOL_REGISTRY,
    AdvisorAnswer,
    SuggestedAction,
    citations_from_output,
    contains_forbidden_phrase,
    run_tool,
)
from common.llm.budget import llm_call_budget
from common.llm.chat import ChatTurn, ToolCallRequest, get_chat_provider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are CreditMate AI's card advisor for Bangladesh. You may state "
    "fees, APRs, income requirements and rate bands ONLY from tool "
    "results provided in this conversation — never from memory. Loan "
    "rates are ranges (bands), never a single figure. Islamic products "
    "are priced by expected profit, never interest, and Islamic cards "
    "publish no APR. Eligibility language is limited to: Eligible, "
    "Likely, No published requirement, Not yet. Never say a user is "
    "pre-approved or guaranteed a product; banks make the final "
    "decision. When the tools return nothing, say you don't have "
    "published data for that."
)

INTENT_TOOLS = {
    "eligibility": "check_eligibility",
    "calculator": "calculate_emi_or_payoff",
    "compare": "compare_cards",
    "products": "search_products",
    "search": "search_cards",
    "general": "search_cards",
}


class AdvisorState(TypedDict, total=False):
    user_text: str
    intent: str
    tool_results: list
    tool_trace: list
    citations: list
    steps: int
    draft_text: str
    answer: dict
    error: str
    pending_call: object


def classify_intent(text: str) -> str:
    """Cheap keyword classification — deterministic, no LLM call spent."""
    lowered = (text or "").lower()
    if any(w in lowered for w in ("eligible", "qualify", "income", "tin", "cib")):
        return "eligibility"
    if any(
        w in lowered for w in ("emi", "payoff", "pay off", "instalment", "installment")
    ):
        return "calculator"
    if "compare" in lowered or " vs " in lowered or "versus" in lowered:
        return "compare"
    if any(
        w in lowered
        for w in ("deposit", "fdr", "dps", "loan", "savings account", "current account")
    ):
        return "products"
    return "search"


def _classify_node(state):
    return {"intent": classify_intent(state["user_text"])}


def _retrieve_node(state):
    """Best-effort semantic grounding; absence degrades silently."""
    try:
        output, latency = run_tool("retrieve_grounding", {"query": state["user_text"]})
        results = list(state.get("tool_results") or [])
        trace = list(state.get("tool_trace") or [])
        results.append(
            {"tool": "retrieve_grounding", "result": output.model_dump(mode="json")}
        )
        trace.append(
            {
                "tool": "retrieve_grounding",
                "args_hash": _hash({"query": state["user_text"]}),
                "latency_ms": latency,
            }
        )
        return {"tool_results": results, "tool_trace": trace}
    except Exception:
        return {}


def _hash(args):
    from advisor.tools import args_hash

    return args_hash(args)


def build_graph(provider=None):
    """Compile the LangGraph graph around ``provider`` (fake by default)."""
    from langgraph.graph import END, START, StateGraph

    provider = provider or get_chat_provider()
    max_steps = int(getattr(settings, "ADVISOR_MAX_TOOL_STEPS", 6))
    available = list(TOOL_REGISTRY)

    def plan_node(state):
        turn = provider.chat(
            system_prompt=SYSTEM_PROMPT,
            user_text=state["user_text"],
            tool_results=state.get("tool_results") or [],
            available_tools=available,
        )
        if turn.tool_call is not None:
            return {"pending_call": turn.tool_call, "draft_text": ""}
        return {"pending_call": None, "draft_text": turn.text}

    def tools_node(state):
        call: ToolCallRequest = state["pending_call"]
        results = list(state.get("tool_results") or [])
        trace = list(state.get("tool_trace") or [])
        citations = list(state.get("citations") or [])
        try:
            output, latency = run_tool(call.name, call.args)
            results.append({"tool": call.name, "result": output.model_dump(mode="json")})
            trace.append(
                {
                    "tool": call.name,
                    "args_hash": _hash(call.args),
                    "latency_ms": latency,
                }
            )
            for citation in citations_from_output(output):
                if citation not in citations:
                    citations.append(citation)
        except Exception as exc:  # tool failure: tell the planner, don't crash
            results.append({"tool": call.name, "error": type(exc).__name__})
            trace.append(
                {"tool": call.name, "args_hash": _hash(call.args), "latency_ms": 0}
            )
        return {
            "tool_results": results,
            "tool_trace": trace,
            "citations": citations,
            "steps": int(state.get("steps") or 0) + 1,
            "pending_call": None,
        }

    def route_after_plan(state):
        if (
            state.get("pending_call") is not None
            and int(state.get("steps") or 0) < max_steps
        ):
            return "tools"
        return "budget_guard"

    def budget_guard_node(state):
        return {}

    def compose_node(state):
        draft = (state.get("draft_text") or "").strip()
        citations = list(state.get("citations") or [])
        notes = []
        if not draft:
            draft = "I don't have published data for that."
            notes.append("No grounded answer could be composed from tool results.")
        if contains_forbidden_phrase(draft):
            # One repair attempt: replace the draft with a grounded,
            # vocabulary-safe template built from the citations we hold.
            draft = _grounded_template(state)
            notes.append("Draft contained forbidden wording and was replaced.")
            if contains_forbidden_phrase(draft):
                raise ValueError("honesty check failed after repair")
        cited_ids = [c.product_id for c in citations if c.product_id]
        actions = [
            SuggestedAction(
                kind="save_to_shortlist",
                label=f"Save {c.label} to your shortlist",
                product_type=c.product_type,
                product_id=c.product_id,
                slug=c.slug,
            )
            for c in citations[:3]
            if c.product_type == "cards" and c.product_id
        ]
        answer = AdvisorAnswer(
            answer_markdown=draft,
            cited_product_ids=cited_ids,
            citations=citations,
            suggested_actions=actions,
            confidence_notes=notes,
        )
        return {"answer": answer.model_dump(mode="json")}

    graph = StateGraph(AdvisorState)
    graph.add_node("classify", _classify_node)
    graph.add_node("retrieve", _retrieve_node)
    graph.add_node("plan", plan_node)
    graph.add_node("tools", tools_node)
    graph.add_node("budget_guard", budget_guard_node)
    graph.add_node("compose", compose_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "plan")
    graph.add_conditional_edges(
        "plan", route_after_plan, {"tools": "tools", "budget_guard": "budget_guard"}
    )
    graph.add_edge("tools", "plan")
    graph.add_edge("budget_guard", "compose")
    graph.add_edge("compose", END)
    # TODO(checkpointer): Postgres checkpointer once a psycopg3 pool exists;
    # sessions are persisted via AdvisorSession/AdvisorMessage meanwhile.
    from langgraph.checkpoint.memory import MemorySaver

    return graph.compile(checkpointer=MemorySaver())


def _grounded_template(state) -> str:
    citations = state.get("citations") or []
    if citations:
        labels = ", ".join(c.label for c in citations[:5])
        return (
            "Based on CreditMate's published catalogue data, these options "
            f"came up: {labels}. The published figures are in the "
            "citations below; the issuing bank makes the final decision "
            "on any application."
        )
    return "I don't have published data for that."


def fallback_answer(user_text: str, reason: str = "") -> AdvisorAnswer:
    """Normal search results + a plain notice — the graceful degradation."""
    citations = []
    lines = [
        "The advisor is unavailable right now, so here are the normal "
        "search results for your question instead."
    ]
    try:
        output, _ = run_tool("search_cards", {"query": user_text, "limit": 5})
        citations = citations_from_output(output)
        for summary in output.cards:
            lines.append(
                f"- {summary.bank_name} {summary.name}"
                + (
                    f" — annual fee BDT {summary.annual_fee_bdt}"
                    if summary.annual_fee_bdt
                    else ""
                )
                + (
                    f", APR {summary.apr_percent}%"
                    if summary.apr_percent
                    else ", APR not published"
                )
            )
    except Exception:
        logger.exception("advisor fallback search failed")
    return AdvisorAnswer(
        answer_markdown="\n".join(lines),
        cited_product_ids=[c.product_id for c in citations if c.product_id],
        citations=citations,
        confidence_notes=[f"fallback: {reason}"] if reason else ["fallback"],
        is_fallback=True,
    )


def run_advisor(user_text: str, provider=None, timeout_seconds: float | None = None):
    """Run one advisor turn. Returns (AdvisorAnswer, tool_trace).

    Never raises for model/tool problems — those become fallbacks. The
    wall-clock timeout uses a soft deadline check around the synchronous
    graph run (the graph itself is step-capped).
    """
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(getattr(settings, "ADVISOR_TIMEOUT_SECONDS", 20))
    )
    started = time.perf_counter()
    try:
        app = build_graph(provider=provider)
        budget_limit = int(getattr(settings, "ADVISOR_MAX_LLM_CALLS", 12))
        with llm_call_budget(limit=budget_limit):
            final = app.invoke(
                {
                    "user_text": user_text,
                    "steps": 0,
                    "tool_results": [],
                    "tool_trace": [],
                },
                config={"configurable": {"thread_id": "advisor-run"}},
            )
        if time.perf_counter() - started > timeout:
            raise TimeoutError("advisor run exceeded its time budget")
        answer = AdvisorAnswer.model_validate(final["answer"])
        return answer, final.get("tool_trace") or []
    except Exception as exc:
        logger.warning("advisor run fell back: %s", type(exc).__name__)
        return fallback_answer(user_text, reason=type(exc).__name__), []
